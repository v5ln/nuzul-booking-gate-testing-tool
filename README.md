# nuzul-booking-gate

## What this is

A release gate and data audit for the booking API behind Nuzul Hospitality's staff console and Arabic voice agent. `gate` proves whether a build refuses bad bookings, and `audit` finds the bad bookings that already got in.

## Why this tool, why this problem

The API, the console and the voice agent meet in one place: everything writes through the API. Ticket NZL-217 asks to "stop bad dates getting in rather than cleaning up afterwards", so the API boundary is the single place one rule can protect every channel. The gate proves whether a release enforces the rules, and the audit finds what got through in the three weeks before it.

The two need each other, and BK-1043 shows why. The voice agent sent checkout `12/08/2026`. The console read that as 12 August and showed -3 nights. The API read it as 8 December and stored `2026-12-08`, a real date 115 nights after check-in. After that rewrite the stored date passes every date rule in the audit. Only a check that compares what was sent with what was stored can catch it, and that is G03.

The console and the voice agent still need their own checks, because this tool stops at the API. The next step, out of scope here, is a transcript-to-record check for the voice seam: does the booking that was written match what the guest said?

## Quick start

Python 3.10 or newer. Standard library only, so there is no install step.

```bash
git clone https://github.com/v5ln/nuzul-booking-gate-testing-tool.git
cd nuzul-booking-gate-testing-tool
python3 gate.py rules              # what it checks, no network needed
python3 gate.py demo               # one BK-1043-shaped booking, end to end
python3 gate.py gate               # the release gate, about two minutes
python3 gate.py audit --limit 200  # the newest 200 bookings
python3 -m unittest                # the self-tests, offline
```

It defaults to the staging sandbox. The first request can be slow because staging sleeps when idle, so the tool waits up to 60 seconds for it. To test another build:

| Flag | Environment variable | Default |
| --- | --- | --- |
| `--base-url` | `BOOKER_URL` | `https://restful-booker.herokuapp.com` |
| `--username` | `BOOKER_USER` | the public sandbox user |
| `--password` | `BOOKER_PASS` | the public sandbox password |

`audit` also takes `--limit N`, `--ids 1,2,3`, `--concurrency N` (default 8) and `--json`. `gate` also takes `--fail-on critical|high|any`.

## What it checks

`python3 gate.py rules` prints these with the reason each one matters to Nuzul.

### `gate`: does this build refuse bad input?

It creates its own bookings, sends each input, checks what the API did, and cleans up.

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

