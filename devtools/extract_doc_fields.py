"""Extract documented response and broadcast fields from the Elk API reference.

The reference is private and never lives in this repository, so its path is passed
on the command line or in the ``ELKE27_API_DOC`` environment variable.

Each JSON example in the reference starts on a line whose first non-blank text after
the bullet is ``{``. Examples may wrap over several lines; the lines are joined with a
single space until the braces balance or the next bullet starts. Only the ``▪``, ``•``
and ``◦`` bullets end a wrapped example: ``-`` and ``*`` may lead an example line, but a
wrapped line can itself start with ``-`` (a negative number), so they never end one.
Curly quotes are read as straight quotes.

A message is a response or broadcast when it has a top-level ``seq`` and no
``session_id``. Requests and fragments without ``seq`` are skipped. Every other key of
a message is a group, and each key of the group body is handled one of two ways:

- When its value is an object, the key is a command. The type is ``(group, command)``
  and its documented fields are the top-level keys of that object.
- Otherwise the key is a group-level field of a flat message, such as a broadcast whose
  group body holds the values directly, or a command whose value is a list with its
  ``error_code`` beside it. These go to ``DOCUMENTED_GROUP_FIELDS`` per group.

A group whose body is not an object fits neither shape; that example is counted and
reported on stderr, as are examples that do not parse as JSON.

A few types have only malformed examples in the reference. ``REVIEWED_SUPPLEMENT`` holds
their reviewed field sets, and they are merged into the output so ``--check`` still
reproduces the manifest. Each entry must match a malformed example of its type, and an
entry whose type also has a valid example is an error, so the supplement only shrinks.

The generated module lists field names only. Doc locations are written only when
``--locations`` names a file outside this repository.

Usage::

    python devtools/extract_doc_fields.py [DOC] [--output PATH] [--check]
        [--locations PATH]

``--output`` defaults to ``src/elke27_lib/protocol_manifest.py``. ``--check`` exits 1
when the output file differs from what the reference generates, without writing.
``--check`` writes nothing, so combining it with ``--locations`` is refused with exit 2.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = ROOT / "src" / "elke27_lib" / "protocol_manifest.py"
DOC_ENV = "ELKE27_API_DOC"
BULLET_CHARS = "▪•◦-* \t"
BULLETS = ("▪", "•", "◦")
MAX_EXAMPLE_LINES = 40
CURLY_QUOTES = str.maketrans({"\u201c": '"', "\u201d": '"'})

MessageType = tuple[str, str]

REVIEWED_SUPPLEMENT: Mapping[MessageType, frozenset[str]] = {
    ("area", "get_trouble"): frozenset({"area_id", "error_code"}),
    ("zone", "get_all_zones_status"): frozenset({"status", "error_code"}),
}


@dataclass(frozen=True)
class Example:
    """One JSON example and the 1-based line it starts on."""

    line: int
    text: str


@dataclass(frozen=True)
class Extraction:
    """Documented fields per message type and per flat group, where each was seen.

    ``unparsed`` and ``unshaped`` hold the lines of examples that are not valid JSON and
    of responses with a group body that is not an object. ``supplemented`` names the
    types whose fields come from ``REVIEWED_SUPPLEMENT``.
    """

    fields: Mapping[MessageType, frozenset[str]]
    group_fields: Mapping[str, frozenset[str]]
    locations: Mapping[MessageType, Mapping[str, int]]
    group_locations: Mapping[str, Mapping[str, int]]
    unparsed: Sequence[int]
    unshaped: Sequence[int]
    supplemented: frozenset[MessageType]


class SupplementError(ValueError):
    """A ``REVIEWED_SUPPLEMENT`` entry has a valid example or no malformed one."""


@dataclass(frozen=True)
class _Shape:
    commands: list[tuple[MessageType, list[str]]]
    group_keys: list[tuple[str, list[str]]]
    unshaped: bool


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
        while _closing_index(" ".join(parts)) < 0 and index + 1 < len(lines):
            if index - start >= MAX_EXAMPLE_LINES or _starts_bullet(lines[index + 1]):
                break
            index += 1
            parts.append(lines[index].strip())
        joined = " ".join(parts)
        end = _closing_index(joined)
        yield Example(line=start + 1, text=joined[: end + 1] if end >= 0 else joined)
        index += 1


def _message_shape(message: object) -> _Shape | None:
    if not isinstance(message, dict) or "seq" not in message or "session_id" in message:
        return None
    shape = _Shape(commands=[], group_keys=[], unshaped=False)
    for group, body in message.items():
        if group == "seq":
            continue
        if not isinstance(body, dict):
            return _Shape(commands=[], group_keys=[], unshaped=True)
        flat: list[str] = []
        for command, payload in body.items():
            if isinstance(payload, dict):
                shape.commands.append(((str(group), str(command)), [str(key) for key in payload]))
            else:
                flat.append(str(command))
        if flat:
            shape.group_keys.append((str(group), flat))
    return shape


def _malformed_example_line(message_type: MessageType, malformed: Sequence[Example]) -> int | None:
    group, command = message_type
    pattern = re.compile(rf'"{re.escape(group)}"\s*:\s*\{{\s*"{re.escape(command)}"\s*:')
    for example in malformed:
        if pattern.search(example.text.translate(CURLY_QUOTES)):
            return example.line
    return None


def extract(
    lines: Sequence[str],
    supplement: Mapping[MessageType, frozenset[str]] | None = None,
) -> Extraction:
    """Collect documented fields per message type from the reference text.

    ``supplement`` defaults to ``REVIEWED_SUPPLEMENT``. Raises ``SupplementError`` when
    an entry has a valid example of its type, or no malformed example to stand in for.
    """
    fields: dict[MessageType, set[str]] = {}
    group_fields: dict[str, set[str]] = {}
    locations: dict[MessageType, dict[str, int]] = {}
    group_locations: dict[str, dict[str, int]] = {}
    malformed: list[Example] = []
    unshaped: list[int] = []
    for example in iter_examples(lines):
        try:
            message = json.loads(example.text.translate(CURLY_QUOTES))
        except json.JSONDecodeError:
            malformed.append(example)
            continue
        shape = _message_shape(message)
        if shape is None:
            continue
        if shape.unshaped:
            unshaped.append(example.line)
            continue
        for message_type, keys in shape.commands:
            fields.setdefault(message_type, set()).update(keys)
            seen = locations.setdefault(message_type, {})
            for key in keys:
                seen.setdefault(key, example.line)
        for group, keys in shape.group_keys:
            group_fields.setdefault(group, set()).update(keys)
            seen_in_group = group_locations.setdefault(group, {})
            for key in keys:
                seen_in_group.setdefault(key, example.line)
    reviewed = REVIEWED_SUPPLEMENT if supplement is None else supplement
    for message_type, names in reviewed.items():
        if message_type in fields:
            raise SupplementError(f"{message_type} has a valid example; drop its supplement entry")
        line = _malformed_example_line(message_type, malformed)
        if line is None:
            raise SupplementError(f"{message_type} has no malformed example to supplement")
        fields[message_type] = set(names)
        locations[message_type] = dict.fromkeys(names, line)
    return Extraction(
        fields={key: frozenset(value) for key, value in fields.items()},
        group_fields={key: frozenset(value) for key, value in group_fields.items()},
        locations=locations,
        group_locations=group_locations,
        unparsed=[example.line for example in malformed],
        unshaped=unshaped,
        supplemented=frozenset(reviewed),
    )


def _render_names(names: Iterable[str]) -> list[str]:
    out = ["        {"]
    out.extend(f"            {json.dumps(name, ensure_ascii=False)}," for name in sorted(names))
    out.append("        }")
    out.append("    ),")
    return out


def render_manifest(
    fields: Mapping[MessageType, Iterable[str]],
    group_fields: Mapping[str, Iterable[str]],
) -> str:
    """Render the manifest module source, sorted so output is stable."""
    out = [
        '"""Documented response and broadcast fields per message type.',
        "",
        "Generated by devtools/extract_doc_fields.py from the Elk API reference. Data only:",
        "nothing in the library imports this module at runtime. Regenerate it in a PR;",
        "never edit it by hand.",
        "",
        "DOCUMENTED_FIELDS maps (group, command) to the keys of the command object.",
        "DOCUMENTED_GROUP_FIELDS maps a group to the keys of its body whose values are not",
        "objects, as in flat broadcasts or a command whose value is a list.",
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
        out.extend(_render_names(names))
    out.append("}")
    out.append("")
    out.append("DOCUMENTED_GROUP_FIELDS: Final[Mapping[str, frozenset[str]]] = {")
    for group, names in sorted(group_fields.items()):
        out.append(f"    {json.dumps(group)}: frozenset(")
        out.extend(_render_names(names))
    out.append("}")
    return "\n".join(out) + "\n"


