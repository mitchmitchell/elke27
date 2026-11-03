# zone.get_status field matrix

Draft for Architect row-by-row review (audit #99). Code @ main `21e5d66`. Doc: `grokbots/architecture/Elk/elk-api/DealerAPI_UL_CHM-pdf.md`. Code read sites are grep hits on the field name in `src/elke27_lib/handlers/zone.py`; `none` means no handler reads it.

Doc example :3377-3381. Only secure_state values NORMAL and VIOLATED appear in the doc; the handler also accepts invented SECURE/RESTORE/TROUBLE/TAMPER/ALARM/BYPASS substrings (zone.py:1119-1138).

| doc field | doc location (file:line) | code read site | decision | test that proves it | status |
|---|---|---|---|---|---|
| `zone_id` | elk-api/DealerAPI_UL_CHM-pdf.md:3377 | src/elke27_lib/handlers/zone.py:258, src/elke27_lib/handlers/zone.py:265, src/elke27_lib/handlers/zone.py:278 | read (routing key) | none | open |
| `BYPASSED` | elk-api/DealerAPI_UL_CHM-pdf.md:3377 | src/elke27_lib/handlers/zone.py:1109 | read | test/test_zone_status_flags.py | open (check doc-shaped) |
| `contact_state` | elk-api/DealerAPI_UL_CHM-pdf.md:3377 | none | missing (EOLR/OPEN/... values undocumented beyond example) | none | finding (S3) |
| `secure_state` | elk-api/DealerAPI_UL_CHM-pdf.md:3377 | src/elke27_lib/handlers/zone.py:1119 | read (NORMAL clears, VIOLATED sets violated) | test/test_zone_status_flags.py | open (check doc-shaped) |
| `error_code` | elk-api/DealerAPI_UL_CHM-pdf.md:3377 | src/elke27_lib/handlers/zone.py:116, src/elke27_lib/handlers/zone.py:245, src/elke27_lib/handlers/zone.py:354 | read | none | open |
| `rssi` | elk-api/DealerAPI_UL_CHM-pdf.md:3380 | none in zone handler | missing | none | finding (S3) |
| `low_batt` | elk-api/DealerAPI_UL_CHM-pdf.md:3380 | src/elke27_lib/handlers/zone.py:1112 | read | none | open |
| `bypassed` | not documented | zone.py:1109 fallback | not documented | none | open |
| `low_battery` | not documented | zone.py:1112 fallback | not documented | none | open |
| `trouble` | not documented | zone.py:1115 | not documented | none | open |
| `tamper` | not documented | zone.py:1115 | not documented | none | open |
| `alarm` | not documented | zone.py:1115 | not documented | none | open |
| `violated` | not documented | zone.py:1115 | not documented | none | open |
| `enabled` | not documented | zone.py:1115 | not documented | none | open |
