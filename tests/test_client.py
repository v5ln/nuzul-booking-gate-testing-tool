"""Client behaviour that protects other people's data and survives a flaky sandbox."""
import unittest

from booking_gate.client import Client, Unreachable
from tests.fake_api import FakeStaging, no_sleep

MARKER = "gate-00000000"
BOOKING = {"totalprice": 1, "depositpaid": True, "bookingdates": {"checkin": "2031-01-01", "checkout": "2031-01-02"}}


def client_for(transport):
    return Client("http://fake", transport=transport, sleep=no_sleep)


class Scripted:
    """Answers from a list; an exception in the list is raised."""

    def __init__(self, *answers):
        self.answers, self.calls = list(answers), 0

    def __call__(self, method, url, body, headers, timeout):
        self.calls += 1
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


class Cleanup(unittest.TestCase):
    def test_cleanup_deletes_exactly_this_runs_bookings(self):
        """Ids restart after a reset, and a booking stored behind a 4xx never yields an id."""
        staging = FakeStaging()
        staging.bookings[3] = {**BOOKING, "firstname": "Untracked", "lastname": MARKER}
        staging.bookings[4] = {**BOOKING, "firstname": MARKER, "lastname": ""}
        staging.bookings[5] = {**BOOKING, "firstname": "Someone", "lastname": "Else"}
        staging.bookings[7] = {**BOOKING, "firstname": "Recycled", "lastname": "Id"}
        deleted, left = client_for(staging).cleanup(MARKER, known_ids=[7])
        self.assertEqual((deleted, left), (2, []))
        self.assertEqual(sorted(staging.bookings), [5, 7])


class Retries(unittest.TestCase):
    def test_gets_retry_with_backoff_and_a_post_never_does(self):
        """A retried POST could create a second booking."""
        waits = []
        script = Scripted(Unreachable("timeout"), (503, ""), (503, ""), (200, "[]"))
        client = Client("http://fake", transport=script, sleep=waits.append)
        self.assertEqual(client.request("GET", "/booking").status, 200)
        self.assertEqual((script.calls, waits), (4, [1, 2, 4]))
        script = Scripted((503, ""), (200, ""))
        self.assertEqual(client_for(script).request("POST", "/booking", {}).status, 503)
        self.assertEqual(script.calls, 1)

    def test_warm_up_waits_for_a_sleeping_api(self):
        script = Scripted(Unreachable("still asleep"), (503, ""), (201, "Created"))
        self.assertTrue(client_for(script).wait_until_up())
        self.assertEqual(script.calls, 3)
