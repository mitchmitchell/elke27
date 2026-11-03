# zone.realloc field matrix

Draft for Architect row-by-row review (audit #99). Code @ main `21e5d66`. Doc: `grokbots/architecture/Elk/elk-api/DealerAPI_UL_CHM-pdf.md`. Code read sites are grep hits on the field name in `src/elke27_lib/handlers/zone.py`; `none` means no handler reads it.



| doc field | doc location (file:line) | code read site | decision | test that proves it | status |
|---|---|---|---|---|---|
| `table_csm` | elk-api/DealerAPI_UL_CHM-pdf.md:3415 | src/elke27_lib/handlers/zone.py:709, src/elke27_lib/handlers/zone.py:711 | read | none | open |
| `table_elements` | elk-api/DealerAPI_UL_CHM-pdf.md:3415 | src/elke27_lib/handlers/zone.py:605, src/elke27_lib/handlers/zone.py:874 | read | none | open |
| `tablesize` | elk-api/DealerAPI_UL_CHM-pdf.md:3415 | none | missing | none | open |
| `increment_size` | elk-api/DealerAPI_UL_CHM-pdf.md:3415 | src/elke27_lib/handlers/zone.py:667 | read | none | open |
| `element_size` | elk-api/DealerAPI_UL_CHM-pdf.md:3415 | none | missing | none | open |
| `error_code` | elk-api/DealerAPI_UL_CHM-pdf.md:3415 | src/elke27_lib/handlers/zone.py:116, src/elke27_lib/handlers/zone.py:245, src/elke27_lib/handlers/zone.py:354 | read: generic error_code path | none | open |
