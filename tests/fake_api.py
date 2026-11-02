"""Offline stand-ins for the booking API. Both are transports for Client."""
import base64
import json
import re
import urllib.parse
from datetime import datetime

BASIC = "Basic " + base64.b64encode(b"admin:password123").decode()
REWRITES = {"12/08/2026": "2026-12-08", "2026-02-30": "2026-03-02", "not-a-date": "0NaN-aN-aN"}  # seen on staging
REQUIRED = ("firstname", "lastname", "totalprice", "depositpaid", "bookingdates")


def no_sleep(seconds):
    pass


def iso_date(value):
    if isinstance(value, str) and re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        try:
            return datetime.strptime(value, "%Y-%m-%d").date()
        except ValueError:
            return None
    return None


class Replay:
    """Answers one rule's requests from a recorded run, and insists they arrive in that order."""

    def __init__(self, exchanges):
        self.queue = list(exchanges)

    def __call__(self, method, url, body, headers, timeout):
        expected = self.queue.pop(0)
        sent = (method, url.partition("://")[2].partition("/")[2])
        if sent != (expected["method"], expected["path"].lstrip("/")):
            raise AssertionError(f"replay out of order: {sent} instead of {expected['path']}")
        return expected["status"], expected["response"]


class FakeStaging:
    """An in-memory booking API.

    By default it repeats the behaviour recorded from staging on 2 November 2026. With
    fixed=True it does what the docs and NZL-217 ask, which proves the gate can pass at all.
    """

    def __init__(self, fixed=False):
        self.fixed = fixed
        self.bookings = {}
        self.next_id = 1
        self.before_call = lambda method, path: None

    def __call__(self, method, url, body, headers, timeout):
        parts = urllib.parse.urlsplit(url)
        self.before_call(method, parts.path)
        data = json.loads(body) if body else None
        if parts.path == "/ping":
            return 201, "Created"
        if parts.path == "/auth":
            return self.auth(data)
        if parts.path == "/booking":
            if method == "POST":
                return self.create(data)
            return self.search(dict(urllib.parse.parse_qsl(parts.query, keep_blank_values=True)))
        booking_id = int(parts.path.rsplit("/", 1)[1])
        if method == "GET":
            found = booking_id in self.bookings
            return (200, json.dumps(self.bookings[booking_id])) if found else (404, "Not Found")
        if headers.get("Authorization") != BASIC:
            return 403, "Forbidden"
        if booking_id not in self.bookings:
            return (404, "Not Found") if self.fixed and method == "DELETE" else (405, "Method Not Allowed")
        if method == "DELETE":
            del self.bookings[booking_id]
            return 201, "Created"
        return self.update(booking_id, method, data)

    def auth(self, data):
        if data.get("password") == "password123":
            return 200, '{"token":"recorded"}'
        return 401 if self.fixed else 200, '{"reason":"Bad credentials"}'

    def invalid(self, data):
        """True when a correct API must refuse the body."""
        names = (data.get("firstname"), data.get("lastname"))
        dates = data.get("bookingdates") or {}
        checkin, checkout = iso_date(dates.get("checkin")), iso_date(dates.get("checkout"))
        price = data.get("totalprice")
        return (not all(isinstance(name, str) and name.strip() for name in names)
                or not isinstance(data.get("depositpaid"), bool)
                or not isinstance(price, (int, float)) or price < 0
                or not (checkin and checkout and checkin < checkout))

    def kept(self, data):
        """What staging stores for a body: dates rewritten, price truncated, deposit coerced."""
        price = data["totalprice"]
        dates = {key: REWRITES.get(value, value) for key, value in data["bookingdates"].items()}
        return {**data, "bookingdates": dates, "depositpaid": bool(data["depositpaid"]),
                "totalprice": None if isinstance(price, str) else int(price)}

    def refusal(self, data):
        """The error answer for a body, or None when it gets through."""
        if self.fixed:
            return (400, "Bad Request") if self.invalid(data) else None
        broken = (any(key not in data for key in REQUIRED) or not isinstance(data["firstname"], str)
                  or "checkin" not in data["bookingdates"])
        return (500, "Internal Server Error") if broken else None

    def create(self, data):
        refused = self.refusal(data)
        if refused:
            return refused
        booking_id, self.next_id = self.next_id, self.next_id + 1
        self.bookings[booking_id] = data if self.fixed else self.kept(data)
        return 200, json.dumps({"bookingid": booking_id, "booking": self.bookings[booking_id]})

    def update(self, booking_id, method, data):
        if method == "PATCH":
            current = self.bookings[booking_id]
            base = current["bookingdates"] if self.fixed else {"checkin": "0NaN-aN-aN", "checkout": "0NaN-aN-aN"}
            dates = {**base, **data["bookingdates"]} if "bookingdates" in data else current["bookingdates"]
            data = {**current, **data, "bookingdates": dates}
        refused = self.refusal(data)
        if refused:
            return refused
        self.bookings[booking_id] = data if self.fixed else self.kept(data)
        return 200, json.dumps(self.bookings[booking_id])

    def search(self, query):
        checkin = query.get("checkin")
        if checkin is not None and not iso_date(checkin):
            return (400, "Bad Request") if self.fixed else (500, "Internal Server Error")

        def matches(booking):
            names_match = all(booking[key] == query[key] for key in ("firstname", "lastname") if key in query)
            if checkin is None:
                return names_match
            stored = booking["bookingdates"]["checkin"]
            return names_match and (stored >= checkin if self.fixed else stored > checkin)

        rows = [{"bookingid": key} for key, booking in self.bookings.items() if matches(booking)]
        return 200, json.dumps(rows)
