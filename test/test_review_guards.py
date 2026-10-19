"""Guards for review findings that kept coming back.

Each test here turns a finding that Architect or Claude raised on several PRs
into a check, so CI catches it before review does:

- tests reaching into private library members (also ruff SLF001, see pyproject);
- helper code imported from another test module;
- strict xfails without ``raises=`` or a linked issue;
- docstrings that promise retry/resend behaviour without a test pinning it;
- ``getattr``/``hasattr`` with a literal name instead of a typed member;
- new ``noqa`` escapes for SLF001/BLE001 (ruff PGH004 also bans a bare noqa).

Legacy code is listed explicitly. The lists may only shrink: when you fix a
file, remove it from the list (the stale-entry checks fail until you do).
"""

from __future__ import annotations

import ast
import re
import tokenize
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src" / "elke27_lib"
TEST = ROOT / "test"
THIS = Path(__file__).resolve()
PRIVATE_HELPERS = {"get_private", "set_private", "get_kernel"}
REFLECTION = {"getattr", "setattr", "hasattr", "delattr"}


def _files(base: Path) -> list[Path]:
    return sorted(base.rglob("*.py"))


def _rel(path: Path) -> str:
    return path.resolve().relative_to(ROOT).as_posix()


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _is_private(name: str) -> bool:
    return name.startswith("_") and not (name.startswith("__") and name.endswith("__"))


def _literal_name(call: ast.Call) -> str | None:
    if len(call.args) >= 2:
        arg = call.args[1]
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            return arg.value
    return None


def _call_name(call: ast.Call) -> str | None:
    func = call.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


# --- private access from tests ------------------------------------------------


def _slf001_legacy_files() -> set[str]:
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    ignores: dict[str, list[str]] = config["tool"]["ruff"]["lint"]["per-file-ignores"]
    return {path for path, codes in ignores.items() if "SLF001" in codes and "*" not in path}


def _private_access(path: Path) -> list[str]:
    """Private library access ruff SLF001 cannot see (helpers, imports, reflection)."""
    hits: list[str] = []
    for node in ast.walk(_tree(path)):
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("elke27_lib"):
            hits += [f"import {a.name}" for a in node.names if _is_private(a.name)]
        elif isinstance(node, ast.Call):
            name = _call_name(node)
            if name in PRIVATE_HELPERS:
                hits.append(f"{name}()")
            elif name in REFLECTION:
                literal = _literal_name(node)
                if literal is not None and _is_private(literal):
                    hits.append(f"{name}(..., {literal!r})")
    return hits


def _private_attribute_access(path: Path) -> bool:
    """Rough SLF001: obj._name where obj is not self/cls."""
    for node in ast.walk(_tree(path)):
        if isinstance(node, ast.Attribute) and _is_private(node.attr):
            base = node.value
            if not (isinstance(base, ast.Name) and base.id in {"self", "cls"}):
                return True
    return False


def _test_modules() -> list[Path]:
    return [
        p
        for p in _files(TEST)
        if p.resolve() != THIS and "helpers" not in p.relative_to(TEST).parts
    ]


def test_private_access_only_in_legacy_test_files() -> None:
    """New tests drive the public API; private access stays in the SLF001 legacy list."""
    legacy = _slf001_legacy_files()
    offenders = {
        _rel(p): hits
        for p in _test_modules()
        if (hits := _private_access(p)) and _rel(p) not in legacy
    }
    assert offenders == {}, (
        "Tests must use the public API (repeat review finding). Drive the client "
        "through its public calls with only the transport faked."
    )


# Number of legacy test files in SLF001 per-file-ignores. Lower it when you remove
# one; it never goes up (new tests use the public API).
SLF001_LEGACY_FILE_COUNT = 77


def test_slf001_legacy_list_does_not_grow() -> None:
    """The SLF001 per-file-ignores list only shrinks."""
    assert len(_slf001_legacy_files()) == SLF001_LEGACY_FILE_COUNT, (
        "Do not add test files to the SLF001 per-file-ignores; use the public API. "
        "If you removed one, lower SLF001_LEGACY_FILE_COUNT."
    )


def _helper_modules() -> list[Path]:
    return _files(TEST / "helpers")


