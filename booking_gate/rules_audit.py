"""Audit rules A01-A07 and the scan over bookings that already got in.

Each rule is a pure function of one booking returning (field, value) hits, so the same rules
run on a stored record, on a raw payload and on recorded fixtures.
"""
import re
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime

from .client import Unreachable, ids_in
from .verdict import SEVERITIES, rule_decorator

RULES = []
rule = rule_decorator(RULES)
ISO_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")  # \d would also take Arabic-Indic digits
TEST_WORD = re.compile(r"(?<![^\W\d_])(test|qa)(?![^\W\d_])", re.IGNORECASE)  # never the Qa of Qahtani


@dataclass
class Flag:
    booking_id: object
    rule_id: str
    severity: str
    field: str
    value: object
    nights: object


def real_date(value):
    """The date if value is a real CCYY-MM-DD calendar date, else None."""
    if isinstance(value, str) and ISO_DATE.fullmatch(value):
        try:
            return datetime.strptime(value, "%Y-%m-%d").date()
        except ValueError:
            return None
    return None


def readable_date(value):
    """Also reads DD/MM/YYYY, as the console did: BK-1043's 12/08/2026 gave it -3 nights."""
    try:
        return real_date(value) or datetime.strptime(value, "%d/%m/%Y").date()
    except (TypeError, ValueError):
        return None


def stay_dates(booking):
    dates = booking.get("bookingdates")
    return dates if isinstance(dates, dict) else {}


def stay_nights(booking):
    """Checkout minus checkin in days, or None when either date cannot be read."""
    dates = stay_dates(booking)
    checkin, checkout = readable_date(dates.get("checkin")), readable_date(dates.get("checkout"))
    return (checkout - checkin).days if checkin and checkout else None


def is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def date_pair(booking):
    dates = stay_dates(booking)
    return f"{dates.get('checkin')} -> {dates.get('checkout')}"


@rule("A01", "checkout before checkin", "Critical",
      "The guest leaves before arriving; reception sees negative nights, as on BK-1043.")
def a01(booking):
    """Nights below zero, reading DD/MM/YYYY as the console does."""
    nights = stay_nights(booking)
    return [("bookingdates", date_pair(booking))] if nights is not None and nights < 0 else []


@rule("A02", "checkout equals checkin", "High",
      "Zero nights: no room to assign and nothing to bill.")
def a02(booking):
    """Same-day stays. Policy may allow them, but the gate's G02 does not today."""
    return [("bookingdates", date_pair(booking))] if stay_nights(booking) == 0 else []


@rule("A03", "a date that is not a real CCYY-MM-DD calendar date", "Critical",
      "Covers 0NaN-aN-aN, 12/08/2026 and empty: the arrival or departure cannot be trusted.")
def a03(booking):
    """Checks each date on its own, so a booking with two bad dates raises two flags."""
    dates = stay_dates(booking)
    return [(f"bookingdates.{name}", dates.get(name)) for name in ("checkin", "checkout")
            if real_date(dates.get(name)) is None]


@rule("A04", "totalprice null, non-numeric, or negative", "High",
      "No usable price: nothing can be billed, or the amount is plainly wrong.")
def a04(booking):
    """The API turns an unreadable price into null, so null is what the audit will see."""
    price = booking.get("totalprice")
    return [("totalprice", price)] if not is_number(price) or price < 0 else []


@rule("A05", "totalprice zero", "Medium",
      "A free stay may be legitimate, but each one needs a human look.")
def a05(booking):
    """Zero is flagged here and not gated, because it is a policy decision."""
    price = booking.get("totalprice")
    return [("totalprice", price)] if is_number(price) and price == 0 else []


@rule("A06", "empty or whitespace-only firstname or lastname", "High",
      "Reception has nobody to look for at the front desk.")
def a06(booking):
    """A missing name counts as empty."""
    return [(name, booking.get(name)) for name in ("firstname", "lastname")
            if not str(booking.get(name) or "").strip()]


@rule("A07", "names or values that look like test data", "Info",
      "Test records mixed with real bookings inflate counts and confuse staff.")
def a07(booking):
    """Whole words only, so Al-Qahtani is safe; plus the apidoc example Jim Brown 111."""
    hits = [(name, booking[name]) for name in ("firstname", "lastname", "additionalneeds")
            if isinstance(booking.get(name), str) and TEST_WORD.search(booking[name])]
    if (booking.get("firstname"), booking.get("lastname"), booking.get("totalprice")) == ("Jim", "Brown", 111):
        hits.append(("firstname", "Jim Brown 111"))
    return hits


def scan(booking_id, booking):
    """Every flag one booking raises."""
    nights = stay_nights(booking)
    return [Flag(booking_id, item.rule_id, item.severity, name, value, nights)
            for item in RULES for name, value in item.check(booking)]


def choose_ids(client, ids=None, limit=None):
    """The ids to scan: those asked for, else every id, newest first.

    The oldest ids are the sandbox's clean seed rows, so a quick look starts at the new end.
    """
    chosen = ids or sorted(ids_in(client.request("GET", "/booking")), reverse=True)
    return chosen if limit is None else chosen[:limit]


def fetch(client, booking_id):
    """Fetch one booking; returns (id, booking or None, 'ok', 'missing' or 'failed')."""
    try:
        reply = client.request("GET", f"/booking/{booking_id}")
    except Unreachable:
        return booking_id, None, "failed"
    if reply.status == 404:
        return booking_id, None, "missing"
    good = reply.status == 200 and isinstance(reply.json, dict)
    return booking_id, reply.json if good else None, "ok" if good else "failed"


def run_audit(client, ids, concurrency=8):
    """Fetch and scan the ids with a bounded pool; a vanished booking is noted, never fatal."""
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        fetched = list(pool.map(lambda booking_id: fetch(client, booking_id), ids))
    flags = [flag for booking_id, booking, state in fetched if state == "ok" for flag in scan(booking_id, booking)]
    flags.sort(key=lambda flag: (SEVERITIES.index(flag.severity), flag.rule_id, str(flag.booking_id)))
    states = Counter(state for _, _, state in fetched)
    return {"requested": len(ids), "scanned": states["ok"], "not_found": states["missing"],
            "failed": states["failed"], "flagged": len({flag.booking_id for flag in flags}), "flags": flags,
            "by_rule": dict(sorted(Counter(flag.rule_id for flag in flags).items())),
            "by_severity": {name: count for name in SEVERITIES
                            if (count := sum(flag.severity == name for flag in flags))}}
