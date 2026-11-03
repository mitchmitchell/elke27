# area.get_status field matrix

Draft for Architect row-by-row review (audit #99). Code @ main `21e5d66`. Doc: `grokbots/architecture/Elk/elk-api/DealerAPI_UL_CHM-pdf.md`. Code read sites are grep hits on the field name in `src/elke27_lib/handlers/area.py`; `none` means no handler reads it.

Prose field lists: arm_state values :146-152, arm_cmd_state :153-158, alarms :159-170, alrm_snd (prose calls it `alrm_sound`) :171-183, troubles :184-195, ready_status :196-199, ee_timer note :200. Open PRs that change rows: #94, #98, #101.

| doc field | doc location (file:line) | code read site | decision | test that proves it | status |
|---|---|---|---|---|---|
| `area_id` | elk-api/DealerAPI_UL_CHM-pdf.md:205 | src/elke27_lib/handlers/area.py:262, src/elke27_lib/handlers/area.py:274, src/elke27_lib/handlers/area.py:363 | read (routing key) | none | open |
| `arm_state` | elk-api/DealerAPI_UL_CHM-pdf.md:205 | src/elke27_lib/handlers/area.py:112; client.py:993 (_arm_mode_from_string) | read; values ARMED_VACATION and ALARM_MEM unmapped on main | #101 test/test_area_arm_state_doc_values.py (doc payload) | finding #100 (S1), fix in #101 |
| `arm_cmd_state` | elk-api/DealerAPI_UL_CHM-pdf.md:205 | src/elke27_lib/handlers/area.py:113; client.py arm_cmd_mode | read; same mapping as arm_state | test/test_area_exit_delay_state.py (assumed shape) | finding #100 (S1), fix in #101 |
| `ready_status` | elk-api/DealerAPI_UL_CHM-pdf.md:205 | src/elke27_lib/handlers/area.py:117 | read | test/test_area_exit_delay_state.py | open (needs doc-shaped corpus test) |
| `ee_timer` | elk-api/DealerAPI_UL_CHM-pdf.md:205 | src/elke27_lib/handlers/area.py:131 | read (entry/exit per :200) | test/test_area_exit_delay_state.py; #94 | open (#94) |
| `Chime` | elk-api/DealerAPI_UL_CHM-pdf.md:205 | src/elke27_lib/handlers/area.py:124 | read (also invented lowercase `chime`) | none doc-shaped | open |
| `alarms` | elk-api/DealerAPI_UL_CHM-pdf.md:205 | none on main (#94, #98 add it) | missing on main | #98 test/test_area_alarm_triggered.py | finding #92 (S1), fix in #98 |
| `alarm_mem` | elk-api/DealerAPI_UL_CHM-pdf.md:205 | none on main (#101 adds it) | missing on main; #101 exposes AreaState.alarm_memory | #101 test_alarm_mem_field_sets_alarm_memory | finding (S2), fix in #101 |
| `alrm_snd` | elk-api/DealerAPI_UL_CHM-pdf.md:205 | none on main (#94, #98 add it) | missing on main | #98 test/test_area_alarm_triggered.py | finding #92 (S1), fix in #98 |
| `troubles` | elk-api/DealerAPI_UL_CHM-pdf.md:205 | none in get_status (handler reads invented bool `trouble`, area.py:127) | missing | none | finding (S2), see issue |
| `alarm_zone` | elk-api/DealerAPI_UL_CHM-pdf.md:205 | src/elke27_lib/handlers/area.py:118 | read | test/test_area_exit_delay_state.py; #94 | open |
| `zones_bypassed` | elk-api/DealerAPI_UL_CHM-pdf.md:205 | src/elke27_lib/handlers/area.py:130 -> num_bypassed_zones | read | none doc-shaped | open |
| `xzn_time` | elk-api/DealerAPI_UL_CHM-pdf.md:205 | none | missing | none | finding (S3) |
| `xzn_id` | elk-api/DealerAPI_UL_CHM-pdf.md:205 | none | missing | none | finding (S3) |
| `auto_arm_timer` | elk-api/DealerAPI_UL_CHM-pdf.md:205 | none | missing | none | finding (S3) |
| `chime_count` | elk-api/DealerAPI_UL_CHM-pdf.md:205 | none | missing | none | finding (S3) |
| `error_code` | elk-api/DealerAPI_UL_CHM-pdf.md:205 | src/elke27_lib/handlers/area.py:133 -> last_error_code | read | none | open |
| `alarm_state` | not documented | area.py:115; client.py alarm_active | not documented; drives alarm_active on main | test/test_e27_area_get_status.py:37 (assumed fixture) | finding #92; assumed fixture (S2) |
| `alarm_event` | not documented | area.py | not documented | none | open (needs capture or RE) |
| `armed_state` | not documented | area.py; client.py fallback for arm_state | not documented | none | open (needs capture or RE) |
| `ready` | not documented | area.py | not documented | none | open |
| `stay` | not documented | area.py | not documented | none | open |
| `away` | not documented | area.py | not documented | none | open |
| `bypass` | not documented | area.py | not documented | none | open |
| `chime` | not documented | area.py | not documented (doc is `Chime`) | none | open |
| `trouble` | not documented | area.py:127 | not documented (doc is string `troubles`) | none | finding (S2), see issue |
| `num_not_ready_zones` | not documented | area.py | not documented here (doc: area.get_num_not_rdy_zones `not_rdy_zones`) | none | open |
| `num_bypassed_zones` | not documented | area.py | not documented | none | open |
| `entry_delay_active` | not documented | area.py | not documented (#94 removes) | none | open (#94) |
| `exit_delay_active` | not documented | area.py | not documented (#94 removes) | none | open (#94) |
