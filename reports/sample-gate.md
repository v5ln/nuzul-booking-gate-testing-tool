# Release gate report

- **Verdict: BLOCK** (exit code 1)
- API: https://restful-booker.herokuapp.com
- Finished: 2026-11-02 23:56:51 UTC
- Run marker: `gate-d7d4aa98`
- Results: 1 passed, 18 failed, 0 inconclusive
- Cleanup: deleted 17, left 0

| Id | Severity | Result | What happened |
| --- | --- | --- | --- |
| G01 | Critical | FAIL | accepted and stored as sent: bookingdates {"checkin": "2026-12-02", "checkout": "2026-11-27"} |
| G02 | High | FAIL | accepted and stored as sent: bookingdates {"checkin": "2026-12-02", "checkout": "2026-12-02"} |
| G03 | Critical | FAIL | accepted and silently rewritten: bookingdates.checkout sent "12/08/2026", stored "2026-12-08" |
| G04 | Critical | FAIL | accepted and silently rewritten: bookingdates.checkin sent "2026-02-30", stored "2026-03-02" |
| G05 | Critical | FAIL | accepted and silently rewritten: bookingdates.checkin sent "not-a-date", stored "0NaN-aN-aN" |
| G06 | Critical | FAIL | accepted with 200 and stored: bookingdates {"checkin": "2026-12-02", "checkout": "2026-11-27"} |
| G07 | Critical | FAIL | accepted with 200 and stored: bookingdates {"checkin": "2026-12-02", "checkout": "2026-11-27"} |
| G08 | Critical | FAIL | checkin wiped by a checkout-only PATCH: was "2026-12-02", now "0NaN-aN-aN" |
| G09 | Critical | PASS | stored exactly as sent, Arabic text intact |
| G10 | High | FAIL | accepted and silently rewritten: totalprice sent "SAR 250", stored null |
| G11 | High | FAIL | accepted and stored as sent: totalprice -100 |
| G12 | Medium | FAIL | truncated: totalprice sent 199.99, stored 199 |
| G13 | High | FAIL | missing firstname: answered 500; missing totalprice: answered 500; missing depositpaid: answered 500; missing bookingdates: answered 500; missing lastname: answered 500; missing checkin: answered 500; firstname as a number: answered 500; expected 400 |
| G14 | High | FAIL | accepted and stored as sent: firstname ""; accepted and stored as sent: lastname "" |
| G15 | Medium | FAIL | accepted and silently rewritten: depositpaid sent "yes", stored true |
| G16 | Medium | FAIL | wrong password: answered 200; expected 401 |
| G17 | Medium | FAIL | checkin exactly 2027-03-02 not returned, the day after is: filter acts as >, docs say >= |
| G18 | Low | FAIL | checkin=15/08/2026: answered 500; expected 400 |
| G19 | Low | FAIL | DELETE of a missing id: answered 405; expected 404 |

## G01: POST with checkout before checkin is rejected and nothing is stored

- **Severity:** Critical
- **Result:** FAIL
- **Why this matters for Nuzul:** A guest cannot leave before arriving; BK-1043 reached reception showing -3 nights.
- **What happened:** accepted and stored as sent: bookingdates {"checkin": "2026-12-02", "checkout": "2026-11-27"}

**1. `POST /booking`**

Request body:

```json
{
  "firstname": "G01",
  "lastname": "gate-d7d4aa98",
  "totalprice": 250,
  "depositpaid": true,
  "bookingdates": {
    "checkin": "2026-12-02",
    "checkout": "2026-11-27"
  },
  "additionalneeds": "Breakfast"
}
```

Response `200`:

```json
{
  "bookingid": 2246,
  "booking": {
    "firstname": "G01",
    "lastname": "gate-d7d4aa98",
    "totalprice": 250,
    "depositpaid": true,
    "bookingdates": {
      "checkin": "2026-12-02",
      "checkout": "2026-11-27"
    },
    "additionalneeds": "Breakfast"
  }
}
```

**2. `GET /booking?firstname=G01&lastname=gate-d7d4aa98`**

Response `200`:

```json
[
  {
    "bookingid": 2246
  }
]
```

**3. `GET /booking/2246`**

Response `200`:

```json
{
  "firstname": "G01",
  "lastname": "gate-d7d4aa98",
  "totalprice": 250,
  "depositpaid": true,
  "bookingdates": {
    "checkin": "2026-12-02",
    "checkout": "2026-11-27"
  },
  "additionalneeds": "Breakfast"
}
```

## G02: POST with checkin equal to checkout is rejected

