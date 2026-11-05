# zone.set_status field matrix

Draft for Architect row-by-row review (audit #99). Code @ main `21e5d66`. Rows with decision `unreviewed` are not yet checked; their read sites are module-wide grep hints only.



| field | code read site | decision | test that proves it | status |
|---|---|---|---|---|
| `zone_id` | grep hint (module-wide, unconfirmed): src/elke27_lib/handlers/zone.py:258, src/elke27_lib/handlers/zone.py:265, src/elke27_lib/handlers/zone.py:278 | unreviewed | none | open |
| `error_code` | grep hint (module-wide, unconfirmed): src/elke27_lib/handlers/zone.py:116, src/elke27_lib/handlers/zone.py:245, src/elke27_lib/handlers/zone.py:354 | unreviewed | none | open |
