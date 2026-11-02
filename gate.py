#!/usr/bin/env python3
"""Release gate and data audit for the Nuzul booking API."""
import argparse
import os
import sys

from booking_gate import client as api
from booking_gate.rules_gate import Run, run_gate
from booking_gate.verdict import exit_code, verdict

INCONCLUSIVE_EXIT = 2


def connect(args):
    """Build the client and wake staging. None if the API cannot be reached."""
    client = api.Client(args.base_url, args.username, args.password)
    print(f"Waking {client.base_url} (up to {api.WARM_UP_PATIENCE}s)...")
    if client.wait_until_up():
        return client
    print(f"INCONCLUSIVE: {client.base_url} did not answer GET /ping with 201.")
    return None


def cmd_gate(args):
    client = connect(args)
    if client is None:
        return INCONCLUSIVE_EXIT
    run = Run(client, api.new_marker())
    results = []
    try:
        results = run_gate(run)
    finally:
        deleted, left = client.cleanup(run.marker, run.created)
        print(f"Cleanup: deleted {deleted}, left {len(left)} with marker {run.marker}")
    for result in results:
        print(f"{result.rule_id}  {result.severity:<8}  {result.status:<12}  {result.message}")
    print(f"Verdict: {verdict(results)}")
    return exit_code(results, args.fail_on)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=os.environ.get("BOOKER_URL", api.DEFAULT_URL))
    parser.add_argument("--username", default=os.environ.get("BOOKER_USER", api.DEFAULT_USER))
    parser.add_argument("--password", default=os.environ.get("BOOKER_PASS", api.DEFAULT_PASS))
    commands = parser.add_subparsers(dest="command", required=True)
    gate = commands.add_parser("gate", help="prove whether a release enforces the booking rules")
    gate.add_argument("--fail-on", choices=("critical", "high", "any"), default="critical")
    gate.set_defaults(run=cmd_gate)
    args = parser.parse_args()
    return args.run(args)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