- **Severity:** High
- **Result:** FAIL
- **Why this matters for Nuzul:** A zero-night stay has no room to assign and nothing to bill, yet shows as Confirmed.
- **What happened:** accepted and stored as sent: bookingdates {"checkin": "2026-12-02", "checkout": "2026-12-02"}

**1. `POST /booking`**

Request body:

```json
{
  "firstname": "G02",
  "lastname": "gate-d7d4aa98",
  "totalprice": 250,
  "depositpaid": true,
  "bookingdates": {
    "checkin": "2026-12-02",
    "checkout": "2026-12-02"
  },
  "additionalneeds": "Breakfast"
}
```

Response `200`:

```json
{
  "bookingid": 2267,
  "booking": {
    "firstname": "G02",
    "lastname": "gate-d7d4aa98",
    "totalprice": 250,
    "depositpaid": true,
    "bookingdates": {
      "checkin": "2026-12-02",
      "checkout": "2026-12-02"
    },
    "additionalneeds": "Breakfast"
  }
}
```

**2. `GET /booking?firstname=G02&lastname=gate-d7d4aa98`**

Response `200`:

```json
[
  {
    "bookingid": 2267
  }
]
```

**3. `GET /booking/2267`**

Response `200`:

```json
{
  "firstname": "G02",
  "lastname": "gate-d7d4aa98",
  "totalprice": 250,
  "depositpaid": true,
  "bookingdates": {
    "checkin": "2026-12-02",
    "checkout": "2026-12-02"
  },
  "additionalneeds": "Breakfast"
}
```

## G03: POST with a non-ISO date is rejected, never silently reinterpreted

- **Severity:** Critical
- **Result:** FAIL
- **Why this matters for Nuzul:** The voice agent wrote checkout 12/08/2026 on BK-1043; the API reads it as 8 December.
- **What happened:** accepted and silently rewritten: bookingdates.checkout sent "12/08/2026", stored "2026-12-08"

**1. `POST /booking`**

Request body:

```json
{
  "firstname": "G03",
  "lastname": "gate-d7d4aa98",
  "totalprice": 250,
  "depositpaid": true,
  "bookingdates": {
    "checkin": "2026-08-01",
    "checkout": "12/08/2026"
  },
  "additionalneeds": "Breakfast"
}
```

Response `200`:

```json
{
  "bookingid": 2289,
  "booking": {
    "firstname": "G03",
    "lastname": "gate-d7d4aa98",
    "totalprice": 250,
    "depositpaid": true,
    "bookingdates": {
      "checkin": "2026-08-01",
      "checkout": "2026-12-08"
    },
    "additionalneeds": "Breakfast"
  }
}
```

**2. `GET /booking?firstname=G03&lastname=gate-d7d4aa98`**

Response `200`:

```json
[
  {
    "bookingid": 2289
  }
]
```

**3. `GET /booking/2289`**

Response `200`:

```json
{
  "firstname": "G03",
  "lastname": "gate-d7d4aa98",
  "totalprice": 250,
  "depositpaid": true,
  "bookingdates": {
    "checkin": "2026-08-01",
    "checkout": "2026-12-08"
  },
  "additionalneeds": "Breakfast"
}
```

## G04: POST with an impossible calendar date is rejected, never rolled

- **Severity:** Critical
- **Result:** FAIL
- **Why this matters for Nuzul:** A date that does not exist turns into a different real date nobody agreed to.
- **What happened:** accepted and silently rewritten: bookingdates.checkin sent "2026-02-30", stored "2026-03-02"

**1. `POST /booking`**

Request body:

```json
{
  "firstname": "G04",
  "lastname": "gate-d7d4aa98",
  "totalprice": 250,
  "depositpaid": true,
  "bookingdates": {
    "checkin": "2026-02-30",
    "checkout": "2026-03-05"
  },
  "additionalneeds": "Breakfast"
}
```

Response `200`:

```json
{
  "bookingid": 2312,
  "booking": {
    "firstname": "G04",
    "lastname": "gate-d7d4aa98",
    "totalprice": 250,
    "depositpaid": true,
    "bookingdates": {
      "checkin": "2026-03-02",
      "checkout": "2026-03-05"
    },
    "additionalneeds": "Breakfast"
  }
}
```

**2. `GET /booking?firstname=G04&lastname=gate-d7d4aa98`**

Response `200`:

```json
[
  {
    "bookingid": 2312
  }
]
```

**3. `GET /booking/2312`**

Response `200`:

```json
{
  "firstname": "G04",
  "lastname": "gate-d7d4aa98",
  "totalprice": 250,
  "depositpaid": true,
  "bookingdates": {
    "checkin": "2026-03-02",
    "checkout": "2026-03-05"
  },
  "additionalneeds": "Breakfast"
}
```

