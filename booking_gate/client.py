"""HTTP client for the booking API: Basic auth, retries, warm-up and marker cleanup."""
import base64
import http.client
import json
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

DEFAULT_URL = "https://restful-booker.herokuapp.com"
DEFAULT_USER = "admin"
DEFAULT_PASS = "password123"
TIMEOUT = 15  # seconds per request
RETRY_DELAYS = (1, 2, 4)  # three retries with backoff, GETs only
WARM_UP_PATIENCE = 60  # seconds; staging sleeps when idle


class Unreachable(Exception):
    """The API gave no usable answer: timeout, connection failure or a broken listing."""


@dataclass
class Response:
    status: int
    text: str

    @property
    def json(self):
        try:
            return json.loads(self.text)
        except ValueError:
            return None


def new_marker():
    """A unique run id. Every booking the tool creates carries it."""
    return "gate-" + secrets.token_hex(4)


def booking_path(**filters):
    """Build /booking with query filters, leaving the slash readable for the non-ISO date test."""
    return "/booking?" + urllib.parse.urlencode(filters, safe="/") if filters else "/booking"


def ids_in(reply):
    """The booking ids in a GET /booking reply. Anything but a list is an error, never 'no ids'."""
    if reply.status != 200 or not isinstance(reply.json, list):
        raise Unreachable(f"booking listing failed with status {reply.status}")
    return [row["bookingid"] for row in reply.json]


def urllib_transport(method, url, body, headers, timeout):
    """Send one request and return (status, text). 4xx and 5xx are answers, not errors."""
    request = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as reply:
            return reply.status, reply.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode("utf-8", "replace")
    except (OSError, http.client.HTTPException) as error:
        raise Unreachable(f"{method} {url}: {error}") from error


class Client:
    """Talks to one booking API. Pass a fake `transport` to run without a network."""

    def __init__(self, base_url=DEFAULT_URL, username=DEFAULT_USER, password=DEFAULT_PASS,
                 transport=urllib_transport, sleep=time.sleep):
        self.base_url = base_url.rstrip("/")
        self.username, self.password = username, password
        self.transport, self.sleep = transport, sleep
        self._basic = "Basic " + base64.b64encode(f"{username}:{password}".encode()).decode()

    def request(self, method, path, body=None, auth=False, retry=None):
        """Send a request. GETs retry on timeouts and 5xx unless retry=False."""
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if auth:
            headers["Authorization"] = self._basic
        data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
        delays = RETRY_DELAYS if (method == "GET" if retry is None else retry) else ()
        for delay in (*delays, None):
            try:
                status, text = self.transport(method, self.base_url + path, data, headers, TIMEOUT)
                if status < 500 or delay is None:
                    return Response(status, text)
            except Unreachable:
                if delay is None:
                    raise
            self.sleep(delay)

    def wait_until_up(self, patience=WARM_UP_PATIENCE):
        """Poll /ping until it answers 201. False if it never does, or says the URL is wrong."""
        waited = 0
        while waited <= patience:
            started = time.monotonic()
            try:
                status = self.request("GET", "/ping", retry=False).status
                if status == 201:
                    return True
                if status < 500:
                    return False
            except Unreachable:
                pass
            self.sleep(3)
            waited += 3 + time.monotonic() - started
        return False

    def credentials_work(self):
        """True when POST /auth issues a token for the configured credentials."""
        body = {"username": self.username, "password": self.password}
        reply = self.request("POST", "/auth", body)
        return isinstance(reply.json, dict) and "token" in reply.json

    def marked_ids(self, marker):
        """Ids carrying the marker. Rules that test a blank lastname put it in firstname instead."""
        ids = set()
        for name_field in ("lastname", "firstname"):
            ids.update(ids_in(self.request("GET", booking_path(**{name_field: marker}))))
        return ids

    def cleanup(self, marker, known_ids=()):
        """Delete this run's bookings; return (deleted, ids still carrying the marker).

        A 4xx can still store a record, so the marker search finds what known_ids missed.
        Each record is re-read first: after a reset an id may belong to someone else.
        """
        deleted = 0
        for booking_id in sorted(self.marked_ids(marker) | set(known_ids)):
            record = self.request("GET", f"/booking/{booking_id}").json
            if isinstance(record, dict) and marker in (record.get("firstname"), record.get("lastname")):
                deleted += self.request("DELETE", f"/booking/{booking_id}", auth=True).status == 201
        return deleted, sorted(self.marked_ids(marker))
