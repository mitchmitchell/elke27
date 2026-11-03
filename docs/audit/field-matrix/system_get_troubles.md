# system.get_troubles field matrix

Draft for Architect row-by-row review (audit #99). Code @ main `21e5d66`. Doc: `grokbots/architecture/Elk/elk-api/DealerAPI_UL_CHM-pdf.md`. Code read sites are grep hits on the field name in `src/elke27_lib/handlers/system.py`; `none` means no handler reads it.

Doc :806-816 and :2356-2366 (response key can be get_trouble or get_troubles; handler routes both, system.py:62,104).

| doc field | doc location (file:line) | code read site | decision | test that proves it | status |
|---|---|---|---|---|---|
| `troubles` | elk-api/DealerAPI_UL_CHM-pdf.md:816 | src/elke27_lib/handlers/system.py:105 | read (list of strings) | test/test_handlers_system_extra.py | open |
| `error_code` | elk-api/DealerAPI_UL_CHM-pdf.md:816 | src/elke27_lib/handlers/system.py:67 | read: generic error_code path | none | open |
| `at` | elk-api/DealerAPI_UL_CHM-pdf.md:2362 | none | missing (per-area trouble bitmask) | none | finding (S3) |