## G05: POST with an unparseable date is rejected, never stored as 0NaN-aN-aN

- **Severity:** Critical
- **Result:** FAIL
- **Why this matters for Nuzul:** Reception cannot act on 0NaN-aN-aN, and it matches every checkin search.
- **What happened:** accepted and silently rewritten: bookingdates.checkin sent "not-a-date", stored "0NaN-aN-aN"

**1. `POST /booking`**

Request body:

```json
{
  "firstname": "G05",
  "lastname": "gate-d7d4aa98",
  "totalprice": 250,
  "depositpaid": true,
  "bookingdates": {
    "checkin": "not-a-date",
    "checkout": "2026-12-07"
  },
  "additionalneeds": "Breakfast"
}
```

Response `200`:

```json
{
  "bookingid": 2343,
  "booking": {
    "firstname": "G05",
    "lastname": "gate-d7d4aa98",
    "totalprice": 250,
    "depositpaid": true,
    "bookingdates": {
      "checkin": "0NaN-aN-aN",
      "checkout": "2026-12-07"
    },
    "additionalneeds": "Breakfast"
  }
}
```

**2. `GET /booking?firstname=G05&lastname=gate-d7d4aa98`**

Response `200`:

```json
[
  {
    "bookingid": 2343
  }
]
```

**3. `GET /booking/2343`**

Response `200`:

```json
{
  "firstname": "G05",
  "lastname": "gate-d7d4aa98",
  "totalprice": 250,
  "depositpaid": true,
  "bookingdates": {
    "checkin": "0NaN-aN-aN",
    "checkout": "2026-12-07"
  },
  "additionalneeds": "Breakfast"
}
```

## G06: PUT with checkout before checkin is rejected

- **Severity:** Critical
- **Result:** FAIL
- **Why this matters for Nuzul:** A fix that guards only new bookings leaves every edit path open.
- **What happened:** accepted with 200 and stored: bookingdates {"checkin": "2026-12-02", "checkout": "2026-11-27"}

**1. `POST /booking`**

Request body:

```json
{
  "firstname": "G06",
  "lastname": "gate-d7d4aa98",
  "totalprice": 250,
  "depositpaid": true,
  "bookingdates": {
    "checkin": "2026-12-02",
    "checkout": "2026-12-07"
  },
  "additionalneeds": "Breakfast"
}
```

Response `200`:

```json
{
  "bookingid": 2359,
  "booking": {
    "firstname": "G06",
    "lastname": "gate-d7d4aa98",
    "totalprice": 250,
    "depositpaid": true,
    "bookingdates": {
      "checkin": "2026-12-02",
      "checkout": "2026-12-07"
    },
    "additionalneeds": "Breakfast"
  }
}
```

**2. `GET /booking/2359`**

Response `200`:

```json
{
  "firstname": "G06",
  "lastname": "gate-d7d4aa98",
  "totalprice": 250,
  "depositpaid": true,
  "bookingdates": {
    "checkin": "2026-12-02",
    "checkout": "2026-12-07"
  },
  "additionalneeds": "Breakfast"
}
```

**3. `PUT /booking/2359`**

Request body:

```json
{
  "firstname": "G06",
  "lastname": "gate-d7d4aa98",
  "totalprice": 250,
  "depositpaid": true,
  "bookingdates": {
    "checkin": "2026-12-02",
    "checkout": "2026-11-27"
  },
  "additionalneeds": "Breakfast"
}
```

Response `200`:

```json
{
  "firstname": "G06",
  "lastname": "gate-d7d4aa98",
  "totalprice": 250,
  "depositpaid": true,
  "bookingdates": {
    "checkin": "2026-12-02",
    "checkout": "2026-11-27"
  },
  "additionalneeds": "Breakfast"
}
```

**4. `GET /booking/2359`**

Response `200`:

```json
{
  "firstname": "G06",
  "lastname": "gate-d7d4aa98",
  "totalprice": 250,
  "depositpaid": true,
  "bookingdates": {
    "checkin": "2026-12-02",
    "checkout": "2026-11-27"
  },
  "additionalneeds": "Breakfast"
}
```

## G07: PATCH with checkout before checkin is rejected

- **Severity:** Critical
- **Result:** FAIL
- **Why this matters for Nuzul:** PATCH is the third way in; a date change must obey the same rule as a new booking.
- **What happened:** accepted with 200 and stored: bookingdates {"checkin": "2026-12-02", "checkout": "2026-11-27"}

**1. `POST /booking`**

Request body:

