# zone.get_attribs field matrix

Draft for Architect row-by-row review (audit #99). Code @ main `21e5d66`. Doc: `grokbots/architecture/Elk/elk-api/DealerAPI_UL_CHM-pdf.md`. Code read sites are grep hits on the field name in `src/elke27_lib/handlers/zone.py`; `none` means no handler reads it.



| doc field | doc location (file:line) | code read site | decision | test that proves it | status |
|---|---|---|---|---|---|
| `zone_id` | elk-api/DealerAPI_UL_CHM-pdf.md:3224 | src/elke27_lib/handlers/zone.py:258, src/elke27_lib/handlers/zone.py:265, src/elke27_lib/handlers/zone.py:278 | read | none | open |
| `name` | elk-api/DealerAPI_UL_CHM-pdf.md:3224 | src/elke27_lib/handlers/zone.py:70, src/elke27_lib/handlers/zone.py:84, src/elke27_lib/handlers/zone.py:170 | read | none | open |
| `area_id` | elk-api/DealerAPI_UL_CHM-pdf.md:3224 | src/elke27_lib/handlers/zone.py:71, src/elke27_lib/handlers/zone.py:85, src/elke27_lib/handlers/zone.py:1235 | read | none | open |
| `definition` | elk-api/DealerAPI_UL_CHM-pdf.md:3224 | src/elke27_lib/handlers/zone.py:778, src/elke27_lib/handlers/zone.py:835, src/elke27_lib/handlers/zone.py:840 | read | none | open |
| `flags` | elk-api/DealerAPI_UL_CHM-pdf.md:3224 | src/elke27_lib/handlers/zone.py:836, src/elke27_lib/handlers/zone.py:840, src/elke27_lib/handlers/zone.py:1237 | read | none | open |
| `error_code` | elk-api/DealerAPI_UL_CHM-pdf.md:3224 | src/elke27_lib/handlers/zone.py:116, src/elke27_lib/handlers/zone.py:245, src/elke27_lib/handlers/zone.py:354 | read: generic error_code path | none | open |
