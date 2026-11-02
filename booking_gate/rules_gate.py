"""Release-gate rules: each one sends an input and proves what the API did with it.

A rule is one function returning an Outcome. It talks to the API through Run, which records
every request and response as evidence. The evaluate_* functions are pure, so the unit tests
replay recorded responses through the same logic the live run uses.
"""
import json
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .client import Unreachable, booking_path, ids_in
from .verdict import PASS, SANITY_RULE, Inconclusive, failed, inconclusive, passed, rule_decorator

RULES = []
rule = rule_decorator(RULES)


@dataclass
class Result:
    rule_id: str
    title: str
    severity: str
    why: str
    status: str
    message: str
    exchanges: list


class Run:
    """One gate run: the marker, the bookings created, and the evidence for the current rule."""

    def __init__(self, client, marker):
        self.client, self.marker = client, marker
        self.created, self.exchanges = set(), []
        self.first_night = datetime.now(timezone.utc).date() + timedelta(days=30)

    def call(self, method, path, body=None, **options):
        """Send a request and keep it as evidence."""
        reply = self.client.request(method, path, body, **options)
        self.exchanges.append({"method": method, "path": path, "body": body,
                               "status": reply.status, "response": reply.text})
        if method == "POST" and isinstance(reply.json, dict) and "bookingid" in reply.json:
            self.created.add(reply.json["bookingid"])
        return reply

    def dates(self, nights=5, offset=0):
        """A stay in the future, so that only the rule under test can be the reason for a 4xx."""
        checkin = self.first_night + timedelta(days=offset)
        return {"checkin": checkin.isoformat(), "checkout": (checkin + timedelta(days=nights)).isoformat()}

    def booking(self, tag, **overrides):
        """A valid booking body. The tag in firstname isolates each rule's record."""
        body = {"firstname": tag, "lastname": self.marker, "totalprice": 250, "depositpaid": True,
                "bookingdates": self.dates(), "additionalneeds": "Breakfast"}
        return {**body, **overrides}

    def read(self, booking_id):
        """Read a booking this run created. A 404 means staging reset under us, not a bug."""
        reply = self.call("GET", f"/booking/{booking_id}")
        if reply.status == 404:
            raise Inconclusive(f"booking {booking_id} vanished mid-run (404); staging resets every ten minutes")
        record = reply.json
        if reply.status != 200 or not isinstance(record, dict):
            raise Inconclusive(f"could not read booking {booking_id}: status {reply.status}")
        if self.marker not in (record.get("firstname"), record.get("lastname")):
            raise Inconclusive(f"booking {booking_id} no longer carries this run's marker; ids restart after a reset")
        return record

    def create(self, tag, **overrides):
        """Create a valid booking a rule needs; returns (id, stored record)."""
        reply = self.call("POST", "/booking", self.booking(tag, **overrides))
        if reply.status != 200 or not isinstance(reply.json, dict) or "bookingid" not in reply.json:
            raise Inconclusive(f"could not create the booking this rule needs: status {reply.status}")
        return reply.json["bookingid"], self.read(reply.json["bookingid"])

    def post_and_find(self, tag, **overrides):
        """POST a booking and return (sent, status, what the API kept).

        The status alone proves nothing: staging answers 418 to a POST without an Accept
        header and stores the booking anyway. So always look for the record afterwards.
        """
        sent = self.booking(tag, **overrides)
        reply = self.call("POST", "/booking", sent)
        matches = ids_in(self.call("GET", booking_path(firstname=sent["firstname"], lastname=sent["lastname"])))
        reply_id = reply.json.get("bookingid") if isinstance(reply.json, dict) else None
        booking_id = reply_id or (matches[0] if matches else None)
        return sent, reply.status, self.read(booking_id) if booking_id else None

    def must_refuse(self, tag, path, **overrides):
        """POST a bad booking and judge the rejection; `path` is the field to compare."""
        sent, status, stored = self.post_and_find(tag, **overrides)
        return evaluate_rejection(sent, status, stored, path)

    def update(self, tag, method, body):
        """Send a bad update to a fresh booking; returns (before, status, after).

        A vanished booking answers PUT and PATCH with 405, which would pass for a rejection,
        so the read afterwards is what turns a reset into INCONCLUSIVE instead of a false PASS.
        """
        booking_id, before = self.create(tag)
        status = self.call(method, f"/booking/{booking_id}", body, auth=True).status
        return before, status, self.read(booking_id)