```json
{
  "firstname": "G07",
  "lastname": "gate-d7d4aa98",
  "totalprice": 250,
  "depositpaid": true,
  "bookingdates": {
    "checkin": "2026-12-02",
    "checkout": "2026-12-07"
  },
  "additionalneeds": "Breakfast"
}
```

Response `200`:

```json
{
  "bookingid": 2388,
  "booking": {
    "firstname": "G07",
    "lastname": "gate-d7d4aa98",
    "totalprice": 250,
    "depositpaid": true,
    "bookingdates": {
      "checkin": "2026-12-02",
      "checkout": "2026-12-07"
    },
    "additionalneeds": "Breakfast"
  }
}
```

**2. `GET /booking/2388`**

Response `200`:

```json
{
  "firstname": "G07",
  "lastname": "gate-d7d4aa98",
  "totalprice": 250,
  "depositpaid": true,
  "bookingdates": {
    "checkin": "2026-12-02",
    "checkout": "2026-12-07"
  },
  "additionalneeds": "Breakfast"
}
```

**3. `PATCH /booking/2388`**

Request body:

```json
{
  "bookingdates": {
    "checkin": "2026-12-02",
    "checkout": "2026-11-27"
  }
}
```

Response `200`:

```json
{
  "firstname": "G07",
  "lastname": "gate-d7d4aa98",
  "totalprice": 250,
  "depositpaid": true,
  "bookingdates": {
    "checkin": "2026-12-02",
    "checkout": "2026-11-27"
  },
  "additionalneeds": "Breakfast"
}
```

**4. `GET /booking/2388`**

Response `200`:

```json
{
  "firstname": "G07",
  "lastname": "gate-d7d4aa98",
  "totalprice": 250,
  "depositpaid": true,
  "bookingdates": {
    "checkin": "2026-12-02",
    "checkout": "2026-11-27"
  },
  "additionalneeds": "Breakfast"
}
```

## G08: PATCH with only a new checkout keeps the existing checkin

- **Severity:** Critical
- **Result:** FAIL
- **Why this matters for Nuzul:** Extending a stay at reception must not destroy the arrival date of a good booking.
- **What happened:** checkin wiped by a checkout-only PATCH: was "2026-12-02", now "0NaN-aN-aN"

**1. `POST /booking`**

Request body:

```json
{
  "firstname": "G08",
  "lastname": "gate-d7d4aa98",
  "totalprice": 250,
  "depositpaid": true,
  "bookingdates": {
    "checkin": "2026-12-02",
    "checkout": "2026-12-07"
  },
  "additionalneeds": "Breakfast"
}
```

Response `200`:

```json
{
  "bookingid": 2422,
  "booking": {
    "firstname": "G08",
    "lastname": "gate-d7d4aa98",
    "totalprice": 250,
    "depositpaid": true,
    "bookingdates": {
      "checkin": "2026-12-02",
      "checkout": "2026-12-07"
    },
    "additionalneeds": "Breakfast"
  }
}
```

**2. `GET /booking/2422`**

Response `200`:

```json
{
  "firstname": "G08",
  "lastname": "gate-d7d4aa98",
  "totalprice": 250,
  "depositpaid": true,
  "bookingdates": {
    "checkin": "2026-12-02",
    "checkout": "2026-12-07"
  },
  "additionalneeds": "Breakfast"
}
```

**3. `PATCH /booking/2422`**

Request body:

```json
{
  "bookingdates": {
    "checkout": "2026-12-10"
  }
}
```

Response `200`:

```json
{
  "firstname": "G08",
  "lastname": "gate-d7d4aa98",
  "totalprice": 250,
  "depositpaid": true,
  "bookingdates": {
    "checkin": "0NaN-aN-aN",
    "checkout": "2026-12-10"
  },
  "additionalneeds": "Breakfast"
}
```

**4. `GET /booking/2422`**

Response `200`:

```json
{
  "firstname": "G08",
  "lastname": "gate-d7d4aa98",
  "totalprice": 250,
  "depositpaid": true,
  "bookingdates": {
    "checkin": "0NaN-aN-aN",
    "checkout": "2026-12-10"
  },
  "additionalneeds": "Breakfast"
}
```

## G09: A valid booking with an Arabic name is stored exactly as sent

- **Severity:** Critical
- **Result:** PASS
- **Why this matters for Nuzul:** Sanity check and the Riyadh and Jeddah happy path: if this fails the environment is broken.
- **What happened:** stored exactly as sent, Arabic text intact

**1. `POST /booking`**

Request body:

```json
{
  "firstname": "فهد العتيبي",
  "lastname": "gate-d7d4aa98",
  "totalprice": 250,
  "depositpaid": true,
  "bookingdates": {
    "checkin": "2026-12-02",
    "checkout": "2026-12-07"
  },
  "additionalneeds": "سرير إضافي"
}
```

