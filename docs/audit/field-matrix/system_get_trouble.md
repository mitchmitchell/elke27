# system.get_trouble field matrix

Draft for Architect row-by-row review (audit #99). Code @ main `21e5d66`. Doc: `grokbots/architecture/Elk/elk-api/DealerAPI_UL_CHM-pdf.md`. Code read sites are grep hits on the field name in `src/elke27_lib/handlers/system.py`; `none` means no handler reads it.



| doc field | doc location (file:line) | code read site | decision | test that proves it | status |
|---|---|---|---|---|---|
| `troubles` | elk-api/DealerAPI_UL_CHM-pdf.md:2364 | src/elke27_lib/handlers/system.py:105 | read | test/test_handlers_system_extra.py | open |
| `at` | elk-api/DealerAPI_UL_CHM-pdf.md:2364 | none | missing | none | finding (S3) |
| `error_code` | elk-api/DealerAPI_UL_CHM-pdf.md:2364 | src/elke27_lib/handlers/system.py:67 | read: generic error_code path | none | open |