"Rejected" means a 4xx and a follow-up read proving nothing was stored. The status alone is not enough on this API: see [Known limitations](#known-limitations).

### `audit`: what already got in?

It reads every booking with a bounded thread pool and changes nothing.

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

A real run of `python3 gate.py gate` against the current staging build, trimmed. G09 passing and everything else failing is the correct result: the gate has proved Release 14 is not ready.

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

Whole runs are committed, all from live output:

- [reports/sample-gate.md](reports/sample-gate.md): the full report for the run above.
- [reports/sample-demo.txt](reports/sample-demo.txt): the BK-1043 walkthrough.
- [reports/sample-audit.md](reports/sample-audit.md): a real `audit --limit 200`. A freshly reset sandbox holds almost no bad data, so one bad booking per rule was first seeded through the API, then deleted by marker afterwards. The "Jim Brown 111" rows are the sandbox's own.

## How to read a report

Each `gate` or `audit` run writes `reports/<command>-<UTC timestamp>.md` and `.json`. Only the samples above are in git.

A gate report opens with the verdict, the API, the run marker and the cleanup result, then one row per rule. Each rule then has its own section: severity, result, why it matters, what happened, and every request (method, path, body) with its response (status, body) in order. A developer can act on it without re-running anything. Long response bodies are clipped in the markdown and kept whole in the `.json`.

| Result | Meaning |
| --- | --- |
| `PASS` | Proven: the API did the right thing. |
| `FAIL` | Proven: the API did the wrong thing. |
| `INCONCLUSIVE` | Not proven either way: a reset, a timeout, refused credentials or a crash in the rule. Run it again. |

Failures differ in how bad they are:

| Message | Meaning |
| --- | --- |
| `accepted and stored as sent` | Bad data got in unchanged. The audit can find it later. |
| `accepted and silently rewritten` | Worse: the API changed it, so the original is gone and the audit may never see it. |
| `answered 4xx but stored the booking anyway` | The status says refused, the data says otherwise. |

### Verdict and exit codes

| `gate` verdict | When | Exit code |
| --- | --- | --- |
| `PASS` | Nothing failed. | 0 |
| `WARN` | Only High, Medium or Low rules failed. | 0 by default, 1 if a failure is at or above `--fail-on` |
| `BLOCK` | A Critical rule failed. | 1 |
| `INCONCLUSIVE` | The API could not be reached, it refused the credentials, G09 failed, or a rule could not be proven and no Critical rule failed. | 2 |

Exit 2 is not a green light. It means the run proved nothing, and a failing G09 may be a dead environment or a real regression, so someone has to look.

`audit` exits 1 if any Critical flag is raised, 0 otherwise, and 2 if the API cannot be reached or no booking could be read.

## Using it as a release safeguard

**Release 14 does not ship while `gate` returns BLOCK.**

Point `BOOKER_URL` at the build that is going out and run `python3 gate.py gate`. On BLOCK, attach the report to NZL-217: it already holds the exact request and response for every failure. A good release does not repair old data, so run `python3 gate.py audit` afterwards to size the cleanup.

[.github/workflows/gate.yml](.github/workflows/gate.yml) makes this repeatable:

- Every push runs the unit tests on Python 3.10 and 3.13.
- A nightly schedule (02:00 UTC) and a manual "Run workflow" trigger run `audit`, then `gate`, and keep the reports as a build artifact.
- The job goes red on BLOCK and stays red until the API is fixed. That is the signal, not a broken pipeline.

GitHub runs scheduled workflows from the default branch only.

## Adding a rule

A rule is one function in [booking_gate/rules_gate.py](booking_gate/rules_gate.py) that returns a result object. The decorator registers it, so it runs in `gate` and shows up in `rules` and the reports with no other change:

```python
@rule("G20", "A stay longer than a year is rejected", "High",
      "A 400-night stay is a typo, not a reservation.")
def g20(run):
    """Every date is valid, so only a length check can refuse this."""
    return run.must_refuse("G20", "bookingdates", bookingdates=run.dates(nights=400))
```

Run against staging, that rule reports:

```text
G20 High FAIL | accepted and stored as sent: bookingdates {"checkin": "2026-12-02", "checkout": "2028-01-06"}
```

`run.must_refuse` posts the booking, looks for the record and judges the rejection. For anything else, send requests with `run.call`, which records them as evidence, and return `passed("...")` or `failed("...")`. Raise `Inconclusive("...")` when the environment stopped the check. Audit rules in [booking_gate/rules_audit.py](booking_gate/rules_audit.py) work the same way: a function of one booking that returns `(field, value)` hits.

## Known limitations

- **Shared sandbox.** Other testers write here constantly. The booking count read 2,627 at one point and 104 a few minutes later, after a reset, so a count or a sample is only true for that moment. The tool deletes only bookings carrying its own run marker.
- **Resets.** Staging wipes itself about every ten minutes, not on a fixed clock (three resets came about ten minutes apart, then one gap ran past thirteen). The id counter restarts too, so a remembered id can belong to someone else afterwards. A rule caught by a reset reports `INCONCLUSIVE` instead of failing, the audit counts vanished bookings as not found, and cleanup re-reads every record and deletes it only if it still carries the marker.
- **The audit cannot see a rewrite.** `12/08/2026` is stored as `2026-12-08`, a real date, so on the stored BK-1043 record the audit raises A04 for the null price and nothing for the date. Only the gate catches that, at write time. Finding past rewrites takes a system that kept what was sent. The console appears to, so comparing console records with API records is the way to look for them.
- **Policy rules are opinions.** Same-day stays (G02, A02), zero prices (A05) and decimal prices (G12) are readings Nuzul may set differently. Zero is flagged by the audit but not gated, for that reason.
- **The console and the voice agent are not covered.** Two things to check there:
  - BK-1043 shows `12/08/2026` and `SAR 250` on the console, but for that payload the API stores `2026-12-08` and `null`, and it has no status field to hold "Confirmed". So the console is not simply showing the API's record, which sits oddly with "everything writes through the API".
  - Once the API refuses bad input, the voice agent has to handle a 4xx in the middle of a call, or a guest hears "confirmed" for a booking that does not exist.

Choices worth knowing about:

- With the default `--fail-on critical`, exit 1 means a Critical failure, so a `WARN` exits 0.
- A rule that could not be proven makes the verdict `INCONCLUSIVE`, unless a Critical failure has already proved `BLOCK`. It never counts as a pass.
- `--limit N` scans the newest N ids. The oldest ids are the sandbox's clean seed rows, so the lowest N could never flag anything.
- Lastname holds the run marker, so G09's Arabic goes in firstname and additionalneeds, and the gate does not test an Arabic lastname. The G13 and G14 cases that blank or drop lastname carry the marker in firstname instead, and cleanup searches both fields.
- G03 and G04 use fixed dates, which are now in the past. A release that adds a no-past-dates rule would refuse them for that reason. The other rules use dates 30 days ahead.

Seen on staging and not gated:

- A POST without an `Accept` header answers 418 and stores the booking anyway. This is why the gate looks for the record after a rejection instead of trusting the status.
- PUT and PATCH on a missing id answer 405, which looks like a rejection. This is why G06 to G08 read the booking back.
- The `checkout` filter behaves as `<=`. The docs say `>=`.
- A booking with checkin `0NaN-aN-aN` comes back from every `checkin` search, even `2199-01-01`, so corrupted bookings would pollute any arrivals search.
- The docs list `additionalneeds` as required, but the API accepts it missing. That gap is a likely source of `undefined` on the console.
- A lastname of spaces is stored as an empty string.

## Author

Omar Al-Banna
