# system.get_attribs field matrix

Draft for Architect row-by-row review (audit #99). Code @ main `21e5d66`. Doc: `grokbots/architecture/Elk/elk-api/DealerAPI_UL_CHM-pdf.md`. Code read sites are grep hits on the field name in `src/elke27_lib/handlers/system.py`; `none` means no handler reads it.



| doc field | doc location (file:line) | code read site | decision | test that proves it | status |
|---|---|---|---|---|---|
| `name` | elk-api/DealerAPI_UL_CHM-pdf.md:2232 | src/elke27_lib/handlers/system.py:240 | read | none | open |
| `RO_sysid` | elk-api/DealerAPI_UL_CHM-pdf.md:2232 | none | missing | none | open |
| `long` | elk-api/DealerAPI_UL_CHM-pdf.md:2232 | none | missing | none | open |
| `lat` | elk-api/DealerAPI_UL_CHM-pdf.md:2232 | none | missing | none | open |
| `tz_offset` | elk-api/DealerAPI_UL_CHM-pdf.md:2232 | none | missing | none | open |
| `cross_zn_tm` | elk-api/DealerAPI_UL_CHM-pdf.md:2232 | none | missing | none | open |
| `ac_fail_dly_tm` | elk-api/DealerAPI_UL_CHM-pdf.md:2232 | none | missing | none | open |
| `eth_fail_dly_tm` | elk-api/DealerAPI_UL_CHM-pdf.md:2232 | none | missing | none | open |
| `pots_fail_dly_tm` | elk-api/DealerAPI_UL_CHM-pdf.md:2232 | none | missing | none | open |
| `Fire Supervision Time` | elk-api/DealerAPI_UL_CHM-pdf.md:2232 | none | missing | none | open |
| `BurgSupervision Time` | elk-api/DealerAPI_UL_CHM-pdf.md:2232 | none | missing | none | open |
| `cloud_pw` | elk-api/DealerAPI_UL_CHM-pdf.md:2232 | none | missing | none | open |
| `cloud_url` | elk-api/DealerAPI_UL_CHM-pdf.md:2232 | none | missing | none | open |
| `flags` | elk-api/DealerAPI_UL_CHM-pdf.md:2232 | none | missing | none | open |
| `error_code` | elk-api/DealerAPI_UL_CHM-pdf.md:2232 | src/elke27_lib/handlers/system.py:67 | read: generic error_code path | none | open |
| `Burg Supervision Time` | elk-api/DealerAPI_UL_CHM-pdf.md:8829 | none | missing | none | open |
