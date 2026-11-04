# system.get_trouble field matrix

Draft for Architect row-by-row review (audit #99). Code @ main `21e5d66`. Rows with decision `unreviewed` are not yet checked; their read sites are module-wide grep hints only.



| field | code read site | decision | test that proves it | status |
|---|---|---|---|---|
| `troubles` | src/elke27_lib/handlers/system.py:105 | read | test/test_handlers_system_extra.py | open |
| `at` | none | missing | none | finding (S3) |
| `error_code` | grep hint (module-wide, unconfirmed): src/elke27_lib/handlers/system.py:67 | unreviewed | none | open |
