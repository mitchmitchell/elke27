# zone.get_all_zones_status field matrix

Draft for Architect row-by-row review (audit #99). Code @ main `21e5d66`. Doc: `grokbots/architecture/Elk/elk-api/DealerAPI_UL_CHM-pdf.md`. Code read sites are grep hits on the field name in `src/elke27_lib/handlers/zone.py`; `none` means no handler reads it.

Doc :3186-3216: one hex char per zone; table 0-F. Handler zone.py:1141 maps all 16 values (disabled/normal/trouble/violated/bypassed). Open-vs-EOL-vs-Short detail is kept in status_code only.

| doc field | doc location (file:line) | code read site | decision | test that proves it | status |
|---|---|---|---|---|---|
| `status` | elk-api/DealerAPI_UL_CHM-pdf.md:3192 | src/elke27_lib/handlers/zone.py:1036, :1141 | read (all 16 table values) | test/test_handlers_zone_extra.py | open (needs doc-shaped corpus test) |
