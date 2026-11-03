# system.get_system_time field matrix

Draft for Architect row-by-row review (audit #99). Code @ main `21e5d66`. Doc: `grokbots/architecture/Elk/elk-api/DealerAPI_UL_CHM-pdf.md`. Code read sites are grep hits on the field name in `src/elke27_lib/handlers/system.py`; `none` means no handler reads it.



| doc field | doc location (file:line) | code read site | decision | test that proves it | status |
|---|---|---|---|---|---|
| `tz_offset` | elk-api/DealerAPI_UL_CHM-pdf.md:2178 | none | missing | none | open |
| `city_index` | elk-api/DealerAPI_UL_CHM-pdf.md:2178 | none | missing | none | open |
| `dst_active` | elk-api/DealerAPI_UL_CHM-pdf.md:2178 | none | missing | none | open |
| `gmt_seconds` | elk-api/DealerAPI_UL_CHM-pdf.md:2178 | none | missing | none | open |
| `uptime_seconds` | elk-api/DealerAPI_UL_CHM-pdf.md:2178 | none | missing | none | open |
| `BOOTED` | elk-api/DealerAPI_UL_CHM-pdf.md:2178 | none | missing | none | open |
| `LOCAL` | elk-api/DealerAPI_UL_CHM-pdf.md:2178 | none | missing | none | open |
| `error_code` | elk-api/DealerAPI_UL_CHM-pdf.md:2178 | src/elke27_lib/handlers/system.py:67 | read: generic error_code path | none | open |
