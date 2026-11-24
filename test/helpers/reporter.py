# test/helpers/reporter.py
from __future__ import annotations

import importlib
import importlib.util
import json
import logging
import os
import pathlib
import time
from dataclasses import dataclass, field
from typing import Any

from test.helpers.redaction import redact_record


def _safe_json_default(obj: Any) -> Any:
    # Ensure JSON serialization never crashes reporting.
    if isinstance(obj, (bytes, bytearray)):
        return {"__bytes__": True, "len": len(obj), "sha256": None}
    try:
        return str(obj)
    except (TypeError, ValueError, RecursionError):
        return repr(obj)


def _now_iso() -> str:
    # ISO-ish timestamp without timezone dependency.
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _yaml_text(summary: dict[str, Any]) -> str | None:
    """The summary as YAML, or ``None`` without PyYAML or when a value is not representable."""
    if importlib.util.find_spec("yaml") is None:
        return None
    yaml_mod = importlib.import_module("yaml")
    try:
        text = yaml_mod.safe_dump(summary, sort_keys=False, default_flow_style=False)
    except yaml_mod.YAMLError as err:
        logging.getLogger(__name__).warning("summary is not YAML (%s); writing JSON instead", err)
        return None
    return text if isinstance(text, str) else None


@dataclass
class Reporter:
    run_id: str
    test_id: str
    artifacts_dir: pathlib.Path
    emit_jsonl: bool = True
    emit_yaml: bool = False
    enable: bool = True

    _t0: float = field(default_factory=time.monotonic, init=False)
    _records: list[dict[str, Any]] = field(default_factory=list, init=False)
    _jsonl_path: pathlib.Path | None = field(default=None, init=False)
    _yaml_path: pathlib.Path | None = field(default=None, init=False)

    def _t_ms(self) -> int:
        return int((time.monotonic() - self._t0) * 1000)

    def _ensure_paths(self) -> None:
        if not self.enable:
            return
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        base = self.run_id.replace(os.sep, "_")
        self._jsonl_path = self.artifacts_dir / f"{base}.jsonl"
        self._yaml_path = self.artifacts_dir / f"{base}.summary.yaml"

    def _apply_redaction(self, record: dict[str, Any]) -> dict[str, Any]:
        return redact_record(record)

    def emit(self, record_type: str, **fields: Any) -> dict[str, Any]:
        """
        Emit a typed record. Always adds:
          - run_id
          - test_id
          - record_type
          - t_ms
          - ts_utc
        Writes JSONL immediately (append-only) when enabled.
        """
        if not self.enable:
            return {}

        self._ensure_paths()

        record: dict[str, Any] = {
            "run_id": self.run_id,
            "test_id": self.test_id,
            "record_type": record_type,
            "t_ms": self._t_ms(),
            "ts_utc": _now_iso(),
        }
        record.update(fields)

        record = self._apply_redaction(record)

        self._records.append(record)

        if self.emit_jsonl and self._jsonl_path is not None:
            with self._jsonl_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, default=_safe_json_default, sort_keys=False))
                f.write("\n")

        return record

    def test_start(self) -> None:
        self.emit(
            "test_start",
            meta={
                "pid": os.getpid(),
            },
        )

    def test_end(self, outcome: str, when: str | None, longrepr: Any) -> None:
        err: dict[str, Any] | None = None
        if longrepr is not None:
            # pytest longrepr can be various types; store as string safely.
            err = {"when": when, "longrepr": str(longrepr)}

        self.emit(
            "test_end",
            outcome=outcome,
            error=err,
        )

    def finalize(self) -> None:
        """
        Finalize reporting. JSONL is already written incrementally.
        YAML summary is derived from the collected in-memory records.
        """
        if not self.enable:
            return

        self._ensure_paths()

        if self.emit_yaml and self._yaml_path is not None:
            summary = {
                "run_id": self.run_id,
                "test_id": self.test_id,
                "record_count": len(self._records),
                "records": self._records,
            }
            text = _yaml_text(summary)
            if text is None:
                text = json.dumps(summary, indent=2, default=_safe_json_default, sort_keys=False)
            self._yaml_path.write_text(f"{text.rstrip()}\n", encoding="utf-8")
