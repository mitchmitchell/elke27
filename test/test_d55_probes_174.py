"""Decision 55 probes for #174: legacy flake8-self name ignores and bool ceilings."""

from __future__ import annotations

from pathlib import Path

import pytest

from test.helpers.devtools import load

ratchet = load("ratchet")


def _tables(root: Path, files: dict[str, str]) -> dict[str, object]:
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text, encoding="utf-8")
    tree = ratchet.Tree(root, None)
    tree.paths = lambda: sorted(files)
    return ratchet.tables(tree)


def _messages(tmp_path: Path, base: dict[str, str], head: dict[str, str]) -> list[str]:
    old = _tables(tmp_path / "base", base)
    new = _tables(tmp_path / "head", head)
    return [f.message for f in ratchet.compare(old, new)]


@pytest.mark.parametrize("key", ["ignore-names", "extend-ignore-names"])
def test_legacy_top_level_flake8_self_names_are_growth(tmp_path: Path, key: str) -> None:
    base = {"pyproject.toml": "[tool.ruff]\nline-length = 100\n"}
    head = {
        "pyproject.toml": f"[tool.ruff]\nline-length = 100\n[tool.ruff.flake8-self]\n{key} = ['_seam']\n"
    }
    assert _messages(tmp_path, base, head) == [f"tool.ruff.flake8-self.{key} gained '_seam'"]


def test_toml_ceiling_bool_value_fails_closed(tmp_path: Path) -> None:
    base = {"pyproject.toml": "[tool.elke27.x.comment_ceiling]\n'src/a.py' = 1\n"}
    head = {"pyproject.toml": "[tool.elke27.x.comment_ceiling]\n'src/a.py' = true\n"}
    assert _messages(tmp_path, base, head) == [
        "tool.elke27.x.comment_ceiling: 'src/a.py' is not an integer count"
    ]