Response `200`:

```json
{
  "bookingid": 2213,
  "booking": {
    "firstname": "فهد العتيبي",
    "lastname": "gate-d7d4aa98",
    "totalprice": 250,
    "depositpaid": true,
    "bookingdates": {
      "checkin": "2026-12-02",
      "checkout": "2026-12-07"
    },
    "additionalneeds": "سرير إضافي"
  }
}
```

**2. `GET /booking?firstname=%D9%81%D9%87%D8%AF+%D8%A7%D9%84%D8%B9%D8%AA%D9%8A%D8%A8%D9%8A&lastname=gate-d7d4aa98`**

Response `200`:

```json
[
  {
    "bookingid": 2213
  }
]
```

**3. `GET /booking/2213`**

Response `200`:

```json
{
  "firstname": "فهد العتيبي",
  "lastname": "gate-d7d4aa98",
  "totalprice": 250,
  "depositpaid": true,
  "bookingdates": {
    "checkin": "2026-12-02",
    "checkout": "2026-12-07"
  },
  "additionalneeds": "سرير إضافي"
}
```

## G10: totalprice as a non-numeric string is rejected, never stored as null

- **Severity:** High
- **Result:** FAIL
- **Why this matters for Nuzul:** BK-1043 carried SAR 250; stored as null, nobody knows what to charge.
- **What happened:** accepted and silently rewritten: totalprice sent "SAR 250", stored null

**1. `POST /booking`**

Request body:

```json
{
  "firstname": "G10",
  "lastname": "gate-d7d4aa98",
  "totalprice": "SAR 250",
  "depositpaid": true,
  "bookingdates": {
    "checkin": "2026-12-02",
    "checkout": "2026-12-07"
  },
  "additionalneeds": "Breakfast"
}
```

Response `200`:

```json
{
  "bookingid": 2445,
  "booking": {
    "firstname": "G10",
    "lastname": "gate-d7d4aa98",
    "totalprice": null,
    "depositpaid": true,
    "bookingdates": {
      "checkin": "2026-12-02",
      "checkout": "2026-12-07"
    },
    "additionalneeds": "Breakfast"
  }
}
```

**2. `GET /booking?firstname=G10&lastname=gate-d7d4aa98`**

Response `200`:

```json
[
  {
    "bookingid": 2445
  }
]
```

**3. `GET /booking/2445`**

Response `200`:

```json
{
  "firstname": "G10",
  "lastname": "gate-d7d4aa98",
  "totalprice": null,
  "depositpaid": true,
  "bookingdates": {
    "checkin": "2026-12-02",
    "checkout": "2026-12-07"
  },
  "additionalneeds": "Breakfast"
}
```

## G11: Negative totalprice is rejected

- **Severity:** High
- **Result:** FAIL
- **Why this matters for Nuzul:** A negative total means paying the guest to stay.
- **What happened:** accepted and stored as sent: totalprice -100

**1. `POST /booking`**

Request body:

```json
{
  "firstname": "G11",
  "lastname": "gate-d7d4aa98",
  "totalprice": -100,
  "depositpaid": true,
  "bookingdates": {
    "checkin": "2026-12-02",
    "checkout": "2026-12-07"
  },
  "additionalneeds": "Breakfast"
}
```

Response `200`:

```json
{
  "bookingid": 2468,
  "booking": {
    "firstname": "G11",
    "lastname": "gate-d7d4aa98",
    "totalprice": -100,
    "depositpaid": true,
    "bookingdates": {
      "checkin": "2026-12-02",
      "checkout": "2026-12-07"
    },
    "additionalneeds": "Breakfast"
  }
}
```

**2. `GET /booking?firstname=G11&lastname=gate-d7d4aa98`**

Response `200`:

```json
[
  {
    "bookingid": 2468
  }
]
```

**3. `GET /booking/2468`**

Response `200`:

```json
{
  "firstname": "G11",
  "lastname": "gate-d7d4aa98",
  "totalprice": -100,
  "depositpaid": true,
  "bookingdates": {
    "checkin": "2026-12-02",
    "checkout": "2026-12-07"
  },
  "additionalneeds": "Breakfast"
}
```

## G12: Decimal totalprice is preserved, not truncated

- **Severity:** Medium
- **Result:** FAIL
- **Why this matters for Nuzul:** Truncating 199.99 to 199 under-bills every booking priced in halalas.
- **What happened:** truncated: totalprice sent 199.99, stored 199

**1. `POST /booking`**

Request body:

