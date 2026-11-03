#!/usr/bin/env python3
"""Release gate and data audit for the Nuzul booking API."""
import argparse
import json
import os
import sys
import textwrap
from datetime import datetime, timezone

from booking_gate import client as api
from booking_gate import report
from booking_gate.rules_audit import RULES as AUDIT_RULES
from booking_gate.rules_audit import choose_ids, run_audit, scan, stay_nights
from booking_gate.rules_gate import RULES as GATE_RULES
from booking_gate.rules_gate import Run, dig, run_gate, show
from booking_gate.verdict import exit_code, verdict

INCONCLUSIVE_EXIT = 2
ABSENT = object()
ROW = "{:<4}  {:<8}  {:<12}  {}"
BK_1043 = {"totalprice": "SAR 250", "depositpaid": True,
           "bookingdates": {"checkin": "2026-08-15", "checkout": "12/08/2026"}}


def say(message):
    """Progress goes to stderr, so stdout stays clean for --json."""
    print(message, file=sys.stderr, flush=True)


def utc_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


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


def cmd_rules(args):
    for heading, rules in (("Gate rules (python3 gate.py gate)", GATE_RULES),
                           ("Audit rules (python3 gate.py audit)", AUDIT_RULES)):
        print(heading)
        for item in sorted(rules, key=lambda entry: entry.rule_id):
            print(f"  {item.rule_id}  {item.severity:<8}  {item.title}")
            print(f"       Why: {item.why}")
        print()
    return 0


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
            "marker": run.marker, "cleanup": cleanup, "finished": utc_now()}
    paths = report.save_gate(info, results)
    failures = [result.rule_id for result in results if result.status != "PASS"]
    print(f"Verdict: {info['verdict']}, exit code {code}. Not passing: {', '.join(failures) or 'none'}")
    print(f"Report: {paths[0].relative_to(report.REPORTS.parent)} and .json")
    return code


def cmd_audit(args):
    client = connect(args, needs_login=False)
    if client is None:
        return INCONCLUSIVE_EXIT
    try:
        ids = choose_ids(client, args.ids, args.limit)
    except api.Unreachable as error:
        say(f"INCONCLUSIVE: {error}")
        return INCONCLUSIVE_EXIT
    say(f"Scanning {len(ids)} bookings with {args.concurrency} workers...")
    audit = run_audit(client, ids, args.concurrency)
    info = {"base_url": client.base_url, "finished": utc_now()}
    paths = report.save_audit(info, audit)
    if args.json:
        print(json.dumps(report.audit_data(info, audit), ensure_ascii=False, indent=2))
    else:
        print("\n".join(report.audit_summary(audit)))
        if audit["flags"]:
            print("\n" + report.table(report.FLAG_HEADERS, report.flag_rows(audit["flags"])))
        print(f"\nReport: {paths[0].relative_to(report.REPORTS.parent)} and .json")
    if ids and not audit["scanned"]:
        say("INCONCLUSIVE: no booking could be read.")
        return INCONCLUSIVE_EXIT
    return int("Critical" in audit["by_severity"])


def field_row(name, sent, stored):
    was, now = dig(sent, name, ABSENT), dig(stored, name, ABSENT)
    cells = ["(absent)" if value is ABSENT else show(value) for value in (was, now)]
    return [name, *cells, "REWRITTEN" if was != now else ""]


def indented(text):
    print(textwrap.indent(text, "   "))


def show_seeded_booking(client, booking_id, sent):
    """Print what the API kept and what the audit can still see of it."""
    stored = client.request("GET", f"/booking/{booking_id}").json
    print(f"2. What the API stored as booking {booking_id}")
    names = ("bookingdates.checkin", "bookingdates.checkout", "totalprice", "additionalneeds")
    indented(report.table(("Field", "Sent", "Stored", ""), [field_row(name, sent, stored) for name in names]))
    print(f"\n   Nights from the sent dates, read day-first as the console did: {stay_nights(sent)}")
    print(f"   Nights from the stored dates, read month-first as the API did: {stay_nights(stored)}\n")
    print(f"3. Audit of booking {booking_id}")
    indented(report.table(report.FLAG_HEADERS, report.flag_rows(run_audit(client, [booking_id])["flags"])))
    print("\n   The same rules on the raw payload, before the API rewrote it:")
    indented(report.table(report.FLAG_HEADERS, report.flag_rows(scan("payload", sent))))
    print("\n   The audit sees only what survived. The rewritten checkout is a real date now, so it passes")
    print("   the audit's date rules. Only the gate catches it: G03 compares what was sent with what was stored.\n")


def cmd_demo(args):
    client = connect(args)
    if client is None:
        return INCONCLUSIVE_EXIT
    marker = api.new_marker()
    sent = {"firstname": "فهد العتيبي", "lastname": marker, **BK_1043}
    print(f"Nuzul demo, run {marker}: one bad voice-agent call, end to end\n")
    print(f"1. The voice agent posts a booking shaped like BK-1043\n   POST /booking {show(sent)}")
    try:
        reply = client.request("POST", "/booking", sent)
        print(f"   -> {reply.status}\n")
        if reply.status == 200:
            show_seeded_booking(client, reply.json["bookingid"], sent)
        else:
            print("The API refused the payload, so this bad booking never got in. Nothing to audit.\n")
    finally:
        print(f"4. Cleanup: {tidy_up(client, marker)}")
    return 0


def id_list(text):
    return [int(item) for item in text.split(",")]


def main():
    shared = argparse.ArgumentParser(add_help=False)
    shared.add_argument("--base-url", default=os.environ.get("BOOKER_URL", api.DEFAULT_URL))
    shared.add_argument("--username", default=os.environ.get("BOOKER_USER", api.DEFAULT_USER))
    shared.add_argument("--password", default=os.environ.get("BOOKER_PASS", api.DEFAULT_PASS))
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("rules", help="print the rule catalogue").set_defaults(run=cmd_rules)
    gate = commands.add_parser("gate", parents=[shared], help="prove whether a release enforces the booking rules")
    gate.add_argument("--fail-on", choices=("critical", "high", "any"), default="critical",
                      help="lowest severity that makes the exit code 1")
    gate.set_defaults(run=cmd_gate)
    audit = commands.add_parser("audit", parents=[shared], help="scan the bookings that already got in")
    audit.add_argument("--limit", type=int, help="scan only the first N ids, newest first")
    audit.add_argument("--ids", type=id_list, help="comma-separated booking ids to scan")
    audit.add_argument("--concurrency", type=int, default=8)
    audit.add_argument("--json", action="store_true", help="print JSON instead of tables")
    audit.set_defaults(run=cmd_audit)
    demo = commands.add_parser("demo", parents=[shared], help="the BK-1043 booking, end to end")
    demo.set_defaults(run=cmd_demo)

    args = parser.parse_args()
    return args.run(args)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    sys.exit(main())
