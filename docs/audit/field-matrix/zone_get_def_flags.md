# zone.get_def_flags field matrix

Draft for Architect row-by-row review (audit #99). Code @ main `21e5d66`. Doc: `grokbots/architecture/Elk/elk-api/DealerAPI_UL_CHM-pdf.md`. Code read sites are grep hits on the field name in `src/elke27_lib/handlers/zone.py`; `none` means no handler reads it.



| doc field | doc location (file:line) | code read site | decision | test that proves it | status |
|---|---|---|---|---|---|
| `definition` | elk-api/DealerAPI_UL_CHM-pdf.md:3261 | src/elke27_lib/handlers/zone.py:778, src/elke27_lib/handlers/zone.py:835, src/elke27_lib/handlers/zone.py:840 | read | none | open |
| `flags` | elk-api/DealerAPI_UL_CHM-pdf.md:3261 | src/elke27_lib/handlers/zone.py:836, src/elke27_lib/handlers/zone.py:840, src/elke27_lib/handlers/zone.py:1237 | read | none | open |
| `error_code` | elk-api/DealerAPI_UL_CHM-pdf.md:3261 | src/elke27_lib/handlers/zone.py:116, src/elke27_lib/handlers/zone.py:245, src/elke27_lib/handlers/zone.py:354 | read: generic error_code path | none | open |