def dig(record, path, default=None):
    """Read a dotted path such as bookingdates.checkout; `default` when the key is absent."""
    for key in path.split("."):
        if not isinstance(record, dict) or key not in record:
            return default
        record = record[key]
    return record


def show(value):
    return json.dumps(value, ensure_ascii=False)


def evaluate_rejection(sent, status, stored, path):
    """A 4xx with nothing stored passes. Anything else fails, and says how badly."""
    if 400 <= status < 500:
        if stored is None:
            return passed(f"rejected with {status}, nothing stored")
        return failed(f"answered {status} but stored the booking anyway")
    if status >= 500:
        return failed(f"server error {status}, expected a 4xx rejection")
    was, now = dig(sent, path), dig(stored, path)
    if stored is None:
        return failed(f"accepted with {status}, sent {path} {show(was)}")
    if now != was:
        return failed(f"accepted and silently rewritten: {path} sent {show(was)}, stored {show(now)}")
    return failed(f"accepted and stored as sent: {path} {show(now)}")


def evaluate_update_refused(before, status, after):
    """A bad update must be refused and leave the booking exactly as it was."""
    if status in (401, 403):
        return inconclusive(f"credentials refused ({status}), which says nothing about the rule")
    if 400 <= status < 500:
        if after == before:
            return passed(f"rejected with {status}, booking unchanged")
        return failed(f"answered {status} but changed the booking anyway")
    dates = show(dig(after, "bookingdates"))
    if after != before:
        return failed(f"accepted with {status} and stored: bookingdates {dates}")
    return failed(f"answered {status}, expected a 4xx rejection")


def evaluate_partial_patch(before, status, after, new_checkout):
    """PATCH of one date must leave the other alone."""
    if status in (401, 403):
        return inconclusive(f"credentials refused ({status}), which says nothing about the rule")
    was, now = dig(before, "bookingdates.checkin"), dig(after, "bookingdates.checkin")
    if now != was:
        return failed(f"checkin wiped by a checkout-only PATCH: was {show(was)}, now {show(now)}")
    if status < 300 and dig(after, "bookingdates.checkout") != new_checkout:
        return failed(f"answered {status} but checkout is not {show(new_checkout)}")
    return passed(f"checkin kept at {show(now)}, PATCH answered {status}")


def evaluate_round_trip(sent, status, stored):
    """The sanity check: a valid booking comes back identical."""
    if status != 200:
        return failed(f"a valid booking was refused with {status}")
    if stored != sent:
        return failed(f"stored record differs: sent {show(sent)}, stored {show(stored)}")
    return passed("stored exactly as sent, Arabic text intact")


def evaluate_decimal(sent, status, stored):
    """A valid decimal price must survive: this rule expects acceptance, not a rejection."""
    was, now = dig(sent, "totalprice"), dig(stored, "totalprice")
    if stored is None:
        return failed(f"refused with {status}; decimal prices must be storable")
    if now != was:
        return failed(f"truncated: totalprice sent {show(was)}, stored {show(now)}")
    return passed(f"totalprice stored as sent: {show(now)}")


def evaluate_statuses(expected, statuses):
    """Every labelled request must answer exactly `expected`."""
    wrong = [f"{label}: answered {status}" for label, status in statuses.items() if status != expected]
    if wrong:
        return failed("; ".join(wrong) + f"; expected {expected}")
    return passed(f"answered {expected}")


def evaluate_checkin_filter(day, exact_found, later_found):
    """Docs: checkin filter is 'greater than or equal'. The later booking is the control."""
    if exact_found:
        return passed(f"booking with checkin exactly {day} returned")
    if later_found:
        return failed(f"checkin exactly {day} not returned, the day after is: filter acts as >, docs say >=")
    return failed(f"neither checkin {day} nor the day after returned: filter is broken")


@rule("G01", "POST with checkout before checkin is rejected and nothing is stored", "Critical",
      "A guest cannot leave before arriving; BK-1043 reached reception showing -3 nights.")
def g01(run):
    """Both dates are valid on their own, so only an ordering check can refuse this."""
    return run.must_refuse("G01", "bookingdates", bookingdates=run.dates(nights=-5))


@rule("G02", "POST with checkin equal to checkout is rejected", "High",
      "A zero-night stay has no room to assign and nothing to bill, yet shows as Confirmed.")
def g02(run):
    """Same-day is a policy opinion; Nuzul may decide day-use is allowed."""
    return run.must_refuse("G02", "bookingdates", bookingdates=run.dates(nights=0))


