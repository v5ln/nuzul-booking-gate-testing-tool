# Booking data audit

- API: https://restful-booker.herokuapp.com
- Finished: 2026-11-02 23:54:57 UTC
- Scanned 199 of 200 bookings
- Flagged 13 bookings with 13 flags
- By severity: Critical 2, High 5, Medium 1, Info 5
- By rule: A01 1, A02 1, A03 1, A04 2, A05 1, A06 2, A07 5
- Not found (reset or deleted during the scan): 1
- Failed after retries: 0

| Booking | Rule | Severity | Field | Value | Nights |
| --- | --- | --- | --- | --- | --- |
| 1745 | A01 | Critical | bookingdates | 2026-12-15 -> 2026-12-10 | -5 |
| 1756 | A03 | Critical | bookingdates.checkin | 0NaN-aN-aN | ? |
| 1749 | A02 | High | bookingdates | 2026-12-10 -> 2026-12-10 | 0 |
| 1767 | A04 | High | totalprice | null | 5 |
| 1776 | A04 | High | totalprice | -100 | 5 |
| 1791 | A06 | High | firstname | "" | 5 |
| 1799 | A06 | High | lastname | "" | 5 |
| 1784 | A05 | Medium | totalprice | 0 | 5 |
| 1605 | A07 | Info | firstname | Jim Brown 111 | 365 |
| 1688 | A07 | Info | firstname | Jim Brown 111 | 365 |
| 1780 | A07 | Info | firstname | Jim Brown 111 | 365 |
| 1866 | A07 | Info | firstname | Jim Brown 111 | 365 |
| 1873 | A07 | Info | firstname | Test | 5 |
