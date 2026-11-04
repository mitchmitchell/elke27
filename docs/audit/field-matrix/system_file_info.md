# system.file_info field matrix

Draft for Architect row-by-row review (audit #99). Code @ main `21e5d66`. Rows with decision `unreviewed` are not yet checked; their read sites are module-wide grep hints only.



| field | code read site | decision | test that proves it | status |
|---|---|---|---|---|
| `file_list` | none found by grep | unreviewed | none | open |
| `TotalSize` | none found by grep | unreviewed | none | open |
| `error_code` | grep hint (module-wide, unconfirmed): src/elke27_lib/handlers/system.py:67 | unreviewed | none | open |
| `file_num` | none found by grep | unreviewed | none | open |
| `file_count` | none found by grep | unreviewed | none | open |
| `name` | grep hint (module-wide, unconfirmed): src/elke27_lib/handlers/system.py:240 | unreviewed | none | open |
| `file_size` | none found by grep | unreviewed | none | open |
