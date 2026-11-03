# area.get_table_info field matrix

Draft for Architect row-by-row review (audit #99). Code @ main `21e5d66`. Rows with decision `unreviewed` are not yet checked; their read sites are module-wide grep hints only.



| field | code read site | decision | test that proves it | status |
|---|---|---|---|---|
| `table_csm` | grep hint (module-wide, unconfirmed): src/elke27_lib/handlers/area.py:1137, src/elke27_lib/handlers/area.py:1139 | unreviewed | none | open |
| `table_elements` | grep hint (module-wide, unconfirmed): src/elke27_lib/handlers/area.py:1001, src/elke27_lib/handlers/area.py:1163, src/elke27_lib/handlers/area.py:1210 | unreviewed | none | open |
| `tablesize` | none found by grep | unreviewed | none | open |
| `increment_size` | grep hint (module-wide, unconfirmed): src/elke27_lib/handlers/area.py:1063 | unreviewed | none | open |
| `element_size` | none found by grep | unreviewed | none | open |
| `error_code` | grep hint (module-wide, unconfirmed): src/elke27_lib/handlers/area.py:103, src/elke27_lib/handlers/area.py:133, src/elke27_lib/handlers/area.py:326 | unreviewed | none | open |
