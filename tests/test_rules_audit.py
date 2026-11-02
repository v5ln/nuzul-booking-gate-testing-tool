"""Audit rules on the shapes staging really stores, and the scan around them."""
import unittest

from booking_gate import report
from booking_gate.client import Client
from booking_gate.rules_audit import choose_ids, run_audit, scan
from tests.fake_api import FakeStaging, no_sleep

GOOD = {"firstname": "نورة", "lastname": "Al-Qahtani", "totalprice": 250, "depositpaid": True,
        "bookingdates": {"checkin": "2026-12-01", "checkout": "2026-12-05"}}
BK_1043 = {"firstname": "فهد", "lastname": "العتيبي", "totalprice": "SAR 250", "depositpaid": True,
           "bookingdates": {"checkin": "2026-08-15", "checkout": "12/08/2026"}}


def flagged(**overrides):
    return {flag.rule_id for flag in scan(1, {**GOOD, **overrides})}


def with_dates(checkin, checkout):
    return flagged(bookingdates={"checkin": checkin, "checkout": checkout})


class Rules(unittest.TestCase):
    def test_bk_1043_as_the_console_showed_it(self):
        flags = {flag.rule_id: flag for flag in scan("BK-1043", BK_1043)}
        self.assertEqual(flags["A01"].nights, -3)
        self.assertEqual(flags["A03"].field, "bookingdates.checkout")
        self.assertEqual(flags["A04"].value, "SAR 250")

    def test_a03_flags_every_date_that_is_not_real_ccyy_mm_dd(self):
        for bad in ("0NaN-aN-aN", "12/08/2026", "", None, "2026-02-30", "2026-8-5", "20260815", "٢٠٢٦-٠٨-١٥"):
            with self.subTest(bad):
                self.assertIn("A03", with_dates(bad, "2026-12-05"))

    def test_the_rest_of_the_catalogue_and_a_good_booking_raises_nothing(self):
        """Al-Qahtani contains 'Qa': a substring match would call a real guest test data."""
        self.assertEqual(flagged(), set())
        cases = (("A01", with_dates("2026-12-05", "2026-12-01")), ("A02", with_dates("2026-12-05", "2026-12-05")),
                 ("A04", flagged(totalprice=None)), ("A04", flagged(totalprice=-100)), ("A05", flagged(totalprice=0)),
                 ("A06", flagged(firstname="")), ("A06", flagged(lastname="   ")), ("A07", flagged(firstname="Test")),
                 ("A07", flagged(lastname="QA")), ("A07", flagged(additionalneeds="qa_user")),
                 ("A07", flagged(firstname="Jim", lastname="Brown", totalprice=111)))
        for rule_id, found in cases:
            with self.subTest(rule_id, found=found):
                self.assertIn(rule_id, found)


class Scan(unittest.TestCase):
    def test_a_vanished_or_broken_booking_is_counted_and_never_fatal(self):
        staging = FakeStaging()
        staging.bookings[1] = dict(GOOD, totalprice=None)
        original = staging.__call__

        def transport(method, url, body, headers, timeout):
            return (503, "Service Unavailable") if url.endswith("/3") else original(method, url, body, headers, timeout)

        audit = run_audit(Client("http://fake", transport=transport, sleep=no_sleep), [1, 2, 3], concurrency=2)
        self.assertEqual((audit["scanned"], audit["not_found"], audit["failed"]), (1, 1, 1))
        self.assertEqual(audit["by_rule"], {"A04": 1})

    def test_limit_takes_the_newest_ids(self):
        """The oldest ids are the sandbox's clean seed rows, and tool-made records are the newest."""
        staging = FakeStaging()
        staging.bookings = {key: GOOD for key in range(1, 6)}
        self.assertEqual(choose_ids(Client("http://fake", transport=staging), limit=2), [5, 4])

    def test_other_testers_data_cannot_break_a_report(self):
        flag = scan(1, dict(GOOD, firstname="", lastname="a|b\n\x1b[31m"))[0]
        flag.value = "a|b\n\x1b[31m"
        cell = report.flag_rows([flag])[0][4]
        self.assertNotIn("\n", cell)
        self.assertNotIn("\x1b", cell)
        self.assertIn("\\|", report.md_row([cell]))