def render_locations(extraction: Extraction) -> str:
    """Render the private doc-location sidecar as markdown."""
    out = ["# Field doc locations (PRIVATE, never cite on GitHub)", ""]
    for (group, command), seen in sorted(extraction.locations.items()):
        if (group, command) in extraction.supplemented:
            out.append(f"## {group}.{command} (reviewed supplement; malformed example)")
        else:
            out.append(f"## {group}.{command}")
        out.extend(f"- `{name}`: line {line}" for name, line in sorted(seen.items()))
        out.append("")
    for group, seen in sorted(extraction.group_locations.items()):
        out.append(f"## {group} (group-level fields)")
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
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit 1 if --output is out of date; writes nothing, so --locations is refused",
    )
    parser.add_argument("--locations", type=Path, help="private location report, outside repo")
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
    if locations_path is not None and args.check:
        print("error: --check writes nothing; drop --locations", file=sys.stderr)
        return 2
    if locations_path is not None and _inside_repo(locations_path):
        print("error: --locations must point outside this repository", file=sys.stderr)
        return 2
    try:
        extraction = extract(read_lines(doc))
    except SupplementError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    if extraction.unparsed:
        print(
            f"skipped {len(extraction.unparsed)} examples that are not valid JSON", file=sys.stderr
        )
    if extraction.unshaped:
        print(
            f"skipped {len(extraction.unshaped)} responses whose group body is not an object",
            file=sys.stderr,
        )
    manifest = render_manifest(extraction.fields, extraction.group_fields)
    output: Path = args.output
    if args.check:
        current = output.read_text(encoding="utf-8") if output.is_file() else ""
        if current != manifest:
            print(f"{output} is out of date; regenerate it", file=sys.stderr)
            return 1
        return 0
    output.write_text(manifest, encoding="utf-8")
    if locations_path is not None:
        locations_path.write_text(render_locations(extraction), encoding="utf-8")
    print(f"{len(extraction.fields)} message types written", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