```json
{
  "firstname": "G12",
  "lastname": "gate-d7d4aa98",
  "totalprice": 199.99,
  "depositpaid": true,
  "bookingdates": {
    "checkin": "2026-12-02",
    "checkout": "2026-12-07"
  },
  "additionalneeds": "Breakfast"
}
```

Response `200`:

```json
{
  "bookingid": 2490,
  "booking": {
    "firstname": "G12",
    "lastname": "gate-d7d4aa98",
    "totalprice": 199,
    "depositpaid": true,
    "bookingdates": {
      "checkin": "2026-12-02",
      "checkout": "2026-12-07"
    },
    "additionalneeds": "Breakfast"
  }
}
```

**2. `GET /booking?firstname=G12&lastname=gate-d7d4aa98`**

Response `200`:

```json
[
  {
    "bookingid": 2490
  }
]
```

**3. `GET /booking/2490`**

Response `200`:

```json
{
  "firstname": "G12",
  "lastname": "gate-d7d4aa98",
  "totalprice": 199,
  "depositpaid": true,
  "bookingdates": {
    "checkin": "2026-12-02",
    "checkout": "2026-12-07"
  },
  "additionalneeds": "Breakfast"
}
```

## G13: A missing required field returns 400, not 500

- **Severity:** High
- **Result:** FAIL
- **Why this matters for Nuzul:** A 500 tells the voice agent nothing it can fix and looks like an outage.
- **What happened:** missing firstname: answered 500; missing totalprice: answered 500; missing depositpaid: answered 500; missing bookingdates: answered 500; missing lastname: answered 500; missing checkin: answered 500; firstname as a number: answered 500; expected 400

**1. `POST /booking`**

Request body:

```json
{
  "lastname": "gate-d7d4aa98",
  "totalprice": 250,
  "depositpaid": true,
  "bookingdates": {
    "checkin": "2026-12-02",
    "checkout": "2026-12-07"
  },
  "additionalneeds": "Breakfast"
}
```

Response `500`:

```json
Internal Server Error
```

**2. `POST /booking`**

Request body:

```json
{
  "firstname": "G13",
  "lastname": "gate-d7d4aa98",
  "depositpaid": true,
  "bookingdates": {
    "checkin": "2026-12-02",
    "checkout": "2026-12-07"
  },
  "additionalneeds": "Breakfast"
}
```

Response `500`:

```json
Internal Server Error
```

**3. `POST /booking`**

Request body:

```json
{
  "firstname": "G13",
  "lastname": "gate-d7d4aa98",
  "totalprice": 250,
  "bookingdates": {
    "checkin": "2026-12-02",
    "checkout": "2026-12-07"
  },
  "additionalneeds": "Breakfast"
}
```

Response `500`:

```json
Internal Server Error
```

**4. `POST /booking`**

Request body:

```json
{
  "firstname": "G13",
  "lastname": "gate-d7d4aa98",
  "totalprice": 250,
  "depositpaid": true,
  "additionalneeds": "Breakfast"
}
```

Response `500`:

```json
Internal Server Error
```

**5. `POST /booking`**

Request body:

```json
{
  "firstname": "gate-d7d4aa98",
  "totalprice": 250,
  "depositpaid": true,
  "bookingdates": {
    "checkin": "2026-12-02",
    "checkout": "2026-12-07"
  },
  "additionalneeds": "Breakfast"
}
```

Response `500`:

```json
Internal Server Error
```

**6. `POST /booking`**

Request body:

```json
{
  "firstname": "G13",
  "lastname": "gate-d7d4aa98",
  "totalprice": 250,
  "depositpaid": true,
  "bookingdates": {
    "checkout": "2026-12-07"
  },
  "additionalneeds": "Breakfast"
}
```

Response `500`:

```json
Internal Server Error
```

**7. `POST /booking`**

Request body:

```json
{
  "firstname": 12345,
  "lastname": "gate-d7d4aa98",
  "totalprice": 250,
  "depositpaid": true,
  "bookingdates": {
    "checkin": "2026-12-02",
    "checkout": "2026-12-07"
  },
  "additionalneeds": "Breakfast"
}
```

Response `500`:

```json
Internal Server Error
```

## G14: Empty firstname or lastname is rejected

- **Severity:** High
- **Result:** FAIL
- **Why this matters for Nuzul:** Reception cannot greet or find a guest with no name.
- **What happened:** accepted and stored as sent: firstname ""; accepted and stored as sent: lastname ""

**1. `POST /booking`**

Request body:

```json
{
  "firstname": "",
  "lastname": "gate-d7d4aa98",
  "totalprice": 250,
  "depositpaid": true,
  "bookingdates": {
    "checkin": "2026-12-02",
    "checkout": "2026-12-07"
  },
  "additionalneeds": "Breakfast"
}
```

