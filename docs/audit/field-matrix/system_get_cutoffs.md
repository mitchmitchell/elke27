# system.get_cutoffs field matrix

Draft for Architect row-by-row review (audit #99). Code @ main `21e5d66`. Doc: `grokbots/architecture/Elk/elk-api/DealerAPI_UL_CHM-pdf.md`. Code read sites are grep hits on the field name in `src/elke27_lib/handlers/system.py`; `none` means no handler reads it.



| doc field | doc location (file:line) | code read site | decision | test that proves it | status |
|---|---|---|---|---|---|
| `ct_fire` | elk-api/DealerAPI_UL_CHM-pdf.md:2249 | none | missing | none | open |
| `ct_co` | elk-api/DealerAPI_UL_CHM-pdf.md:2249 | none | missing | none | open |
| `ct_burg` | elk-api/DealerAPI_UL_CHM-pdf.md:2249 | none | missing | none | open |
| `ct_emerg` | elk-api/DealerAPI_UL_CHM-pdf.md:2249 | none | missing | none | open |
| `ct_panic` | elk-api/DealerAPI_UL_CHM-pdf.md:2249 | none | missing | none | open |
| `ct_water` | elk-api/DealerAPI_UL_CHM-pdf.md:2249 | none | missing | none | open |
| `ct_temp` | elk-api/DealerAPI_UL_CHM-pdf.md:2249 | none | missing | none | open |
| `ct_security` | elk-api/DealerAPI_UL_CHM-pdf.md:2249 | none | missing | none | open |
| `ct_power` | elk-api/DealerAPI_UL_CHM-pdf.md:2249 | none | missing | none | open |
| `ct_automation` | elk-api/DealerAPI_UL_CHM-pdf.md:2249 | none | missing | none | open |
| `ct_local` | elk-api/DealerAPI_UL_CHM-pdf.md:2249 | none | missing | none | open |
| `error_code` | elk-api/DealerAPI_UL_CHM-pdf.md:2249 | src/elke27_lib/handlers/system.py:67 | read: generic error_code path | none | open |
