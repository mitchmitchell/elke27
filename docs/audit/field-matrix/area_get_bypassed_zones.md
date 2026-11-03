# area.get_bypassed_zones field matrix

Draft for Architect row-by-row review (audit #99). Code @ main `21e5d66`. Doc: `grokbots/architecture/Elk/elk-api/DealerAPI_UL_CHM-pdf.md`. Code read sites are grep hits on the field name in `src/elke27_lib/handlers/area.py`; `none` means no handler reads it.



| doc field | doc location (file:line) | code read site | decision | test that proves it | status |
|---|---|---|---|---|---|
| `area_id` | elk-api/DealerAPI_UL_CHM-pdf.md:120 | src/elke27_lib/handlers/area.py:262, src/elke27_lib/handlers/area.py:274, src/elke27_lib/handlers/area.py:363 | read | none | open |
| `zones` | elk-api/DealerAPI_UL_CHM-pdf.md:120 | none | missing | none | open |
| `error_code` | elk-api/DealerAPI_UL_CHM-pdf.md:120 | src/elke27_lib/handlers/area.py:103, src/elke27_lib/handlers/area.py:133, src/elke27_lib/handlers/area.py:326 | read: generic error_code path | none | open |
