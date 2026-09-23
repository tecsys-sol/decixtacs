from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from uuid import UUID

from networkops.models import AuthEvent, ConfigRevision, NasClient, Page, RenderResult, TacacsServer, parse
from networkops.resources._base import Resource


class Tacacs(Resource):
    """TACACS+ (tac_plus-ng): servers, NAS clients, policies, user mappings, render & deploy."""

    # servers ---------------------------------------------------------------------------------
    def servers(self) -> list[TacacsServer]:
        return [parse(TacacsServer, s) for s in self._c.get("/tacacs/servers")]

    def create_server(self, *, name: str, address: str, port: int = 49, enabled: bool = True,
                      ldap_backend: bool = False) -> TacacsServer:
        """The returned ``agent_token`` is shown only once - store it for the tac_plus-ng agent."""
        return parse(TacacsServer, self._c.post("/tacacs/servers", json={
            "name": name, "address": address, "port": port, "enabled": enabled, "ldap_backend": ldap_backend}))

    def delete_server(self, server_id: UUID | str) -> None:
        self._c.delete(f"/tacacs/servers/{server_id}")

    # render / deploy ----------------------------------------------------------------------------
    def render(self, server_id: UUID | str | None = None) -> RenderResult:
        """Preview the generated tac_plus-ng configuration (keys redacted) and its warnings."""
        return parse(RenderResult, self._c.get("/tacacs/render", params={"server_id": server_id}))

    def deploy(self, server_id: UUID | str) -> ConfigRevision:
        """Publish a new revision; the agent pulls it, validates with ``tac_plus-ng -P`` and reloads.
        Idempotent: redeploying an unchanged render returns the current revision."""
        return parse(ConfigRevision, self._c.post(f"/tacacs/servers/{server_id}/deploy"))

    def revisions(self, server_id: UUID | str) -> list[ConfigRevision]:
        return [parse(ConfigRevision, r) for r in self._c.get(f"/tacacs/servers/{server_id}/revisions")]

    # NAS clients ----------------------------------------------------------------------------------
    def nas_clients(self) -> list[NasClient]:
        return [parse(NasClient, n) for n in self._c.get("/tacacs/devices")]

    def create_nas_client(self, *, name: str, address: str, vendor: str, key: str | None = None,
                          **fields: Any) -> NasClient:
        """vendor: juniper|cisco|arista|fortinet|sophos|mikrotik|generic. ``key`` is generated if omitted."""
        return parse(NasClient, self._c.post("/tacacs/devices", json={
            "name": name, "address": address, "vendor": vendor, "key": key, **fields}))

    def import_inventory(self, device_group_id: UUID | str | None = None) -> list[NasClient]:
        return [parse(NasClient, n) for n in self._c.post(
            "/tacacs/devices/import-inventory", params={"device_group_id": device_group_id})]

    def rotate_key(self, nas_id: UUID | str) -> str:
        """Rotate the NAS shared secret; the new key is returned once. Redeploy afterwards."""
        key: str = self._c.post(f"/tacacs/devices/{nas_id}/rotate-key")["key"]
        return key

    def delete_nas_client(self, nas_id: UUID | str) -> None:
        self._c.delete(f"/tacacs/devices/{nas_id}")

    # policies / user mappings ------------------------------------------------------------------------
    def policies(self) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = self._c.get("/tacacs/policies")
        return result

    def create_policy(self, policy: dict[str, Any]) -> dict[str, Any]:
        result: dict[str, Any] = self._c.post("/tacacs/policies", json=policy)
        return result

    def update_policy(self, policy_id: UUID | str, policy: dict[str, Any]) -> dict[str, Any]:
        result: dict[str, Any] = self._c.put(f"/tacacs/policies/{policy_id}", json=policy)
        return result

    def delete_policy(self, policy_id: UUID | str) -> None:
        self._c.delete(f"/tacacs/policies/{policy_id}")

    def user_mappings(self) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = self._c.get("/tacacs/users")
        return result

    def create_user_mapping(self, *, user_id: UUID | str, auth_method: str = "crypt", password: str | None = None,
                            tacacs_username: str | None = None, **fields: Any) -> dict[str, Any]:
        result: dict[str, Any] = self._c.post("/tacacs/users", json={
            "user_id": user_id, "auth_method": auth_method, "password": password,
            "tacacs_username": tacacs_username, **fields})
        return result

    # auth events ------------------------------------------------------------------------------------------
    def auth_events(self, *, username: str | None = None, result: str | None = None, limit: int = 100,
                    offset: int = 0) -> Page[AuthEvent]:
        return self._c.get_page("/tacacs/events", AuthEvent, {"username": username, "result": result},
                                limit=limit, offset=offset)

    def iter_auth_events(self, *, page_size: int = 500, max_items: int | None = None,
                         **filters: Any) -> Iterator[AuthEvent]:
        return self._c.iterate("/tacacs/events", AuthEvent, filters, page_size=page_size, max_items=max_items)
