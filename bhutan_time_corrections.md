# Bhutan Upload Time Corrections

Existing TimeCorrection records as of 2026-04-01, sorted by retrieval date.

| Station          | Retrieved   | Images | Correction           | Status              | Date Range                  |
|------------------|-------------|--------|----------------------|---------------------|-----------------------------|
| WCNP_006         | 2025-11-05 |    423 | -2y                  | PENDING             |                             |
| JDNP-C006        | 2026-02-11 |   1360 | -12h                 | PENDING             |                             |
| WCNP_004         | 2026-02-12 |    483 | +45m                 | PENDING             |                             |
| JDNP-009         | 2026-02-13 |    108 | +5d +30m             | PENDING             |                             |
| ThDFO_9          | 2026-02-13 |    414 | +1d +14h +28m        | APPLIED 2026-03-16  |                             |
| JSWNP-FM-28      | 2026-02-14 |   2124 | -1h                  | PENDING             |                             |
| JSWNP-FM-032     | 2026-02-15 |   1433 | -1h                  | APPLIED 2026-03-16  | 2025-10-20 to 2026-02-15    |
| JSWNP-FM-003     | 2026-02-17 |    270 | +1h                  | APPLIED 2026-03-16  |                             |
| JSWNP-FM-004     | 2026-02-17 |   1732 | +1h                  | APPLIED 2026-03-16  |                             |
| JSWNP-FM-022     | 2026-02-26 |   1500 | -3d -22h -40m        | PENDING             |                             |
| JSWNP-FM-30      | 2026-03-11 |   1464 | -1h                  | APPLIED 2026-03-16  | 2025-10-16 to 2026-02-18    |
| WCNP_013         | 2200-12-12 |      1 | +2y -3mo +13m        | PENDING             | 2025-06-01 to 2025-06-04    |

## Notes

- **5 APPLIED** (all on Mar 16, 2026): Manual corrections for timezone/DST discrepancies.
  The EXIF-based fix will overwrite these with the correct values from EXIF DateTimeOriginal.
- **7 PENDING**: Not yet applied. Mix of timezone fixes and camera clock drift.
  - Clock drift corrections (e.g., WCNP_004 +45m, WCNP_006 -2y, JDNP-009 +5d30m) may still
    need to be applied *after* the EXIF-based fix, since the camera clock itself was wrong.
  - Timezone corrections (e.g., JDNP-C006 -12h, JSWNP-FM-28 -1h) will be handled by the
    EXIF-based fix and should be reviewed/removed afterward.
