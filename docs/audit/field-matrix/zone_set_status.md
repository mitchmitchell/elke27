# zone.set_status field matrix

Draft for Architect row-by-row review (audit #99). Code @ main `21e5d66`. Doc: `grokbots/architecture/Elk/elk-api/DealerAPI_UL_CHM-pdf.md`. Code read sites are grep hits on the field name in `src/elke27_lib/handlers/zone.py`; `none` means no handler reads it.



| doc field | doc location (file:line) | code read site | decision | test that proves it | status |
|---|---|---|---|---|---|
| `zone_id` | elk-api/DealerAPI_UL_CHM-pdf.md:3442 | src/elke27_lib/handlers/zone.py:258, src/elke27_lib/handlers/zone.py:265, src/elke27_lib/handlers/zone.py:278 | read | none | open |
| `error_code` | elk-api/DealerAPI_UL_CHM-pdf.md:3442 | src/elke27_lib/handlers/zone.py:116, src/elke27_lib/handlers/zone.py:245, src/elke27_lib/handlers/zone.py:354 | read: generic error_code path | none | open |
