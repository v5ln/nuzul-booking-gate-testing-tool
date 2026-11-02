"""Release-gate rules: each one sends an input and proves what the API did with it.

A rule is one function returning an Outcome. It reports through Run, which records every
request and response as evidence. The evaluate_* functions are pure, so the unit tests can
replay recorded responses through the same logic the live run uses.
"""
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from .client import Unreachable, booking_path, ids_in
from .verdict import INCONCLUSIVE, PASS, SANITY_RULE, Inconclusive, Outcome, failed, passed

RULES = []


@dataclass(frozen=True)
class Rule:
    rule_id: str
    title: str
    severity: str
    why: str
    check: object


@dataclass
class Result:
    rule_id: str
    title: str
    severity: str
    why: str
    status: str
    message: str
    exchanges: list = field(default_factory=list)


def rule(rule_id, title, severity, why):
    """Register a function as a gate rule."""
    def register(check):
        RULES.append(Rule(rule_id, title, severity, why, check))
        return check
    return register


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
            raise Inconclusive(f"booking {booking_id} no longer carries this run's marker")
        return record

    def create(self, tag, **overrides):
        """Create a valid booking a rule needs; returns (id, stored record)."""
        reply = self.call("POST", "/booking", self.booking(tag, **overrides))
        if reply.status != 200 or not isinstance(reply.json, dict) or "bookingid" not in reply.json:
            raise Inconclusive(f"could not create the booking this rule needs: status {reply.status}")
        return reply.json["bookingid"], self.read(reply.json["bookingid"])

    def post_bad(self, tag, **overrides):
        """POST a booking that must be refused; return (sent, status, what the API kept).

        The status alone proves nothing: staging answers 418 to a POST without an Accept
        header and stores the booking anyway. So always look for the record afterwards.
        """
        sent = self.booking(tag, **overrides)
        reply = self.call("POST", "/booking", sent)
        matches = ids_in(self.call("GET", booking_path(firstname=tag, lastname=self.marker)))
        reply_id = reply.json.get("bookingid") if isinstance(reply.json, dict) else None
        booking_id = reply_id or (matches[0] if matches else None)
        return sent, reply.status, self.read(booking_id) if booking_id else None


def dig(record, path):
    """Read a dotted path such as bookingdates.checkout; None when absent."""
    for key in path.split("."):
        record = record.get(key) if isinstance(record, dict) else None
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


def evaluate_partial_patch(before, status, after, new_checkout):
    """PATCH of one date must leave the other alone."""
    if status in (401, 403):
        raise Inconclusive(f"credentials refused ({status}), so this says nothing about the rule")
    was, now = dig(before, "bookingdates.checkin"), dig(after, "bookingdates.checkin")
    if now != was:
        return failed(f"checkin wiped by a checkout-only PATCH: was {show(was)}, now {show(now)}")
    if status < 300 and dig(after, "bookingdates.checkout") != new_checkout:
        return failed(f"answered {status} but checkout is not {show(new_checkout)}")
    return passed(f"checkin kept at {show(now)}, PATCH answered {status}")


def evaluate_round_trip(sent, status, stored):
    """The sanity check: a valid booking comes back byte for byte."""
    if status != 200:
        return failed(f"a valid booking was refused with {status}")
    if stored != sent:
        return failed(f"stored record differs: sent {show(sent)}, stored {show(stored)}")
    return passed("stored exactly as sent, Arabic text intact")


@rule("G01", "POST with checkout before checkin is rejected and nothing is stored", "Critical",
      "A guest cannot leave before arriving; BK-1043 reached reception showing -3 nights.")
def g01(run):
    """The dates are valid on their own, so only an ordering check can refuse this."""
    sent, status, stored = run.post_bad("G01", bookingdates=run.dates(nights=-5))
    return evaluate_rejection(sent, status, stored, "bookingdates")


@rule("G03", "POST with a non-ISO date is rejected, never silently reinterpreted", "Critical",
      "The voice agent wrote checkout 12/08/2026 on BK-1043; the API quietly reads it as 8 December.")
def g03(run):
    """Checkin precedes both readings of 12/08/2026, so only a format check can refuse this."""
    dates = {"checkin": "2026-08-01", "checkout": "12/08/2026"}
    sent, status, stored = run.post_bad("G03", bookingdates=dates)
    return evaluate_rejection(sent, status, stored, "bookingdates.checkout")


@rule("G08", "PATCH with only a new checkout keeps the existing checkin", "Critical",
      "Extending a stay at reception must not destroy the arrival date of a good booking.")
def g08(run):
    """The docs mark both dates optional on PATCH, so a checkout-only change is legitimate."""
    booking_id, before = run.create("G08")
    new_checkout = run.dates(nights=8)["checkout"]
    body = {"bookingdates": {"checkout": new_checkout}}
    status = run.call("PATCH", f"/booking/{booking_id}", body, auth=True).status
    return evaluate_partial_patch(before, status, run.read(booking_id), new_checkout)


@rule("G09", "A valid booking with an Arabic name is stored exactly as sent", "Critical",
      "Sanity check and the Riyadh and Jeddah happy path: if this fails the environment is broken.")
def g09(run):
    """Lastname stays the marker so cleanup can find the record; Arabic goes in firstname and needs."""
    sent = run.booking("فهد العتيبي", additionalneeds="سرير إضافي")
    reply = run.call("POST", "/booking", sent)
    booking_id = reply.json.get("bookingid") if isinstance(reply.json, dict) else None
    return evaluate_round_trip(sent, reply.status, run.read(booking_id) if booking_id else None)


def run_rule(run, gate_rule):
    """Run one rule. Environment trouble or a crash gives INCONCLUSIVE, never a pass or a fail."""
    run.exchanges = []
    try:
        outcome = gate_rule.check(run)
    except Inconclusive as error:
        outcome = Outcome(INCONCLUSIVE, str(error))
    except Unreachable as error:
        outcome = Outcome(INCONCLUSIVE, f"no usable answer from the API: {error}")
    except Exception as error:
        outcome = Outcome(INCONCLUSIVE, f"rule crashed: {type(error).__name__}: {error}")
    return Result(gate_rule.rule_id, gate_rule.title, gate_rule.severity, gate_rule.why,
                  outcome.status, outcome.message, run.exchanges)


def run_gate(run, rules=None):
    """Run the sanity rule first; stop there if it fails. Results come back in id order."""
    rules = sorted(RULES if rules is None else rules,
                   key=lambda item: (item.rule_id != SANITY_RULE, item.rule_id))
    results = []
    for gate_rule in rules:
        results.append(run_rule(run, gate_rule))
        if gate_rule.rule_id == SANITY_RULE and results[-1].status != PASS:
            break
    return sorted(results, key=lambda result: result.rule_id)