Response `200`:

```json
{
  "bookingid": 2552,
  "booking": {
    "firstname": "",
    "lastname": "gate-d7d4aa98",
    "totalprice": 250,
    "depositpaid": true,
    "bookingdates": {
      "checkin": "2026-12-02",
      "checkout": "2026-12-07"
    },
    "additionalneeds": "Breakfast"
  }
}
```

**2. `GET /booking?firstname=&lastname=gate-d7d4aa98`**

Response `200`:

```json
[
  {
    "bookingid": 2552
  }
]
```

**3. `GET /booking/2552`**

Response `200`:

```json
{
  "firstname": "",
  "lastname": "gate-d7d4aa98",
  "totalprice": 250,
  "depositpaid": true,
  "bookingdates": {
    "checkin": "2026-12-02",
    "checkout": "2026-12-07"
  },
  "additionalneeds": "Breakfast"
}
```

**4. `POST /booking`**

Request body:

```json
{
  "firstname": "gate-d7d4aa98",
  "lastname": "",
  "totalprice": 250,
  "depositpaid": true,
  "bookingdates": {
    "checkin": "2026-12-02",
    "checkout": "2026-12-07"
  },
  "additionalneeds": "Breakfast"
}
```

Response `200`:

```json
{
  "bookingid": 2571,
  "booking": {
    "firstname": "gate-d7d4aa98",
    "lastname": "",
    "totalprice": 250,
    "depositpaid": true,
    "bookingdates": {
      "checkin": "2026-12-02",
      "checkout": "2026-12-07"
    },
    "additionalneeds": "Breakfast"
  }
}
```

**5. `GET /booking?firstname=gate-d7d4aa98&lastname=`**

Response `200`:

```json
[
  {
    "bookingid": 2571
  }
]
```

**6. `GET /booking/2571`**

Response `200`:

```json
{
  "firstname": "gate-d7d4aa98",
  "lastname": "",
  "totalprice": 250,
  "depositpaid": true,
  "bookingdates": {
    "checkin": "2026-12-02",
    "checkout": "2026-12-07"
  },
  "additionalneeds": "Breakfast"
}
```

## G15: depositpaid as a string is rejected, not coerced

- **Severity:** Medium
- **Result:** FAIL
- **Why this matters for Nuzul:** Coercing 'yes' to true records a deposit nobody checked.
- **What happened:** accepted and silently rewritten: depositpaid sent "yes", stored true

**1. `POST /booking`**

Request body:

```json
{
  "firstname": "G15",
  "lastname": "gate-d7d4aa98",
  "totalprice": 250,
  "depositpaid": "yes",
  "bookingdates": {
    "checkin": "2026-12-02",
    "checkout": "2026-12-07"
  },
  "additionalneeds": "Breakfast"
}
```

Response `200`:

```json
{
  "bookingid": 2598,
  "booking": {
    "firstname": "G15",
    "lastname": "gate-d7d4aa98",
    "totalprice": 250,
    "depositpaid": true,
    "bookingdates": {
      "checkin": "2026-12-02",
      "checkout": "2026-12-07"
    },
    "additionalneeds": "Breakfast"
  }
}
```

**2. `GET /booking?firstname=G15&lastname=gate-d7d4aa98`**

Response `200`:

```json
[
  {
    "bookingid": 2598
  }
]
```

**3. `GET /booking/2598`**

Response `200`:

```json
{
  "firstname": "G15",
  "lastname": "gate-d7d4aa98",
  "totalprice": 250,
  "depositpaid": true,
  "bookingdates": {
    "checkin": "2026-12-02",
    "checkout": "2026-12-07"
  },
  "additionalneeds": "Breakfast"
}
```

## G16: POST /auth with a wrong password returns 401, not 200

- **Severity:** Medium
- **Result:** FAIL
- **Why this matters for Nuzul:** A failed login answered with 200 looks like success to any client checking the status.
- **What happened:** wrong password: answered 200; expected 401

**1. `POST /auth`**

Request body:

```json
{
  "username": "admin",
  "password": "wrong-c57a95c5"
}
```

Response `200`:

```json
{
  "reason": "Bad credentials"
}
```

## G17: GET /booking?checkin=D returns a booking whose checkin is exactly D

- **Severity:** Medium
- **Result:** FAIL
- **Why this matters for Nuzul:** Reception searching arrivals from a date would miss everyone arriving on that date.
- **What happened:** checkin exactly 2027-03-02 not returned, the day after is: filter acts as >, docs say >=

**1. `POST /booking`**

Request body:

