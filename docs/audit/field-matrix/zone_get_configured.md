# zone.get_configured field matrix

Draft for Architect row-by-row review (audit #99). Code @ main `21e5d66`. Doc: `grokbots/architecture/Elk/elk-api/DealerAPI_UL_CHM-pdf.md`. Code read sites are grep hits on the field name in `src/elke27_lib/handlers/zone.py`; `none` means no handler reads it.



| doc field | doc location (file:line) | code read site | decision | test that proves it | status |
|---|---|---|---|---|---|
| `block_id` | elk-api/DealerAPI_UL_CHM-pdf.md:3250 | src/elke27_lib/handlers/zone.py:765, src/elke27_lib/handlers/zone.py:911 | read | none | open |
| `block_count` | elk-api/DealerAPI_UL_CHM-pdf.md:3250 | src/elke27_lib/handlers/zone.py:226, src/elke27_lib/handlers/zone.py:893, src/elke27_lib/handlers/zone.py:912 | read | none | open |
| `zones` | elk-api/DealerAPI_UL_CHM-pdf.md:3250 | src/elke27_lib/handlers/zone.py:226, src/elke27_lib/handlers/zone.py:915, src/elke27_lib/handlers/zone.py:942 | read | none | open |
| `error_code` | elk-api/DealerAPI_UL_CHM-pdf.md:3250 | src/elke27_lib/handlers/zone.py:116, src/elke27_lib/handlers/zone.py:245, src/elke27_lib/handlers/zone.py:354 | read: generic error_code path | none | open |
