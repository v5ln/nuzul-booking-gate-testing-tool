"""The release verdict and exit codes."""
import unittest
from types import SimpleNamespace

from booking_gate.verdict import exit_code, verdict


def result(rule_id, severity, status):
    return SimpleNamespace(rule_id=rule_id, severity=severity, status=status)


SANITY = result("G09", "Critical", "PASS")


class Verdict(unittest.TestCase):
    def test_a_critical_failure_blocks_and_all_clear_passes(self):
        blocked = [SANITY, result("G01", "Critical", "FAIL"), result("G19", "Low", "FAIL")]
        self.assertEqual((verdict(blocked), exit_code(blocked)), ("BLOCK", 1))
        clear = [SANITY, result("G01", "Critical", "PASS")]
        self.assertEqual((verdict(clear), exit_code(clear)), ("PASS", 0))

    def test_lesser_failures_warn_and_fail_on_sets_the_exit_code(self):
        high, medium = result("G10", "High", "FAIL"), result("G12", "Medium", "FAIL")
        self.assertEqual(verdict([SANITY, high]), "WARN")
        for results, fail_on, expected in (([SANITY, high], "critical", 0), ([SANITY, high], "high", 1),
                                           ([SANITY, medium], "high", 0), ([SANITY, medium], "any", 1)):
            with self.subTest(fail_on=fail_on, severity=results[1].severity):
                self.assertEqual(exit_code(results, fail_on), expected)

    def test_no_proof_means_no_verdict_but_a_proven_critical_still_blocks(self):
        unproven = result("G17", "Medium", "INCONCLUSIVE")
        for results in ([], [SANITY, unproven], [result("G09", "Critical", "FAIL"), result("G01", "Critical", "FAIL")]):
            with self.subTest(results=results):
                self.assertEqual((verdict(results), exit_code(results)), ("INCONCLUSIVE", 2))
        self.assertEqual(verdict([SANITY, unproven, result("G01", "Critical", "FAIL")]), "BLOCK")