```json
{
  "firstname": "G17-exact",
  "lastname": "gate-d7d4aa98",
  "totalprice": 250,
  "depositpaid": true,
  "bookingdates": {
    "checkin": "2027-03-02",
    "checkout": "2027-03-07"
  },
  "additionalneeds": "Breakfast"
}
```

Response `200`:

```json
{
  "bookingid": 2620,
  "booking": {
    "firstname": "G17-exact",
    "lastname": "gate-d7d4aa98",
    "totalprice": 250,
    "depositpaid": true,
    "bookingdates": {
      "checkin": "2027-03-02",
      "checkout": "2027-03-07"
    },
    "additionalneeds": "Breakfast"
  }
}
```

**2. `GET /booking/2620`**

Response `200`:

```json
{
  "firstname": "G17-exact",
  "lastname": "gate-d7d4aa98",
  "totalprice": 250,
  "depositpaid": true,
  "bookingdates": {
    "checkin": "2027-03-02",
    "checkout": "2027-03-07"
  },
  "additionalneeds": "Breakfast"
}
```

**3. `POST /booking`**

Request body:

```json
{
  "firstname": "G17-later",
  "lastname": "gate-d7d4aa98",
  "totalprice": 250,
  "depositpaid": true,
  "bookingdates": {
    "checkin": "2027-03-03",
    "checkout": "2027-03-08"
  },
  "additionalneeds": "Breakfast"
}
```

Response `200`:

```json
{
  "bookingid": 2634,
  "booking": {
    "firstname": "G17-later",
    "lastname": "gate-d7d4aa98",
    "totalprice": 250,
    "depositpaid": true,
    "bookingdates": {
      "checkin": "2027-03-03",
      "checkout": "2027-03-08"
    },
    "additionalneeds": "Breakfast"
  }
}
```

**4. `GET /booking/2634`**

Response `200`:

```json
{
  "firstname": "G17-later",
  "lastname": "gate-d7d4aa98",
  "totalprice": 250,
  "depositpaid": true,
  "bookingdates": {
    "checkin": "2027-03-03",
    "checkout": "2027-03-08"
  },
  "additionalneeds": "Breakfast"
}
```

**5. `GET /booking?checkin=2027-03-02`**

Response `200`:

```json
[
  {
    "bookingid": 2343
  },
  {
    "bookingid": 2634
  }
]
```

**6. `GET /booking/2620`**

Response `200`:

```json
{
  "firstname": "G17-exact",
  "lastname": "gate-d7d4aa98",
  "totalprice": 250,
  "depositpaid": true,
  "bookingdates": {
    "checkin": "2027-03-02",
    "checkout": "2027-03-07"
  },
  "additionalneeds": "Breakfast"
}
```

## G18: A filter with a non-ISO date returns 400, not 500

- **Severity:** Low
- **Result:** FAIL
- **Why this matters for Nuzul:** A client sending a local-format date gets a server error instead of a usable message.
- **What happened:** checkin=15/08/2026: answered 500; expected 400

**1. `GET /booking?checkin=15/08/2026`**

Response `500`:

```json
Internal Server Error
```

## G19: DELETE of a missing id returns 404, not 405

- **Severity:** Low
- **Result:** FAIL
- **Why this matters for Nuzul:** A 405 hides the fact that the booking is already gone.
- **What happened:** DELETE of a missing id: answered 405; expected 404

**1. `POST /booking`**

Request body:

```json
{
  "firstname": "G19",
  "lastname": "gate-d7d4aa98",
  "totalprice": 250,
  "depositpaid": true,
  "bookingdates": {
    "checkin": "2026-12-02",
    "checkout": "2026-12-07"
  },
  "additionalneeds": "Breakfast"
}
```

Response `200`:

```json
{
  "bookingid": 2670,
  "booking": {
    "firstname": "G19",
    "lastname": "gate-d7d4aa98",
    "totalprice": 250,
    "depositpaid": true,
    "bookingdates": {
      "checkin": "2026-12-02",
      "checkout": "2026-12-07"
    },
    "additionalneeds": "Breakfast"
  }
}
```

**2. `GET /booking/2670`**

Response `200`:

```json
{
  "firstname": "G19",
  "lastname": "gate-d7d4aa98",
  "totalprice": 250,
  "depositpaid": true,
  "bookingdates": {
    "checkin": "2026-12-02",
    "checkout": "2026-12-07"
  },
  "additionalneeds": "Breakfast"
}
```

**3. `DELETE /booking/2670`**

Response `201`:

```json
Created
```

**4. `GET /booking/2670`**

Response `404`:

```json
Not Found
```

**5. `DELETE /booking/2670`**

Response `405`:

```json
Method Not Allowed
```
