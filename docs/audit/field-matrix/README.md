# Field-map audit matrices

One file per message type (`<group>_<command>.md`), audit parent #99. Columns per the design: field, code read site, decision (read / ignored: reason / missing / not documented), test that proves it, status. A row is `ok` only when a test feeds a doc-shaped or captured payload.

Field names are exact-case. Rows not yet hand-reviewed are marked `unreviewed`, with module-wide grep hints only. Doc locations are kept in private notes, not in this repo. Order of review: area, zone, system.
