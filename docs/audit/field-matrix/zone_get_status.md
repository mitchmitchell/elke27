# zone.get_status field matrix

Draft for Architect row-by-row review (audit #99). Code @ main `21e5d66`. Rows with decision `unreviewed` are not yet checked; their read sites are module-wide grep hints only.

Only secure_state values NORMAL and VIOLATED are documented; the handler also accepts SECURE/RESTORE/TROUBLE/TAMPER/ALARM/BYPASS substrings (zone.py:1119-1138).

| field | code read site | decision | test that proves it | status |
|---|---|---|---|---|
| `zone_id` | none | read (routing key) | none | open |
| `BYPASSED` | src/elke27_lib/handlers/zone.py:1109 | read | test/test_zone_status_flags.py | open (check doc-shaped) |
| `contact_state` | none | missing (EOLR/OPEN/... values undocumented beyond example) | none | finding (S3) |
| `secure_state` | src/elke27_lib/handlers/zone.py:1119 | read (NORMAL clears, VIOLATED sets violated) | test/test_zone_status_flags.py | open (check doc-shaped) |
| `error_code` | none | read | none | open |
| `rssi` | none in zone handler | missing | none | finding (S3) |
| `low_batt` | src/elke27_lib/handlers/zone.py:1112 | read | none | open |
| `bypassed` | zone.py:1109 fallback | not documented | none | open |
| `low_battery` | zone.py:1112 fallback | not documented | none | open |
| `trouble` | zone.py:1115 | not documented | none | open |
| `tamper` | zone.py:1115 | not documented | none | open |
| `alarm` | zone.py:1115 | not documented | none | open |
| `violated` | zone.py:1115 | not documented | none | open |
| `enabled` | zone.py:1115 | not documented | none | open |
