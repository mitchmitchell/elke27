"""Load a ``devtools/`` script as a module for tests, leaving the session clean."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

DEVTOOLS = Path(__file__).resolve().parents[2] / "devtools"


def load(name: str) -> ModuleType:
    """Load ``devtools/<name>.py``.

    ``sys.path`` is restored afterwards, and only the modules this load added from
    ``devtools/`` (the script itself and siblings it imports, such as ``allow``) are
    dropped from ``sys.modules``; anything else imported along the way stays.
    """
    saved_path = list(sys.path)
    saved_modules = set(sys.modules)
    sys.path.insert(0, str(DEVTOOLS))
    try:
        spec = importlib.util.spec_from_file_location(f"devtools_{name}", DEVTOOLS / f"{name}.py")
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path[:] = saved_path
        for added in set(sys.modules) - saved_modules:
            origin = getattr(sys.modules[added], "__file__", None)
            if added == f"devtools_{name}" or (origin and Path(origin).parent == DEVTOOLS):
                del sys.modules[added]
