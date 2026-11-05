# system.get_troubles field matrix

Draft for Architect row-by-row review (audit #99). Code @ main `21e5d66`. Rows with decision `unreviewed` are not yet checked; their read sites are module-wide grep hints only.

Response key can be get_trouble or get_troubles; handler routes both (system.py:62,104).

| field | code read site | decision | test that proves it | status |
|---|---|---|---|---|
| `troubles` | src/elke27_lib/handlers/system.py:105 | read (list of strings) | test/test_handlers_system_extra.py | open |
| `error_code` | grep hint (module-wide, unconfirmed): src/elke27_lib/handlers/system.py:67 | unreviewed | none | open |
| `at` | none | missing (per-area trouble bitmask) | none | finding (S3) |
