"""Terminal tables and the markdown and JSON reports."""
import json
import re
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

REPORTS = Path(__file__).resolve().parent.parent / "reports"
BODY_LIMIT = 600  # characters of a response body shown in markdown; the JSON keeps it all
FLAG_HEADERS = ("Booking", "Rule", "Severity", "Field", "Value", "Nights")


def clean(value, limit=70):
    """Make a value safe and visible: other testers' data is untrusted, and a blank name must show."""
    text = value if isinstance(value, str) and value.strip() else json.dumps(value, ensure_ascii=False)
    text = re.sub(r"[\x00-\x1f\x7f]", " ", text)
    return text if len(text) <= limit else text[:limit - 1] + "…"


def table(headers, rows):
    """Plain-text table. The last column is not padded, so long messages read as one line."""
    rows = [[str(cell) for cell in row] for row in rows]
    widths = [max(len(row[index]) for row in [headers, *rows]) for index in range(len(headers) - 1)]
    def line(row):
        return "  ".join([cell.ljust(width) for cell, width in zip(row, widths)] + [row[-1]]).rstrip()
    return "\n".join([line(headers), line(["-" * len(header) for header in headers])] + [line(row) for row in rows])


def md_row(cells):
    return "| " + " | ".join(str(cell).replace("|", "\\|") for cell in cells) + " |"


def md_table(headers, rows):
    return "\n".join([md_row(headers), md_row(["---"] * len(headers))] + [md_row(row) for row in rows])


def pretty(text):
    """Pretty-print a JSON body and clip what would drown the report."""
    try:
        text = json.dumps(json.loads(text), ensure_ascii=False, indent=2)
    except (TypeError, ValueError):
        text = str(text)
    if len(text) > BODY_LIMIT:
        return f"{text[:BODY_LIMIT]}\n... clipped, {len(text)} characters in total; the .json report has all of it"
    return text


def exchange_md(number, exchange):
    lines = [f"**{number}. `{exchange['method']} {exchange['path']}`**", ""]
    if exchange["body"] is not None:
        lines += ["Request body:", "", "```json", pretty(json.dumps(exchange["body"], ensure_ascii=False)), "```", ""]
    lines += [f"Response `{exchange['status']}`:", "", "```json", pretty(exchange["response"]), "```", ""]
    return lines


def gate_markdown(info, results):
    """A report a developer can act on without re-running anything."""
    counts = Counter(result.status for result in results)
    lines = ["# Release gate report", "", f"- **Verdict: {info['verdict']}** (exit code {info['exit_code']})",
             f"- API: {info['base_url']}", f"- Finished: {info['finished']} UTC", f"- Run marker: `{info['marker']}`",
             f"- Results: {counts['PASS']} passed, {counts['FAIL']} failed, {counts['INCONCLUSIVE']} inconclusive",
             f"- Cleanup: {info['cleanup']}", "",
             md_table(("Id", "Severity", "Result", "What happened"), [
                 (result.rule_id, result.severity, result.status, result.message) for result in results]), ""]
    for result in results:
        lines += [f"## {result.rule_id}: {result.title}", "", f"- **Severity:** {result.severity}",
                  f"- **Result:** {result.status}", f"- **Why this matters for Nuzul:** {result.why}",
                  f"- **What happened:** {result.message}", ""]
        for number, exchange in enumerate(result.exchanges, 1):
            lines += exchange_md(number, exchange)
    return "\n".join(lines)


def flag_rows(flags):
    return [(flag.booking_id, flag.rule_id, flag.severity, flag.field, clean(flag.value),
             "?" if flag.nights is None else flag.nights) for flag in flags]


def audit_summary(audit):
    """The lines shared by the terminal output and the markdown report."""
    severities = ", ".join(f"{name} {count}" for name, count in audit["by_severity"].items()) or "none"
    rules = ", ".join(f"{name} {count}" for name, count in audit["by_rule"].items()) or "none"
    return [f"Scanned {audit['scanned']} of {audit['requested']} bookings",
            f"Flagged {audit['flagged']} bookings with {len(audit['flags'])} flags",
            f"By severity: {severities}", f"By rule: {rules}",
            f"Not found (reset or deleted during the scan): {audit['not_found']}",
            f"Failed after retries: {audit['failed']}"]


def audit_markdown(info, audit):
    lines = ["# Booking data audit", "", f"- API: {info['base_url']}", f"- Finished: {info['finished']} UTC"]
    lines += [f"- {line}" for line in audit_summary(audit)]
    lines += ["", md_table(FLAG_HEADERS, flag_rows(audit["flags"])), ""]
    return "\n".join(lines)


def save(kind, markdown, data):
    """Write reports/<kind>-<UTC timestamp>.md and .json; return both paths."""
    REPORTS.mkdir(exist_ok=True)
    stem = REPORTS / f"{kind}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    paths = stem.with_suffix(".md"), stem.with_suffix(".json")
    paths[0].write_text(markdown, encoding="utf-8")
    paths[1].write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return paths


def save_gate(info, results):
    data = {**info, "results": [asdict(result) for result in results]}
    return save("gate", gate_markdown(info, results), data)


def audit_data(info, audit):
    return {**info, **audit, "flags": [asdict(flag) for flag in audit["flags"]]}


def save_audit(info, audit):
    return save("audit", audit_markdown(info, audit), audit_data(info, audit))
