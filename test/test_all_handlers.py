from __future__ import annotations

from types import SimpleNamespace

from elke27_lib.handlers import all_handlers


def test_collect_handlers_filters_and_maps() -> None:
    def handler_test(_msg, _ctx):  # type: ignore[no-untyped-def]
        return True

    module = SimpleNamespace(handler_test=handler_test, not_handler=lambda: None)
    found = all_handlers._collect_handlers(module)
    assert found["test"] is handler_test