# Helper modules (exempt from SLF001 via test/helpers/*) that touch private members.
# New helpers use the public API. Remove an entry when its module is clean.
LEGACY_PRIVATE_HELPERS = {"test/helpers/internal.py"}


def test_private_access_in_helpers_only_in_legacy_modules() -> None:
    """test/helpers/* is exempt from SLF001, so new helper modules are checked here."""
    found = {
        _rel(p) for p in _helper_modules() if _private_access(p) or _private_attribute_access(p)
    }
    assert found - LEGACY_PRIVATE_HELPERS == set(), (
        "New test helpers must use the public API, not private members."
    )
    assert LEGACY_PRIVATE_HELPERS - found == set(), "Drop clean LEGACY_PRIVATE_HELPERS entries"


def test_slf001_legacy_list_has_no_stale_entries() -> None:
    """Once a legacy file is clean, it leaves the per-file-ignores list."""
    stale = sorted(
        path
        for path in _slf001_legacy_files()
        if path.startswith("test/")
        and not (
            (ROOT / path).exists()
            and (_private_access(ROOT / path) or _private_attribute_access(ROOT / path))
        )
    )
    assert stale == [], "Remove these from SLF001 per-file-ignores in pyproject.toml"


# --- helpers imported from other test modules -----------------------------------

# (importer, imported test module). Move these to test/helpers/ and drop the entry.
LEGACY_TEST_MODULE_IMPORTS = {
    ("test/test_barrier_commands.py", "test.test_transport_command_retry"),
    ("test/test_command_outcome_unknown.py", "test.test_transport_command_retry"),
    ("test/test_raw_passthrough.py", "test.test_transport_command_retry"),
    ("test/test_raw_passthrough.py", "test.test_session_extra"),
    ("test/test_snapshot_after_arm_bypass.py", "test.test_panel_errors_ready_night"),
}
_TEST_PACKAGES = {"", "test", "tests"}


def _imported_test_modules(path: Path) -> set[str]:
    """Every test module imported, in any form: import x.test_y, import test_y,
    from x.test_y import z, from test import test_y, from . import test_y."""
    found: set[str] = set()
    for node in ast.walk(_tree(path)):
        if isinstance(node, ast.Import):
            found |= {a.name for a in node.names if a.name.split(".")[-1].startswith("test_")}
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module.split(".")[-1].startswith("test_"):
                found.add(module)
            elif node.level or module in _TEST_PACKAGES:
                prefix = f"{module}." if module else "." * node.level
                found |= {f"{prefix}{a.name}" for a in node.names if a.name.startswith("test_")}
    return found


def test_no_new_helper_imports_between_test_modules() -> None:
    """Shared fakes live in test/helpers/, not in another test module."""
    found = {
        (_rel(path), module)
        for path in [*_test_modules(), *_helper_modules()]
        for module in _imported_test_modules(path)
    }
    assert found - LEGACY_TEST_MODULE_IMPORTS == set(), "Move shared fakes to test/helpers/"
    assert LEGACY_TEST_MODULE_IMPORTS - found == set(), "Drop fixed LEGACY_TEST_MODULE_IMPORTS"


# --- xfail pairing ---------------------------------------------------------------

_ISSUE = re.compile(r"#\d+|/issues/\d+")


def _xfail_problems(path: Path) -> list[str]:
    tree = _tree(path)
    called = {id(n.func): n for n in ast.walk(tree) if isinstance(n, ast.Call)}
    problems: list[str] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Attribute) and node.attr == "xfail"):
            continue
        where = f"{_rel(path)}:{node.lineno}"
        if isinstance(node.value, ast.Name) and node.value.id == "pytest":
            problems.append(f"{where}: imperative pytest.xfail(); use a marker")
            continue
        call = called.get(id(node))
        if call is None:
            problems.append(f"{where}: bare xfail; add raises= and reason='#<issue>'")
            continue
        keywords = {k.arg: k.value for k in call.keywords if k.arg}
        reason = keywords.get("reason")
        if "raises" not in keywords:
            problems.append(f"{where}: xfail without raises=")
        if "strict" in keywords and not (
            isinstance(keywords["strict"], ast.Constant) and keywords["strict"].value is True
        ):
            problems.append(f"{where}: non-strict xfail")
        if not (
            isinstance(reason, ast.Constant)
            and isinstance(reason.value, str)
            and _ISSUE.search(reason.value)
        ):
            problems.append(f"{where}: xfail reason must link the open issue (#<n>)")
    return problems


