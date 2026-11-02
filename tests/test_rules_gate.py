"""Gate rules against recorded responses and a fake API: the verdicts are owned, not assumed."""
import argparse
import contextlib
import functools
import io
import json
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

import gate
from booking_gate import report
from booking_gate.client import Client
from booking_gate.rules_gate import RULES, Run, evaluate_rejection, run_gate, run_rule
from booking_gate.verdict import INCONCLUSIVE, PASS, Rule, verdict
from tests.fake_api import FakeStaging, Replay, no_sleep

RECORDED = json.loads((Path(__file__).parent / "fixtures" / "recorded_gate_run.json").read_text(encoding="utf-8"))
MARKER = "gate-00000000"


def staging_run(staging):
    return Run(Client("http://fake", transport=staging, sleep=no_sleep), MARKER)


def only(rule_id):
    return next(item for item in RULES if item.rule_id == rule_id)


class RecordedResponses(unittest.TestCase):
    def test_every_rule_reaches_the_recorded_result_from_the_recorded_responses(self):
        """tests/fixtures/recorded_gate_run.json is a real `gate` report, copied unedited."""
        sanity = next(entry for entry in RECORDED["results"] if entry["rule_id"] == "G09")
        first_night = date.fromisoformat(sanity["exchanges"][0]["body"]["bookingdates"]["checkin"])
        self.assertEqual(len(RECORDED["results"]), 19)
        for entry in RECORDED["results"]:
            with self.subTest(entry["rule_id"]):
                client = Client("http://fake", transport=Replay(entry["exchanges"]), sleep=no_sleep)
                run = Run(client, RECORDED["marker"])
                run.first_night = first_night
                result = run_rule(run, only(entry["rule_id"]))
                self.assertEqual((result.status, result.message), (entry["status"], entry["message"]))
        passing = [entry["rule_id"] for entry in RECORDED["results"] if entry["status"] == PASS]
        self.assertEqual(passing, ["G09"])


class Rejection(unittest.TestCase):
    SENT = {"bookingdates": {"checkin": "2026-08-01", "checkout": "12/08/2026"}}
    PATH = "bookingdates.checkout"

    def test_g03_reports_accepted_and_silently_rewritten(self):
        stored = {"bookingdates": {"checkin": "2026-08-01", "checkout": "2026-12-08"}}
        outcome = evaluate_rejection(self.SENT, 200, stored, self.PATH)
        self.assertEqual(outcome.status, "FAIL")
        self.assertIn("accepted and silently rewritten", outcome.message)
        self.assertIn("2026-12-08", outcome.message)

    def test_a_4xx_passes_only_if_nothing_was_stored(self):
        """Staging really does this: a POST with no Accept header answers 418 and stores it."""
        self.assertEqual(evaluate_rejection(self.SENT, 400, None, self.PATH).status, PASS)
        outcome = evaluate_rejection(self.SENT, 418, self.SENT, self.PATH)
        self.assertEqual(outcome.status, "FAIL")
        self.assertIn("stored the booking anyway", outcome.message)


class WholeGate(unittest.TestCase):
    def test_staging_behaviour_blocks_and_the_report_holds_the_evidence(self):
        results = run_gate(staging_run(FakeStaging()))
        self.assertEqual(verdict(results), "BLOCK")
        self.assertEqual([result.rule_id for result in results if result.status == PASS], ["G09"])
        info = {"verdict": "BLOCK", "exit_code": 1, "base_url": "http://fake", "finished": "now",
                "marker": MARKER, "cleanup": "deleted 0, left 0"}
        markdown = report.gate_markdown(info, results)
        for evidence in ("`POST /booking`", "Response `200`", '"checkout": "12/08/2026"'):
            self.assertIn(evidence, markdown)
        for secret in ("password123", "Basic "):
            self.assertNotIn(secret, markdown)

    def test_a_fixed_api_passes_every_rule(self):
        """Without this a gate that can only ever fail would look like a working gate."""
        results = run_gate(staging_run(FakeStaging(fixed=True)))
        self.assertEqual({result.rule_id: result.message for result in results if result.status != PASS}, {})
        self.assertEqual(verdict(results), "PASS")


class EnvironmentTrouble(unittest.TestCase):
    def test_trouble_is_inconclusive_never_a_false_pass(self):
        """A vanished booking answers PUT with 405 and bad credentials 403: both look like rejections.
        A failed search must not read as 'nothing stored', and a recycled id is not our booking.
        """
        reset = FakeStaging(fixed=True)
        reset.before_call = lambda method, path: reset.bookings.clear() if method == "PUT" else None
        wrong_login = Client("http://fake", password="wrong", transport=FakeStaging(fixed=True), sleep=no_sleep)
        crash = Rule("G99", "crash", "Critical", "why", lambda run: 1 / 0)
        recycled = FakeStaging(fixed=True)
        recycled.before_call = lambda method, path: recycled.bookings.update(
            {key: {**value, "firstname": "Someone", "lastname": "Else"} for key, value in recycled.bookings.items()}
        ) if method == "PUT" else None
        no_listing = FakeStaging(fixed=True)
        no_listing.search = lambda query: (500, "Internal Server Error")
        for run, gate_rule, expected in ((staging_run(reset), only("G06"), "vanished mid-run"),
                                         (Run(wrong_login, MARKER), only("G07"), "credentials refused"),
                                         (staging_run(recycled), only("G06"), "no longer carries"),
                                         (staging_run(no_listing), only("G01"), "no usable answer"),
                                         (staging_run(FakeStaging()), crash, "ZeroDivisionError")):
            with self.subTest(expected):
                result = run_rule(run, gate_rule)
                self.assertEqual(result.status, INCONCLUSIVE)
                self.assertIn(expected, result.message)

    def test_a_failed_sanity_rule_stops_the_run(self):
        staging = FakeStaging()
        staging.create = lambda data: (503, "Service Unavailable")
        results = run_gate(staging_run(staging))
        self.assertEqual([result.rule_id for result in results], ["G09"])
        self.assertEqual(verdict(results), "INCONCLUSIVE")

    def test_cleanup_runs_when_the_run_is_interrupted(self):
        staging = FakeStaging()

        def interrupted(run, on_result):
            run.create("G01")
            self.assertEqual(len(staging.bookings), 1)
            raise KeyboardInterrupt

        args = argparse.Namespace(base_url="http://fake", username="admin", password="password123", fail_on="critical")
        client = functools.partial(Client, transport=staging, sleep=no_sleep)
        with mock.patch("booking_gate.client.Client", client), mock.patch("gate.run_gate", interrupted), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(KeyboardInterrupt):
                gate.cmd_gate(args)
        self.assertEqual(staging.bookings, {})
