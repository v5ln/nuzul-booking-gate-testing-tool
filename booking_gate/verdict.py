"""Rule catalogue entries, rule outcomes and the release verdict."""
from dataclasses import dataclass

PASS, FAIL, INCONCLUSIVE = "PASS", "FAIL", "INCONCLUSIVE"
SEVERITIES = ("Critical", "High", "Medium", "Low", "Info")
SANITY_RULE = "G09"
FAIL_ON = {
    "critical": ("Critical",),
    "high": ("Critical", "High"),
    "any": ("Critical", "High", "Medium", "Low"),
}


class Inconclusive(Exception):
    """Raised inside a rule when the environment, not the product, stopped the check."""


@dataclass(frozen=True)
class Rule:
    rule_id: str
    title: str
    severity: str
    why: str
    check: object


def rule_decorator(catalogue):
    """Build a @rule(...) decorator that adds functions to `catalogue`."""
    def rule(rule_id, title, severity, why):
        def register(check):
            catalogue.append(Rule(rule_id, title, severity, why, check))
            return check
        return register
    return rule


@dataclass
class Outcome:
    """What a gate rule returns: a result and one line a developer can read."""
    status: str
    message: str


def passed(message):
    return Outcome(PASS, message)


def failed(message):
    return Outcome(FAIL, message)


def inconclusive(message):
    return Outcome(INCONCLUSIVE, message)


def verdict(results):
    """BLOCK on a proven Critical failure. Otherwise an unproven rule means no verdict at all.

    Results need .rule_id, .severity and .status. A broken sanity rule outranks everything:
    with no working environment the other results prove nothing.
    """
    statuses = {result.rule_id: result.status for result in results}
    if statuses.get(SANITY_RULE) != PASS:
        return "INCONCLUSIVE"
    if any(result.status == FAIL and result.severity == "Critical" for result in results):
        return "BLOCK"
    if INCONCLUSIVE in statuses.values():
        return "INCONCLUSIVE"
    return "WARN" if FAIL in statuses.values() else "PASS"


def exit_code(results, fail_on="critical"):
    """0 clean, 1 a failure at or above --fail-on, 2 inconclusive."""
    if verdict(results) == "INCONCLUSIVE":
        return 2
    return int(any(result.status == FAIL and result.severity in FAIL_ON[fail_on] for result in results))
