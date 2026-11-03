# area.get_table_info field matrix

Draft for Architect row-by-row review (audit #99). Code @ main `21e5d66`. Doc: `grokbots/architecture/Elk/elk-api/DealerAPI_UL_CHM-pdf.md`. Code read sites are grep hits on the field name in `src/elke27_lib/handlers/area.py`; `none` means no handler reads it.



| doc field | doc location (file:line) | code read site | decision | test that proves it | status |
|---|---|---|---|---|---|
| `table_csm` | elk-api/DealerAPI_UL_CHM-pdf.md:244 | src/elke27_lib/handlers/area.py:1137, src/elke27_lib/handlers/area.py:1139 | read | none | open |
| `table_elements` | elk-api/DealerAPI_UL_CHM-pdf.md:244 | src/elke27_lib/handlers/area.py:1001, src/elke27_lib/handlers/area.py:1163, src/elke27_lib/handlers/area.py:1210 | read | none | open |
| `tablesize` | elk-api/DealerAPI_UL_CHM-pdf.md:244 | none | missing | none | open |
| `increment_size` | elk-api/DealerAPI_UL_CHM-pdf.md:244 | src/elke27_lib/handlers/area.py:1063 | read | none | open |
| `element_size` | elk-api/DealerAPI_UL_CHM-pdf.md:244 | none | missing | none | open |
| `error_code` | elk-api/DealerAPI_UL_CHM-pdf.md:244 | src/elke27_lib/handlers/area.py:103, src/elke27_lib/handlers/area.py:133, src/elke27_lib/handlers/area.py:326 | read: generic error_code path | none | open |
