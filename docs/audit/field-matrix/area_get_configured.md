# area.get_configured field matrix

Draft for Architect row-by-row review (audit #99). Code @ main `21e5d66`. Doc: `grokbots/architecture/Elk/elk-api/DealerAPI_UL_CHM-pdf.md`. Code read sites are grep hits on the field name in `src/elke27_lib/handlers/area.py`; `none` means no handler reads it.



| doc field | doc location (file:line) | code read site | decision | test that proves it | status |
|---|---|---|---|---|---|
| `block_id` | elk-api/DealerAPI_UL_CHM-pdf.md:131 | src/elke27_lib/handlers/area.py:613, src/elke27_lib/handlers/area.py:614, src/elke27_lib/handlers/area.py:631 | read | none | open |
| `block_count` | elk-api/DealerAPI_UL_CHM-pdf.md:131 | src/elke27_lib/handlers/area.py:613, src/elke27_lib/handlers/area.py:615, src/elke27_lib/handlers/area.py:632 | read | none | open |
| `areas` | elk-api/DealerAPI_UL_CHM-pdf.md:131 | src/elke27_lib/handlers/area.py:714, src/elke27_lib/handlers/area.py:1240, src/elke27_lib/handlers/area.py:1275 | read | none | open |
| `error_code` | elk-api/DealerAPI_UL_CHM-pdf.md:131 | src/elke27_lib/handlers/area.py:103, src/elke27_lib/handlers/area.py:133, src/elke27_lib/handlers/area.py:326 | read: generic error_code path | none | open |
