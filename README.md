# nuzul-booking-gate

## What this is

A release gate and data audit for Nuzul Hospitality's booking API. `gate` proves whether a build refuses bad bookings, and `audit` finds the bad bookings already stored.

## Why this tool, why this problem

The staff console and the Arabic voice agent both write through one API, and ticket NZL-217 asks to "stop bad dates getting in rather than cleaning up afterwards". The API boundary is the one place a rule protects every channel, so that is where this tool tests. The gate proves whether a release enforces the rules, and the audit finds what already got through.

BK-1043 shows why both are needed. The voice agent sent checkout `12/08/2026`. The console read it as 12 August and showed -3 nights, while the API stored 8 December, 115 nights after check-in. The stored date is valid, so only a check that compares what was sent with what was stored can catch it, and that is G03.

The console and the voice agent still need their own checks. The next step, out of scope here, is a transcript-to-record check for the voice seam.

## Quick start

Python 3.10 or newer, standard library only, nothing to install.

```bash
git clone https://github.com/v5ln/nuzul-booking-gate-testing-tool.git
cd nuzul-booking-gate-testing-tool
python3 gate.py rules              # what it checks
python3 gate.py demo               # one BK-1043-shaped booking, end to end
python3 gate.py gate               # the release gate, about two minutes
python3 gate.py audit --limit 200  # the newest 200 bookings
python3 -m unittest                # the self-tests, offline
```

It targets the staging sandbox by default. Staging sleeps when idle, so the first call can take up to a minute. To test another build, use `--base-url` or `BOOKER_URL`, with `--username`/`BOOKER_USER` and `--password`/`BOOKER_PASS` if needed.

## What it checks

`python3 gate.py rules` prints both lists with the reason each rule matters to Nuzul.

### `gate`: does this build refuse bad input?

It creates its own bookings, sends each input, checks what the API stored, and deletes what it created.

| Id | Rule | Severity |
| --- | --- | --- |
| G01 | POST with checkout before checkin is rejected and nothing is stored | Critical |
| G02 | POST with checkin equal to checkout is rejected | High |
| G03 | POST with a non-ISO date is rejected, never silently reinterpreted | Critical |
| G04 | POST with an impossible calendar date is rejected, never rolled | Critical |
| G05 | POST with an unparseable date is rejected, never stored as `0NaN-aN-aN` | Critical |
| G06 | PUT with checkout before checkin is rejected | Critical |
| G07 | PATCH with checkout before checkin is rejected | Critical |
| G08 | PATCH with only a new checkout keeps the existing checkin | Critical |
| G09 | A valid booking with an Arabic name is stored exactly as sent (the sanity check) | Critical |
| G10 | totalprice as a non-numeric string is rejected, never stored as null | High |
| G11 | Negative totalprice is rejected | High |
| G12 | Decimal totalprice is preserved, not truncated | Medium |
| G13 | A missing required field returns 400, not 500 | High |
| G14 | Empty firstname or lastname is rejected | High |
| G15 | depositpaid as a string is rejected, not coerced | Medium |
| G16 | POST /auth with a wrong password returns 401, not 200 | Medium |
| G17 | `GET /booking?checkin=D` returns a booking whose checkin is exactly D | Medium |
| G18 | A filter with a non-ISO date returns 400, not 500 | Low |
| G19 | DELETE of a missing id returns 404, not 405 | Low |

"Rejected" means a 4xx and a follow-up read showing nothing was stored. The status alone is not enough, because this API can answer with a 4xx and store the booking anyway.

### `audit`: what already got in?

It reads every booking, eight at a time by default, and changes nothing.

| Id | Flag | Severity |
| --- | --- | --- |
| A01 | checkout before checkin | Critical |
| A02 | checkout equals checkin | High |
| A03 | a date that is not a real `CCYY-MM-DD` calendar date | Critical |
| A04 | totalprice null, non-numeric, or negative | High |
| A05 | totalprice zero | Medium |
| A06 | empty or whitespace-only firstname or lastname | High |
| A07 | names or values that look like test data | Info |

## Sample output

A real run of `python3 gate.py gate` against the current staging build, trimmed. G09 passes and the other 18 rules fail, which proves Release 14 is not ready.

```text
Release gate against https://restful-booker.herokuapp.com, run gate-d7d4aa98. G09 first: it proves the environment.

Id    Severity  Result        What happened
G09   Critical  PASS          stored exactly as sent, Arabic text intact
G01   Critical  FAIL          accepted and stored as sent: bookingdates {"checkin": "2026-12-02", "checkout": "2026-11-27"}
G03   Critical  FAIL          accepted and silently rewritten: bookingdates.checkout sent "12/08/2026", stored "2026-12-08"
G04   Critical  FAIL          accepted and silently rewritten: bookingdates.checkin sent "2026-02-30", stored "2026-03-02"
G05   Critical  FAIL          accepted and silently rewritten: bookingdates.checkin sent "not-a-date", stored "0NaN-aN-aN"
G08   Critical  FAIL          checkin wiped by a checkout-only PATCH: was "2026-12-02", now "0NaN-aN-aN"
G10   High      FAIL          accepted and silently rewritten: totalprice sent "SAR 250", stored null
G12   Medium    FAIL          truncated: totalprice sent 199.99, stored 199
G17   Medium    FAIL          checkin exactly 2027-03-02 not returned, the day after is: filter acts as >, docs say >=
G19   Low       FAIL          DELETE of a missing id: answered 405; expected 404

Cleanup: deleted 17, left 0
Verdict: BLOCK, exit code 1. Not passing: G01, G02, G03, G04, G05, G06, G07, G08, G10, G11, G12, G13, G14, G15, G16, G17, G18, G19
```

