# system.file_info field matrix

Draft for Architect row-by-row review (audit #99). Code @ main `21e5d66`. Doc: `grokbots/architecture/Elk/elk-api/DealerAPI_UL_CHM-pdf.md`. Code read sites are grep hits on the field name in `src/elke27_lib/handlers/system.py`; `none` means no handler reads it.



| doc field | doc location (file:line) | code read site | decision | test that proves it | status |
|---|---|---|---|---|---|
| `file_list` | elk-api/DealerAPI_UL_CHM-pdf.md:2215 | none | missing | none | open |
| `TotalSize` | elk-api/DealerAPI_UL_CHM-pdf.md:2215 | none | missing | none | open |
| `error_code` | elk-api/DealerAPI_UL_CHM-pdf.md:2215 | src/elke27_lib/handlers/system.py:67 | read: generic error_code path | none | open |
| `file_num` | elk-api/DealerAPI_UL_CHM-pdf.md:2223 | none | missing | none | open |
| `file_count` | elk-api/DealerAPI_UL_CHM-pdf.md:2223 | none | missing | none | open |
| `name` | elk-api/DealerAPI_UL_CHM-pdf.md:2223 | src/elke27_lib/handlers/system.py:240 | read | none | open |
| `file_size` | elk-api/DealerAPI_UL_CHM-pdf.md:2223 | none | missing | none | open |
