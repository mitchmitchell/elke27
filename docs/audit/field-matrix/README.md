# Field-map audit matrices

One file per message type (`<group>_<command>.md`), audit parent #99. Columns per the design: doc field, doc location, code read site, decision (read / ignored: reason / missing / not documented), test that proves it, status. A row is `ok` only when a test feeds a doc-shaped or captured payload.

Generated rows come from `devtools`-style extraction of the Dealer API example replies (field names exact-case) and a grep of the handler module; hand-reviewed rows carry notes. Order of review: area, zone, system.