Full outputs from real runs:

- [reports/sample-gate.md](reports/sample-gate.md): the complete report for the run above.
- [reports/sample-demo.txt](reports/sample-demo.txt): the BK-1043 walkthrough.
- [reports/sample-audit.md](reports/sample-audit.md): an `audit --limit 200`. The sandbox had almost no bad data of its own, so one bad booking per rule was seeded through the API first and deleted afterwards. The "Jim Brown 111" rows are the sandbox's own.

## How to read a report

Each `gate` or `audit` run writes `reports/<command>-<UTC timestamp>.md` and a `.json` copy. A gate report gives every rule's result, why it matters, and the exact requests and responses, so a developer can act on it without re-running anything.

- `PASS` and `FAIL` are proven results. `accepted and silently rewritten` is worse than `accepted and stored as sent`, because the original value is gone.
- `INCONCLUSIVE` means not proven either way: a reset, a timeout, a refused login or a crash in the rule. Run it again.

| `gate` verdict | When | Exit code |
| --- | --- | --- |
| `PASS` | Nothing failed. | 0 |
| `WARN` | Only High, Medium or Low rules failed. | 0 by default (see `--fail-on`) |
| `BLOCK` | A Critical rule failed. | 1 |
| `INCONCLUSIVE` | The API was unreachable or refused the login, G09 failed, or a rule could not be proven and no Critical rule failed. | 2 |

`--fail-on` sets the lowest severity whose failure exits 1: `critical` (the default), `high` or `any`. Exit 2 is not a green light: the run proved nothing, so someone has to look. `audit` exits 1 if it finds a Critical flag, 0 if not, and 2 if it cannot read the API.

## Using it as a release safeguard

**Release 14 does not ship while `gate` returns BLOCK.**

Run `python3 gate.py gate` against the build that is going out. On BLOCK, attach the report to NZL-217. A fix does not repair old data, so run `python3 gate.py audit` after it ships to size the cleanup.

[.github/workflows/gate.yml](.github/workflows/gate.yml) runs the unit tests on every push, and runs `audit` then `gate` nightly and on demand ("Run workflow" on the Actions tab), keeping the reports as a build artifact. The job stays red while the gate returns BLOCK. That is the safeguard working, not a broken pipeline.

## Adding a rule

A rule is one function in [booking_gate/rules_gate.py](booking_gate/rules_gate.py) that returns a result object. The decorator registers it, so it runs in `gate` and appears in `rules` and the reports with no other change:

```python
@rule("G20", "A stay longer than a year is rejected", "High",
      "A 400-night stay is a typo, not a reservation.")
def g20(run):
    """Every date is valid, so only a length check can refuse this."""
    return run.must_refuse("G20", "bookingdates", bookingdates=run.dates(nights=400))
```

Against staging, that rule reports:

```text
G20 High FAIL | accepted and stored as sent: bookingdates {"checkin": "2026-12-02", "checkout": "2028-01-06"}
```

For other kinds of check, send requests with `run.call` and return `passed("...")` or `failed("...")`. Audit rules in [booking_gate/rules_audit.py](booking_gate/rules_audit.py) are functions of one booking.

## Known limitations

- **Shared sandbox.** Other testers write here constantly, and the booking count read 2,627 at one point and 104 a few minutes later. The tool deletes only bookings carrying its own run marker.
- **Resets.** Staging wipes itself about every ten minutes (I measured gaps of 10, 10 and 17 minutes), and the id counter restarts. A rule caught by a reset reports `INCONCLUSIVE`, and cleanup re-checks the marker before every delete.
- **Policy rules are opinions.** Same-day stays (G02, A02), zero prices (A05) and decimal prices (G12) are choices Nuzul may set differently.
- **The audit cannot see a rewrite.** The stored BK-1043 record raises only A04, because `2026-12-08` is a real date. The console seems to keep what was sent, so comparing console records with API records is the way to find past rewrites.
- **The console and the voice agent are not covered.** Two things worth checking there. The console shows values the API never stores for BK-1043 (`12/08/2026`, `SAR 250`, status Confirmed), so it is not simply showing the API's record. And once the API refuses bad input, the voice agent has to handle a 4xx in the middle of a call.

Choices made where the requirements were open:

- With the default `--fail-on critical`, a `WARN` exits 0.
- A rule that could not be proven never counts as a pass.
- `--limit N` scans the newest ids, because the oldest are the sandbox's clean seed rows.
- The run marker lives in lastname, so G09 tests Arabic in firstname and additionalneeds, not in lastname.
- G03 and G04 use fixed dates that are now in the past, so a future no-past-dates rule would also refuse them.

Also found on staging, not gated:

- A POST without an `Accept` header answers 418 but stores the booking. This is why the gate checks storage, not just status.
- PUT and PATCH on a missing id answer 405, not 404.
- The `checkout` filter behaves as `<=`. The docs say `>=`.
- A booking with checkin `0NaN-aN-aN` matches every checkin search.
- The docs mark `additionalneeds` as required, but the API accepts it missing.
- A lastname of spaces is stored as an empty string.

## Author

Omar Al-Banna