@rule("G03", "POST with a non-ISO date is rejected, never silently reinterpreted", "Critical",
      "The voice agent wrote checkout 12/08/2026 on BK-1043; the API reads it as 8 December.")
def g03(run):
    """Checkin precedes both readings of 12/08/2026, so only a format check can refuse this."""
    dates = {"checkin": "2026-08-01", "checkout": "12/08/2026"}
    return run.must_refuse("G03", "bookingdates.checkout", bookingdates=dates)


@rule("G04", "POST with an impossible calendar date is rejected, never rolled", "Critical",
      "A date that does not exist turns into a different real date nobody agreed to.")
def g04(run):
    """The API rolls 30 February forward; the checkout stays after both readings of it."""
    dates = {"checkin": "2026-02-30", "checkout": "2026-03-05"}
    return run.must_refuse("G04", "bookingdates.checkin", bookingdates=dates)


@rule("G05", "POST with an unparseable date is rejected, never stored as 0NaN-aN-aN", "Critical",
      "Reception cannot act on 0NaN-aN-aN, and it matches every checkin search.")
def g05(run):
    """Garbage in a date field must never reach storage in any form."""
    dates = {"checkin": "not-a-date", "checkout": run.dates()["checkout"]}
    return run.must_refuse("G05", "bookingdates.checkin", bookingdates=dates)


@rule("G06", "PUT with checkout before checkin is rejected", "Critical",
      "A fix that guards only new bookings leaves every edit path open.")
def g06(run):
    """The ordering rule must hold on a full update of a good booking."""
    body = run.booking("G06", bookingdates=run.dates(nights=-5))
    return evaluate_update_refused(*run.update("G06", "PUT", body))


@rule("G07", "PATCH with checkout before checkin is rejected", "Critical",
      "PATCH is the third way in; a date change must obey the same rule as a new booking.")
def g07(run):
    """The ordering rule must hold on a partial update of a good booking."""
    body = {"bookingdates": run.dates(nights=-5)}
    return evaluate_update_refused(*run.update("G07", "PATCH", body))


@rule("G08", "PATCH with only a new checkout keeps the existing checkin", "Critical",
      "Extending a stay at reception must not destroy the arrival date of a good booking.")
def g08(run):
    """The docs mark both dates optional on PATCH, so a checkout-only change is legitimate."""
    new_checkout = run.dates(nights=8)["checkout"]
    before, status, after = run.update("G08", "PATCH", {"bookingdates": {"checkout": new_checkout}})
    return evaluate_partial_patch(before, status, after, new_checkout)


@rule("G09", "A valid booking with an Arabic name is stored exactly as sent", "Critical",
      "Sanity check and the Riyadh and Jeddah happy path: if this fails the environment is broken.")
def g09(run):
    """Lastname stays the marker so cleanup can find it; Arabic goes in firstname and needs."""
    sent, status, stored = run.post_and_find("فهد العتيبي", additionalneeds="سرير إضافي")
    return evaluate_round_trip(sent, status, stored)


@rule("G10", "totalprice as a non-numeric string is rejected, never stored as null", "High",
      "BK-1043 carried SAR 250; stored as null, nobody knows what to charge.")
def g10(run):
    """A price the API cannot read must be refused, not blanked."""
    return run.must_refuse("G10", "totalprice", totalprice="SAR 250")


@rule("G11", "Negative totalprice is rejected", "High",
      "A negative total means paying the guest to stay.")
def g11(run):
    """Zero is left to audit rule A05: free stays may be a legitimate policy."""
    return run.must_refuse("G11", "totalprice", totalprice=-100)


@rule("G12", "Decimal totalprice is preserved, not truncated", "Medium",
      "Truncating 199.99 to 199 under-bills every booking priced in halalas.")
def g12(run):
    """The docs type totalprice as Number; nothing there says whole numbers only."""
    return evaluate_decimal(*run.post_and_find("G12", totalprice=199.99))


@rule("G13", "A missing required field returns 400, not 500", "High",
      "A 500 tells the voice agent nothing it can fix and looks like an outage.")
