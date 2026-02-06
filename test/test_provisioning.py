from __future__ import annotations

from elke27_lib.provisioning import ProvisioningManager


def test_provisioning_credentials_flow() -> None:
    mgr = ProvisioningManager()
    assert mgr.get_credentials() is None

    called: list[str] = []

    def _on_required(reason: str) -> None:
        called.append(reason)

    mgr.on_credentials_required = _on_required
    mgr.request_credentials("need creds")
    assert called == ["need creds"]

    mgr.supply_credentials("code", "pass")
    assert mgr.get_credentials() == ("code", "pass")

    mgr.clear_credentials()
    assert mgr.get_credentials() is None