def test_xfails_are_strict_and_paired_with_an_issue() -> None:
    """xfail_strict is on; every xfail names the exception and the issue it tracks."""
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert config["tool"]["pytest"]["ini_options"]["xfail_strict"] is True
    problems = [p for path in _test_modules() for p in _xfail_problems(path)]
    assert problems == []


# --- docstring retry/resend claims -----------------------------------------------

_CLAIM = re.compile(r"\b(resen[dt]|resend(?:s|ing)?|retr(?:y|ies|ied|ying))\b", re.IGNORECASE)

# Public docstring that talks about retry/resend -> the behaviour tests that pin it,
# or "n/a: <why>" when the sentence is advice or layering, not a behaviour claim.
DOCSTRING_CLAIMS: dict[str, tuple[str, ...] | str] = {
    "src/elke27_lib/client.py::Elke27Client.async_set_barrier": (
        "test/test_barrier_commands.py::test_set_barrier_outcome_unknown_is_not_retried",
        "test/test_barrier_commands.py::test_barrier_set_status_is_send_once",
    ),
    "src/elke27_lib/client.py::Elke27Client.async_raw_request": (
        "test/test_raw_passthrough.py::test_raw_get_is_never_resent_after_lost_reply",
    ),
    "src/elke27_lib/kernel.py::E27Kernel.cancel_command_transport": (
        "test/test_transport_command_retry.py::test_async_execute_timeout_cancels_kernel_transport_retry",
        "test/test_transport_command_retry.py::test_cancel_command_transport_drops_outbound_queued_frame",
    ),
    "src/elke27_lib/kernel.py::E27Kernel.mark_raw_passthrough": (
        "test/test_raw_passthrough.py::test_raw_get_is_never_resent_after_lost_reply",
        "test/test_raw_passthrough.py::test_raw_reply_never_reaches_feature_handlers_or_logs",
    ),
    "src/elke27_lib/dispatcher.py::PendingRequest": "n/a: layering note (retry policy lives above)",
    "src/elke27_lib/errors.py::Elke27LinkSlotsFullError": "n/a: advice to the user",
    "src/elke27_lib/linking.py::perform_api_link": "n/a: advice to callers",
    "src/elke27_lib/session.py::Session.reconnect": "n/a: layering note (retry policy lives above)",
}


def _claims(path: Path) -> set[str]:
    found: set[str] = set()

    def visit(node: ast.AST, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                qualname = f"{prefix}{child.name}"
                doc = ast.get_docstring(child)
                if doc and not child.name.startswith("_") and _CLAIM.search(doc):
                    found.add(f"{_rel(path)}::{qualname}")
                visit(child, f"{qualname}.")

    visit(_tree(path), "")
    return found


def _test_exists(node_id: str) -> bool:
    file, _, name = node_id.partition("::")
    path = ROOT / file
    if not path.exists():
        return False
    return any(
        isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef) and n.name == name
        for n in ast.walk(_tree(path))
    )


def test_retry_and_resend_docstrings_are_pinned_by_tests() -> None:
    """A public docstring promising (no) retry/resend has a behaviour test behind it."""
    found = {claim for path in _files(SRC) for claim in _claims(path)}
    assert found - DOCSTRING_CLAIMS.keys() == set(), (
        "New retry/resend wording in a public docstring: add a behaviour test and "
        "register it in DOCSTRING_CLAIMS (or 'n/a: <why>')."
    )
    assert DOCSTRING_CLAIMS.keys() - found == set(), "Drop stale DOCSTRING_CLAIMS entries"
    missing = [
        node_id
        for tests in DOCSTRING_CLAIMS.values()
        if not isinstance(tests, str)
        for node_id in tests
        if not _test_exists(node_id)
    ]
    assert missing == []


# --- getattr/hasattr with a literal name in the library ---------------------------

