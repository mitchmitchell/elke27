# zone.get_table_info field matrix

Draft for Architect row-by-row review (audit #99). Code @ main `21e5d66`. Rows with decision `unreviewed` are not yet checked; their read sites are module-wide grep hints only.



| field | code read site | decision | test that proves it | status |
|---|---|---|---|---|
| `table_csm` | grep hint (module-wide, unconfirmed): src/elke27_lib/handlers/zone.py:709, src/elke27_lib/handlers/zone.py:711 | unreviewed | none | open |
| `table_elements` | grep hint (module-wide, unconfirmed): src/elke27_lib/handlers/zone.py:605, src/elke27_lib/handlers/zone.py:874 | unreviewed | none | open |
| `tablesize` | none found by grep | unreviewed | none | open |
| `increment_size` | grep hint (module-wide, unconfirmed): src/elke27_lib/handlers/zone.py:667 | unreviewed | none | open |
| `element_size` | none found by grep | unreviewed | none | open |
| `error_code` | grep hint (module-wide, unconfirmed): src/elke27_lib/handlers/zone.py:116, src/elke27_lib/handlers/zone.py:245, src/elke27_lib/handlers/zone.py:354 | unreviewed | none | open |
