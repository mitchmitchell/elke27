# zone.get_all_zones_status field matrix

Draft for Architect row-by-row review (audit #99). Code @ main `21e5d66`. Rows with decision `unreviewed` are not yet checked; their read sites are module-wide grep hints only.

One hex char per zone, table values 0-F. Handler zone.py:1141 maps all 16 values; Open/EOL/Short detail is kept in status_code only.

| field | code read site | decision | test that proves it | status |
|---|---|---|---|---|
| `status` | src/elke27_lib/handlers/zone.py:1036, :1141 | read (all 16 table values) | test/test_handlers_zone_extra.py | open (needs doc-shaped corpus test) |
