# area.get_status field matrix

Draft for Architect row-by-row review (audit #99). Code @ main `21e5d66`. Rows with decision `unreviewed` are not yet checked; their read sites are module-wide grep hints only.

Open PRs that change rows: #94, #98, #101.

| field | code read site | decision | test that proves it | status |
|---|---|---|---|---|
| `area_id` | none | read (routing key) | none | open |
| `arm_state` | src/elke27_lib/handlers/area.py:112; client.py:993 (_arm_mode_from_string) | read; values ARMED_VACATION and ALARM_MEM unmapped on main | #101 test/test_area_arm_state_doc_values.py (doc payload) | finding #100 (S1), fix in #101 |
| `arm_cmd_state` | src/elke27_lib/handlers/area.py:113; client.py arm_cmd_mode | read; same mapping as arm_state | test/test_area_exit_delay_state.py (assumed shape) | finding #100 (S1), fix in #101 |
| `ready_status` | src/elke27_lib/handlers/area.py:117 | read | test/test_area_exit_delay_state.py | open (needs doc-shaped corpus test) |
| `ee_timer` | src/elke27_lib/handlers/area.py:131 | read (exit or entry timer per alarm_zone) | test/test_area_exit_delay_state.py; #94 | open (#94) |
| `Chime` | src/elke27_lib/handlers/area.py:124 | read (also invented lowercase `chime`) | none doc-shaped | open |
| `alarms` | none on main (#94, #98 add it) | missing on main | #98 test/test_area_alarm_triggered.py | finding #92 (S1), fix in #98 |
| `alarm_mem` | none on main (#101 adds it) | missing on main; #101 exposes AreaState.alarm_memory | #101 test_alarm_mem_field_sets_alarm_memory | finding #103 (S2), fix in #101 |
| `alrm_snd` | none on main (#94, #98 add it) | missing on main | #98 test/test_area_alarm_triggered.py | finding #92 (S1), fix in #98 |
| `troubles` | none in get_status (handler reads invented bool `trouble`, area.py:127) | missing | none | finding #102 (S2) |
| `alarm_zone` | src/elke27_lib/handlers/area.py:118 | read | test/test_area_exit_delay_state.py; #94 | open |
| `zones_bypassed` | src/elke27_lib/handlers/area.py:130 -> num_bypassed_zones | read | none doc-shaped | open |
| `xzn_time` | none | missing | none | finding (S3) |
| `xzn_id` | none | missing | none | finding (S3) |
| `auto_arm_timer` | none | missing | none | finding (S3) |
| `chime_count` | none | missing | none | finding (S3) |
| `error_code` | src/elke27_lib/handlers/area.py:133 -> last_error_code | read | none | open |
| `alarm_state` | area.py:115; client.py alarm_active | not documented; drives alarm_active on main | test/test_e27_area_get_status.py:37 (assumed fixture) | finding #92; assumed fixture #104 (S2) |
| `alarm_event` | area.py | not documented | none | open (needs capture or RE) |
| `armed_state` | area.py; client.py fallback for arm_state | not documented | none | open (needs capture or RE) |
| `ready` | area.py | not documented | none | open |
| `stay` | area.py | not documented | none | open |
| `away` | area.py | not documented | none | open |
| `bypass` | area.py | not documented | none | open |
| `chime` | area.py | not documented (doc is `Chime`) | none | open |
| `trouble` | area.py:127 | not documented (doc is string `troubles`) | none | finding #102 (S2) |
| `num_not_ready_zones` | area.py | not documented here (doc: area.get_num_not_rdy_zones `not_rdy_zones`) | none | open |
| `num_bypassed_zones` | area.py | not documented | none | open |
| `entry_delay_active` | area.py | not documented (#94 removes) | none | open (#94) |
| `exit_delay_active` | area.py | not documented (#94 removes) | none | open (#94) |
