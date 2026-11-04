# system.get_system_time field matrix

Draft for Architect row-by-row review (audit #99). Code @ main `21e5d66`. Rows with decision `unreviewed` are not yet checked; their read sites are module-wide grep hints only.



| field | code read site | decision | test that proves it | status |
|---|---|---|---|---|
| `tz_offset` | none found by grep | unreviewed | none | open |
| `city_index` | none found by grep | unreviewed | none | open |
| `dst_active` | none found by grep | unreviewed | none | open |
| `gmt_seconds` | none found by grep | unreviewed | none | open |
| `uptime_seconds` | none found by grep | unreviewed | none | open |
| `BOOTED` | none found by grep | unreviewed | none | open |
| `LOCAL` | none found by grep | unreviewed | none | open |
| `error_code` | grep hint (module-wide, unconfirmed): src/elke27_lib/handlers/system.py:67 | unreviewed | none | open |
