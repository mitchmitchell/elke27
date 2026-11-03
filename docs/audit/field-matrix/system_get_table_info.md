# system.get_table_info field matrix

Draft for Architect row-by-row review (audit #99). Code @ main `21e5d66`. Doc: `grokbots/architecture/Elk/elk-api/DealerAPI_UL_CHM-pdf.md`. Code read sites are grep hits on the field name in `src/elke27_lib/handlers/system.py`; `none` means no handler reads it.



| doc field | doc location (file:line) | code read site | decision | test that proves it | status |
|---|---|---|---|---|---|
| `table_csm` | elk-api/DealerAPI_UL_CHM-pdf.md:2350 | src/elke27_lib/handlers/system.py:216, src/elke27_lib/handlers/system.py:218 | read | none | open |
| `table_elements` | elk-api/DealerAPI_UL_CHM-pdf.md:2350 | none | missing | none | open |
| `tablesize` | elk-api/DealerAPI_UL_CHM-pdf.md:2350 | none | missing | none | open |
| `increment_size` | elk-api/DealerAPI_UL_CHM-pdf.md:2350 | none | missing | none | open |
| `element_size` | elk-api/DealerAPI_UL_CHM-pdf.md:2350 | none | missing | none | open |
| `error_code` | elk-api/DealerAPI_UL_CHM-pdf.md:2350 | src/elke27_lib/handlers/system.py:67 | read: generic error_code path | none | open |
