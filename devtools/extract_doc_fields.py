"""Extract documented response and broadcast fields from the Elk API reference.

The reference is private and never lives in this repository, so its path is passed
on the command line or in the ``ELKE27_API_DOC`` environment variable.

Each JSON example in the reference starts on a line whose first non-blank text after
the bullet is ``{``. Examples may wrap over several lines; the lines are joined with a
single space until the braces balance or the next bullet starts. Curly quotes are read as straight quotes. A
message is a response or broadcast when it has a top-level ``seq`` and no ``session_id``. Its type is ``(group, command)`` and its documented fields
are the top-level keys of the command body. Requests are skipped, and examples that
do not parse as JSON are counted and reported on stderr.

The generated module lists field names only. Doc locations are written only when
``--locations`` names a file outside this repository.

Usage::

    python devtools/extract_doc_fields.py [DOC] [--output PATH] [--check]
        [--locations PATH]

``--output`` defaults to ``src/elke27_lib/protocol_manifest.py``. ``--check`` exits 1
when the output file differs from what the reference generates, without writing.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = ROOT / "src" / "elke27_lib" / "protocol_manifest.py"
DOC_ENV = "ELKE27_API_DOC"
BULLET_CHARS = "▪•◦-* \t"
BULLETS = ("▪", "•", "◦")
ENVELOPE_KEYS = frozenset({"seq", "session_id"})
MAX_EXAMPLE_LINES = 40
CURLY_QUOTES = str.maketrans({"\u201c": '"', "\u201d": '"'})

MessageType = tuple[str, str]


@dataclass(frozen=True)
class Example:
    """One JSON example and the 1-based line it starts on."""

    line: int
    text: str


@dataclass(frozen=True)
class Extraction:
    """Documented fields per message type, where each was seen, and unparsed examples."""

    fields: Mapping[MessageType, frozenset[str]]
    locations: Mapping[MessageType, Mapping[str, int]]
    unparsed: Sequence[int]


def _balance(text: str) -> int:
    depth = 0
    in_string = False
    escaped = False
    for char in text:
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
    return depth


def _closing_index(text: str) -> int:
    depth = 0
    in_string = False
    escaped = False
    for index, char in enumerate(text):
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index
    return -1


def _starts_bullet(line: str) -> bool:
    return line.lstrip().startswith(BULLETS)


def iter_examples(lines: Sequence[str]) -> Iterator[Example]:
    """Yield every JSON example that starts a bullet line, joined across wraps."""
    index = 0
    while index < len(lines):
        stripped = lines[index].lstrip(BULLET_CHARS)
        if not stripped.startswith("{"):
            index += 1
            continue
        start = index
        parts = [stripped.strip()]
        while _balance(" ".join(parts)) > 0 and index + 1 < len(lines):
            if index - start >= MAX_EXAMPLE_LINES or _starts_bullet(lines[index + 1]):
                break
            index += 1
            parts.append(lines[index].strip())
        joined = " ".join(parts)
        end = _closing_index(joined)
        yield Example(line=start + 1, text=joined[: end + 1] if end >= 0 else joined)
        index += 1


def _message_fields(message: object) -> Iterator[tuple[MessageType, list[str]]]:
    if not isinstance(message, dict) or "seq" not in message or "session_id" in message:
        return
    for group, body in message.items():
        if group in ENVELOPE_KEYS or not isinstance(body, dict):
            continue
        for command, payload in body.items():
            if isinstance(payload, dict):
                yield (str(group), str(command)), [str(key) for key in payload]


def extract(lines: Sequence[str]) -> Extraction:
    """Collect documented fields per message type from the reference text."""
    fields: dict[MessageType, set[str]] = {}
    locations: dict[MessageType, dict[str, int]] = {}
    unparsed: list[int] = []
    for example in iter_examples(lines):
        try:
            message = json.loads(example.text.translate(CURLY_QUOTES))
        except json.JSONDecodeError:
            unparsed.append(example.line)
            continue
        for message_type, keys in _message_fields(message):
            fields.setdefault(message_type, set()).update(keys)
            seen = locations.setdefault(message_type, {})
            for key in keys:
                seen.setdefault(key, example.line)
    return Extraction(
        fields={key: frozenset(value) for key, value in fields.items()},
        locations=locations,
        unparsed=unparsed,
    )


def render_manifest(fields: Mapping[MessageType, Iterable[str]]) -> str:
    """Render the manifest module source, sorted so output is stable."""
    out = [
        '"""Documented response and broadcast fields per message type.',
        "",
        "Generated by devtools/extract_doc_fields.py from the Elk API reference. Data only:",
        "nothing in the library imports this module at runtime. Regenerate it in a PR;",
        "never edit it by hand.",
        '"""',
        "",
        "from __future__ import annotations",
        "",
        "from collections.abc import Mapping",
        "from typing import Final",
        "",
        "DOCUMENTED_FIELDS: Final[Mapping[tuple[str, str], frozenset[str]]] = {",
    ]
    for (group, command), names in sorted(fields.items()):
        out.append(f"    ({json.dumps(group)}, {json.dumps(command)}): frozenset(")
        out.append("        {")
        out.extend(f"            {json.dumps(name, ensure_ascii=False)}," for name in sorted(names))
        out.append("        }")
        out.append("    ),")
    out.append("}")
    return "\n".join(out) + "\n"


def render_locations(locations: Mapping[MessageType, Mapping[str, int]]) -> str:
    """Render the private doc-location sidecar as markdown."""
    out = ["# Field doc locations (PRIVATE, never cite on GitHub)", ""]
    for (group, command), seen in sorted(locations.items()):
        out.append(f"## {group}.{command}")
        out.extend(f"- `{name}`: line {line}" for name, line in sorted(seen.items()))
        out.append("")
    return "\n".join(out)


def read_lines(path: Path) -> list[str]:
    """Read the reference as lines split on newlines only, so page breaks keep line numbers."""
    return path.read_text(encoding="utf-8").split("\n")


def _inside_repo(path: Path) -> bool:
    return path.resolve().is_relative_to(ROOT)


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("doc", nargs="?", help=f"reference text file (or set {DOC_ENV})")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--locations", type=Path)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    doc_arg: str | None = args.doc or os.environ.get(DOC_ENV)
    if not doc_arg:
        print(f"error: pass the reference path or set {DOC_ENV}", file=sys.stderr)
        return 2
    doc = Path(doc_arg)
    if not doc.is_file():
        print("error: reference file not found", file=sys.stderr)
        return 2
    locations_path: Path | None = args.locations
    if locations_path is not None and _inside_repo(locations_path):
        print("error: --locations must point outside this repository", file=sys.stderr)
        return 2
    extraction = extract(read_lines(doc))
    if extraction.unparsed:
        print(
            f"skipped {len(extraction.unparsed)} examples that are not valid JSON", file=sys.stderr
        )
    manifest = render_manifest(extraction.fields)
    output: Path = args.output
    if args.check:
        current = output.read_text(encoding="utf-8") if output.is_file() else ""
        if current != manifest:
            print(f"{output} is out of date; regenerate it", file=sys.stderr)
            return 1
        return 0
    output.write_text(manifest, encoding="utf-8")
    if locations_path is not None:
        locations_path.write_text(render_locations(extraction.locations), encoding="utf-8")
    print(f"{len(extraction.fields)} message types written", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
