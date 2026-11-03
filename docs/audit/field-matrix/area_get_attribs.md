# area.get_attribs field matrix

Draft for Architect row-by-row review (audit #99). Code @ main `21e5d66`. Doc: `grokbots/architecture/Elk/elk-api/DealerAPI_UL_CHM-pdf.md`. Code read sites are grep hits on the field name in `src/elke27_lib/handlers/area.py`; `none` means no handler reads it.



| doc field | doc location (file:line) | code read site | decision | test that proves it | status |
|---|---|---|---|---|---|
| `area_id` | elk-api/DealerAPI_UL_CHM-pdf.md:107 | src/elke27_lib/handlers/area.py:262, src/elke27_lib/handlers/area.py:274, src/elke27_lib/handlers/area.py:363 | read | none | open |
| `entry1_time` | elk-api/DealerAPI_UL_CHM-pdf.md:107 | none | missing | none | open |
| `ext_entry_time` | elk-api/DealerAPI_UL_CHM-pdf.md:107 | none | missing | none | open |
| `exit_time` | elk-api/DealerAPI_UL_CHM-pdf.md:107 | none | missing | none | open |
| `name` | elk-api/DealerAPI_UL_CHM-pdf.md:107 | src/elke27_lib/handlers/area.py:653, src/elke27_lib/handlers/area.py:1386, src/elke27_lib/handlers/area.py:1387 | read | none | open |
| `kp_single_key_arm` | elk-api/DealerAPI_UL_CHM-pdf.md:107 | none | missing | none | open |
| `sounder` | elk-api/DealerAPI_UL_CHM-pdf.md:107 | none | missing | none | open |
| `auto_arm_time` | elk-api/DealerAPI_UL_CHM-pdf.md:107 | none | missing | none | open |
| `auto_arm_level` | elk-api/DealerAPI_UL_CHM-pdf.md:107 | none | missing | none | open |
| `aa_warn_mins` | elk-api/DealerAPI_UL_CHM-pdf.md:107 | none | missing | none | open |
| `flags` | elk-api/DealerAPI_UL_CHM-pdf.md:107 | none | missing | none | open |
| `error_code` | elk-api/DealerAPI_UL_CHM-pdf.md:107 | src/elke27_lib/handlers/area.py:103, src/elke27_lib/handlers/area.py:133, src/elke27_lib/handlers/area.py:326 | read: generic error_code path | none | open |
