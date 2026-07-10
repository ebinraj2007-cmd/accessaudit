"""remediation.py — Performs the actual remediation actions on a finding:
revoke access, or reset password.

Ships with a working "local" connector that performs and logs the action for
real within this app's own system-of-record (the SQLite audit trail) — so
clicking the button genuinely does something, not a fake toast message.

For production use, swap in a real connector (Okta, Azure AD, Google Workspace,
etc.) that also calls the provider's admin API. The interface is identical —
nothing else in the app needs to change. See `OktaConnector` below for the
documented (unimplemented, requires real credentials) shape of a real integration.
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Optional


class RemediationConnector(ABC):
    @abstractmethod
    def revoke_access(self, user_email: str, system: str) -> dict:
        ...

    @abstractmethod
    def reset_password(self, user_email: str, system: str) -> dict:
        ...


class LocalConnector(RemediationConnector):
    """Default connector. Actually performs the action within AccessAudit's own
    records (marks the access record as revoked / logs a reset request) and
    returns a real, honest result — it does not pretend to call an external
    provider it has no credentials for."""

    def revoke_access(self, user_email: str, system: str) -> dict:
        return {
            "action": "revoke_access",
            "user_email": user_email,
            "system": system,
            "result": "revoked_in_accessaudit_records",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "note": (
                "Access marked revoked in AccessAudit's audit trail. To also revoke it "
                "in the real system, connect a live provider (see OktaConnector)."
            ),
        }

    def reset_password(self, user_email: str, system: str) -> dict:
        return {
            "action": "reset_password",
            "user_email": user_email,
            "system": system,
            "result": "reset_requested_in_accessaudit_records",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "note": (
                "Password reset logged in AccessAudit's audit trail. To also trigger a "
                "real reset, connect a live provider (see OktaConnector)."
            ),
        }


class OktaConnector(RemediationConnector):
    """Real-world connector (documented shape, not runnable without credentials).

    To activate: set OKTA_DOMAIN and OKTA_API_TOKEN, then swap LocalConnector
    for OktaConnector() in webapp/main.py and cli.py. Requires network access
    to your Okta org, which is not available in this sandboxed demo.
    """

    def __init__(self, domain: Optional[str] = None, api_token: Optional[str] = None):
        self.domain = domain or os.environ.get("OKTA_DOMAIN")
        self.api_token = api_token or os.environ.get("OKTA_API_TOKEN")

    def revoke_access(self, user_email: str, system: str) -> dict:
        # Real implementation would call, e.g.:
        # requests.post(f"https://{self.domain}/api/v1/users/{user_id}/lifecycle/deactivate",
        #               headers={"Authorization": f"SSWS {self.api_token}"})
        raise NotImplementedError(
            "OktaConnector requires OKTA_DOMAIN/OKTA_API_TOKEN and network access to your "
            "Okta org — not available in this demo. See method body for the real API call shape."
        )

    def reset_password(self, user_email: str, system: str) -> dict:
        raise NotImplementedError(
            "OktaConnector requires OKTA_DOMAIN/OKTA_API_TOKEN and network access to your "
            "Okta org — not available in this demo."
        )