def g13(run):
    """Each required field in turn, plus firstname as a number, which also answers 500 today."""
    cases = {f"missing {name}": {key: value for key, value in run.booking("G13").items() if key != name}
             for name in ("firstname", "totalprice", "depositpaid", "bookingdates")}
    cases["missing lastname"] = {key: value for key, value in run.booking(run.marker).items() if key != "lastname"}
    cases["missing checkin"] = run.booking("G13", bookingdates={"checkout": run.dates()["checkout"]})
    cases["firstname as a number"] = run.booking(12345)
    return evaluate_statuses(400, {label: run.call("POST", "/booking", body).status for label, body in cases.items()})


@rule("G14", "Empty firstname or lastname is rejected", "High",
      "Reception cannot greet or find a guest with no name.")
def g14(run):
    """The blank-lastname case carries the marker in firstname, so cleanup still finds it."""
    outcomes = [run.must_refuse("", "firstname"), run.must_refuse(run.marker, "lastname", lastname="")]
    message = "; ".join(outcome.message for outcome in outcomes)
    return passed(message) if all(outcome.status == PASS for outcome in outcomes) else failed(message)


@rule("G15", "depositpaid as a string is rejected, not coerced", "Medium",
      "Coercing 'yes' to true records a deposit nobody checked.")
def g15(run):
    """The docs type depositpaid as Boolean."""
    return run.must_refuse("G15", "depositpaid", depositpaid="yes")


@rule("G16", "POST /auth with a wrong password returns 401, not 200", "Medium",
      "A failed login answered with 200 looks like success to any client checking the status.")
def g16(run):
    """The password is random, so the real one never appears in a report."""
    body = {"username": run.client.username, "password": "wrong-" + secrets.token_hex(4)}
    return evaluate_statuses(401, {"wrong password": run.call("POST", "/auth", body).status})


@rule("G17", "GET /booking?checkin=D returns a booking whose checkin is exactly D", "Medium",
      "Reception searching arrivals from a date would miss everyone arriving on that date.")
def g17(run):
    """Own ids only: other people's corrupted rows match every checkin search."""
    day = run.dates(offset=90)
    exact_id, _ = run.create("G17-exact", bookingdates=day)
    later_id, _ = run.create("G17-later", bookingdates=run.dates(offset=91))
    found = ids_in(run.call("GET", booking_path(checkin=day["checkin"])))
    run.read(exact_id)
    return evaluate_checkin_filter(day["checkin"], exact_id in found, later_id in found)


@rule("G18", "A filter with a non-ISO date returns 400, not 500", "Low",
      "A client sending a local-format date gets a server error instead of a usable message.")
def g18(run):
    """No retry: the 500 is the behaviour under test, not a blip."""
    return evaluate_statuses(400, {"checkin=15/08/2026": run.call(
        "GET", booking_path(checkin="15/08/2026"), retry=False).status})


@rule("G19", "DELETE of a missing id returns 404, not 405", "Low",
      "A 405 hides the fact that the booking is already gone.")
def g19(run):
    """Deletes an id this run created twice, so no id is hard-coded and no other booking is at risk."""
    booking_id, _ = run.create("G19")
    path = f"/booking/{booking_id}"
    if run.call("DELETE", path, auth=True).status != 201:
        raise Inconclusive("could not delete this rule's own booking")
    if run.call("GET", path).status != 404:
        raise Inconclusive("the deleted id still answers, so it is not safe to delete again")
    return evaluate_statuses(404, {"DELETE of a missing id": run.call("DELETE", path, auth=True).status})


def run_rule(run, gate_rule):
    """Run one rule. Environment trouble or a crash gives INCONCLUSIVE, never a pass or a fail."""
    run.exchanges = []
    try:
        outcome = gate_rule.check(run)
    except Inconclusive as error:
        outcome = inconclusive(str(error))
    except Unreachable as error:
        outcome = inconclusive(f"no usable answer from the API: {error}")
    except Exception as error:
        outcome = inconclusive(f"rule crashed: {type(error).__name__}: {error}")
    return Result(gate_rule.rule_id, gate_rule.title, gate_rule.severity, gate_rule.why,
                  outcome.status, outcome.message, run.exchanges)


def run_gate(run, rules=None, on_result=lambda result: None):
    """Run the sanity rule first and stop there if it fails. Results come back in id order."""
    rules = sorted(RULES if rules is None else rules,
                   key=lambda item: (item.rule_id != SANITY_RULE, item.rule_id))
    results = []
    for gate_rule in rules:
        results.append(run_rule(run, gate_rule))
        on_result(results[-1])
        if gate_rule.rule_id == SANITY_RULE and results[-1].status != PASS:
            break
    return sorted(results, key=lambda result: result.rule_id)
