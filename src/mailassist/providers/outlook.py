from __future__ import annotations

from mailassist.models import DraftRecord, ProviderDraftReference
from mailassist.providers.base import DraftProvider, ProviderReadiness


class OutlookProvider(DraftProvider):
    name = "outlook"

    def __init__(
        self,
        *,
        client_id: str = "",
        tenant_id: str = "",
        redirect_uri: str = "",
    ) -> None:
        self.client_id = client_id.strip()
        self.tenant_id = tenant_id.strip()
        self.redirect_uri = redirect_uri.strip()

    def authenticate(self) -> str:
        raise NotImplementedError(
            "Outlook authentication is not implemented yet. The provider contract is ready for Microsoft Graph."
        )

    def get_account_email(self) -> str | None:
        return None

    def readiness_check(self) -> ProviderReadiness:
        if not self.client_id:
            return ProviderReadiness(
                provider=self.name,
                status="not_configured",
                message="Outlook is missing a Microsoft Graph client id.",
                can_authenticate=False,
                can_read=False,
                can_create_drafts=False,
                details={
                    "tenant_id": self.tenant_id,
                    "redirect_uri": self.redirect_uri,
                },
            )
        return ProviderReadiness(
            provider=self.name,
            status="blocked",
            message=(
                "Outlook Graph support is not implemented yet. The next step is Microsoft Graph auth, "
                "mailbox read, and draft creation against mocks or a developer tenant."
            ),
            can_authenticate=False,
            can_read=False,
            can_create_drafts=False,
            requires_admin_consent=True,
            details={
                "client_id": self.client_id,
                "tenant_id": self.tenant_id,
                "redirect_uri": self.redirect_uri,
            },
        )

    def list_actionable_threads(self, *_args, **_kwargs):
        raise NotImplementedError(
            "Outlook thread listing is planned next. The provider contract is ready for Microsoft Graph."
        )

    def create_draft(self, draft: DraftRecord) -> ProviderDraftReference:
        raise NotImplementedError(
            "Outlook support is planned next. The provider interface is ready for it."
        )
