#!/usr/bin/env python3
"""Release gate and data audit for the Nuzul booking API."""
import argparse
import os
import sys
from datetime import datetime, timezone

from booking_gate import client as api
from booking_gate import report
from booking_gate.rules_gate import RULES as GATE_RULES
from booking_gate.rules_gate import Run, run_gate
from booking_gate.verdict import exit_code, verdict

INCONCLUSIVE_EXIT = 2
ROW = "{:<4}  {:<8}  {:<12}  {}"


def say(message):
    """Progress goes to stderr, so stdout stays clean for --json."""
    print(message, file=sys.stderr, flush=True)


def connect(args, needs_login=True):
    """Build the client and wake staging. None if it cannot be reached or refuses the login."""
    client = api.Client(args.base_url, args.username, args.password)
    say(f"Waking {client.base_url} (up to {api.WARM_UP_PATIENCE}s)...")
    if not client.wait_until_up():
        say(f"INCONCLUSIVE: {client.base_url} did not answer GET /ping with 201.")
        return None
    try:
        if needs_login and not client.credentials_work():
            say("INCONCLUSIVE: the API refused the configured credentials.")
            return None
    except api.Unreachable as error:
        say(f"INCONCLUSIVE: {error}")
        return None
    return client


def tidy_up(client, marker, known_ids=()):
    """Delete this run's bookings. Never raises: it runs in a finally block."""
    try:
        deleted, left = client.cleanup(marker, known_ids)
    except api.Unreachable as error:
        return f"INCOMPLETE, bookings with marker {marker} may remain: {error}"
    return f"deleted {deleted}, left {len(left)}" + (f" ({left})" if left else "")


def cmd_gate(args):
    client = connect(args)
    if client is None:
        return INCONCLUSIVE_EXIT
    run = Run(client, api.new_marker())
    results = []
    print(f"Release gate against {client.base_url}, run {run.marker}. G09 first: it proves the environment.\n")
    print(ROW.format("Id", "Severity", "Result", "What happened"))
    try:
        results = run_gate(run, on_result=lambda result: print(
            ROW.format(result.rule_id, result.severity, result.status, result.message), flush=True))
    finally:
        cleanup = tidy_up(client, run.marker, run.created)
        print(f"\nCleanup: {cleanup}")
    code = exit_code(results, args.fail_on)
    info = {"verdict": verdict(results), "exit_code": code, "fail_on": args.fail_on, "base_url": client.base_url,
            "marker": run.marker, "cleanup": cleanup,
            "finished": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")}
    paths = report.save_gate(info, results)
    failures = [result.rule_id for result in results if result.status != "PASS"]
    print(f"Verdict: {info['verdict']}, exit code {code}. Not passing: {', '.join(failures) or 'none'}")
    print(f"Report: {paths[0].relative_to(report.REPORTS.parent)} and .json")
    return code


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=os.environ.get("BOOKER_URL", api.DEFAULT_URL))
    parser.add_argument("--username", default=os.environ.get("BOOKER_USER", api.DEFAULT_USER))
    parser.add_argument("--password", default=os.environ.get("BOOKER_PASS", api.DEFAULT_PASS))
    commands = parser.add_subparsers(dest="command", required=True)
    gate = commands.add_parser("gate", help="prove whether a release enforces the booking rules")
    gate.add_argument("--fail-on", choices=("critical", "high", "any"), default="critical",
                      help="lowest severity that makes the exit code 1")
    gate.set_defaults(run=cmd_gate)
    args = parser.parse_args()
    return args.run(args)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    sys.exit(main())