# Literal-name getattr/hasattr calls per file (ruff B009 only covers the no-default
# form). Prefer typed members; if one is truly needed, raise the count in the same PR
# so review sees it. Lower the count when you remove one.
GETATTR_LITERAL_CEILING: dict[str, int] = {
    "src/elke27_lib/client.py": 30,
    "src/elke27_lib/handlers/area.py": 2,
    "src/elke27_lib/handlers/bus_ios.py": 1,
    "src/elke27_lib/handlers/control.py": 3,
    "src/elke27_lib/handlers/log.py": 1,
    "src/elke27_lib/handlers/system.py": 1,
    "src/elke27_lib/handlers/zone.py": 1,
    "src/elke27_lib/kernel.py": 9,
    "src/elke27_lib/session.py": 5,
}


def _getattr_literals(path: Path) -> int:
    return sum(
        1
        for node in ast.walk(_tree(path))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in {"getattr", "hasattr"}
        and _literal_name(node) is not None
    )


def test_getattr_literal_names_do_not_grow() -> None:
    """Typed members instead of getattr/hasattr probes (repeat review finding)."""
    counts = {_rel(p): n for p in _files(SRC) if (n := _getattr_literals(p))}
    assert counts == GETATTR_LITERAL_CEILING


# --- noqa escapes for SLF001 / BLE001 ----------------------------------------------

_NOQA = re.compile(r"#\s*(ruff:\s*)?noqa\b(?::([^#]*))?", re.IGNORECASE)
WATCHED = ("SLF001", "BLE001")

# "<file>:<code>" -> comments that silence it. The key ends in ":file" for a
# file-level ruff noqa header. Only real comments count (tokenized, so noqa text in
# strings and docstrings is ignored). Matching is case-insensitive, codes may be
# comma- or space-separated, and a bare noqa (no codes) counts for every watched
# code. Lower an entry when you remove an escape; never raise it.
NOQA_CEILING: dict[str, int] = {
    "src/elke27_lib/client.py:BLE001": 12,
    "src/elke27_lib/discovery.py:BLE001": 1,
    "src/elke27_lib/dispatcher.py:BLE001": 1,
    "src/elke27_lib/handlers/control.py:BLE001": 2,
    "src/elke27_lib/kernel.py:BLE001": 4,
    "src/elke27_lib/outbound.py:BLE001": 3,
    "src/elke27_lib/session.py:BLE001": 1,
    "test/conftest.py:BLE001": 2,
    "test/test_e27_area_get_status_live.py:BLE001": 1,
    "test/test_e27_area_info_live.py:BLE001": 1,
    "test/test_e27_configured_names_live.py:BLE001": 1,
    "test/test_e27_network_param_live.py:BLE001": 1,
    "test/test_e27_output_tstat_live.py:BLE001": 1,
    "test/test_e27_table_info_live.py:BLE001": 1,
    "test/test_e27_zone_defs_live.py:BLE001": 1,
    "test/test_e27_zone_live.py:BLE001": 1,
    "test/test_snapshot_after_arm_bypass.py:BLE001": 1,
}


def _comments(path: Path) -> list[str]:
    with path.open("rb") as handle:
        return [
            tok.string for tok in tokenize.tokenize(handle.readline) if tok.type == tokenize.COMMENT
        ]


def _noqa_counts() -> dict[str, int]:
    counts: dict[str, int] = {}
    for path in [*_files(SRC), *_files(TEST), *_files(ROOT / "devtools")]:
        for comment in _comments(path):
            for match in _NOQA.finditer(comment):
                listed = (match.group(2) or "").strip()
                codes = set(re.split(r"[\s,]+", listed.upper()))
                for code in WATCHED:
                    if not listed or code in codes:
                        key = f"{_rel(path)}:{code}" + (":file" if match.group(1) else "")
                        counts[key] = counts.get(key, 0) + 1
    return counts


def test_no_new_noqa_for_private_access_or_broad_except() -> None:
    """SLF001/BLE001 escapes only shrink (repeat review finding)."""
    assert _noqa_counts() == NOQA_CEILING, (
        "Use the public API instead of silencing SLF001, and catch specific exceptions "
        "instead of silencing BLE001. If you removed an escape, lower NOQA_CEILING."
    )
