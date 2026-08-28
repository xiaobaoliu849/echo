from __future__ import annotations

import os
import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from main import create_app
from services.tavus_service import TavusError, TavusService


class TavusRouterTests(unittest.TestCase):
    def setUp(self) -> None:
        # These tests cover the Tavus router contract, not the auth middleware
        # (which has dedicated coverage); this machine may have write auth on.
        self._enforce_patcher = patch("main.should_enforce_auth", return_value=False)
        self._enforce_patcher.start()
        self.addCleanup(self._enforce_patcher.stop)
        self.app = create_app()
        self.client = TestClient(self.app)

    def _patch_service(self, **methods) -> None:
        for name, mocked in methods.items():
            patcher = patch.object(TavusService, name, mocked)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_create_conversation_requires_api_key(self) -> None:
        with patch.dict(os.environ):
            os.environ.pop("TAVUS_API_KEY", None)
            response = self.client.post("/api/tavus/conversations", json={"pal_id": "pal-1"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"]["code"], "TAVUS_NOT_CONFIGURED")

    def test_create_conversation_requires_pal_id(self) -> None:
        with patch.dict(os.environ):
            os.environ["TAVUS_API_KEY"] = "env-key"
            os.environ.pop("TAVUS_PAL_ID", None)
            response = self.client.post("/api/tavus/conversations", json={})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"]["code"], "TAVUS_PAL_ID_MISSING")

    def test_create_conversation_returns_join_payload(self) -> None:
        self._patch_service(
            create_conversation=AsyncMock(
                return_value={
                    "conversation_id": "conv-9",
                    "conversation_url": "https://tavus.daily.co/room?t=token",
                    "status": "started",
                }
            )
        )
        response = self.client.post(
            "/api/tavus/conversations",
            json={"pal_id": "pal-1"},
            headers={"X-Tavus-Api-Key": "header-key"},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["conversation_id"], "conv-9")
        self.assertEqual(payload["conversation_url"], "https://tavus.daily.co/room?t=token")

        create_mock = TavusService.create_conversation
        create_mock.assert_awaited_once()
        self.assertEqual(create_mock.await_args.kwargs["pal_id"], "pal-1")

    def test_create_conversation_falls_back_to_server_pal_id(self) -> None:
        self._patch_service(
            create_conversation=AsyncMock(
                return_value={
                    "conversation_id": "conv-9",
                    "conversation_url": "https://tavus.daily.co/room?t=token",
                }
            )
        )
        with patch.dict(os.environ):
            os.environ["TAVUS_API_KEY"] = "env-key"
            os.environ["TAVUS_PAL_ID"] = "env-pal"
            response = self.client.post("/api/tavus/conversations", json={})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            TavusService.create_conversation.await_args.kwargs["pal_id"],
            "env-pal",
        )

    def test_create_conversation_falls_back_to_config_settings(self) -> None:
        self._patch_service(
            create_conversation=AsyncMock(
                return_value={
                    "conversation_id": "conv-cfg",
                    "conversation_url": "https://tavus.daily.co/room?t=token",
                }
            )
        )
        with patch.dict(os.environ):
            os.environ.pop("TAVUS_API_KEY", None)
            os.environ.pop("TAVUS_PAL_ID", None)
            mock_cfg = {
                "api_keys": {"tavus_api_key": "cfg-key"},
                "tavus_settings": {"default_pal_id": "cfg-pal"},
            }
            with patch("services.config_loader.BackendConfig.get", side_effect=lambda k: mock_cfg.get(k)):
                response = self.client.post("/api/tavus/conversations", json={})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            TavusService.create_conversation.await_args.kwargs["pal_id"],
            "cfg-pal",
        )

    def test_create_conversation_config_takes_precedence_over_env(self) -> None:
        self._patch_service(
            create_conversation=AsyncMock(
                return_value={
                    "conversation_id": "conv-cfg",
                    "conversation_url": "https://tavus.daily.co/room?t=token",
                }
            )
        )
        with patch.dict(os.environ):
            os.environ["TAVUS_API_KEY"] = "env-key"
            os.environ["TAVUS_PAL_ID"] = "env-pal"
            mock_cfg = {
                "api_keys": {"tavus_api_key": "cfg-key"},
                "tavus_settings": {"default_pal_id": "cfg-pal"},
            }
            with patch("services.config_loader.BackendConfig.get", side_effect=lambda k: mock_cfg.get(k)):
                response = self.client.post("/api/tavus/conversations", json={})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            TavusService.create_conversation.await_args.kwargs["pal_id"],
            "cfg-pal",
        )

    def test_create_conversation_maps_upstream_auth_error(self) -> None:
        self._patch_service(
            create_conversation=AsyncMock(
                side_effect=TavusError("TAVUS_UPSTREAM_ERROR", "denied", upstream_status=401)
            )
        )
        response = self.client.post(
            "/api/tavus/conversations",
            json={"pal_id": "pal-1"},
            headers={"X-Tavus-Api-Key": "header-key"},
        )
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["detail"]["code"], "TAVUS_AUTH_REJECTED")

    def test_list_pals_returns_summaries(self) -> None:
        self._patch_service(
            list_pals=AsyncMock(
                return_value=[
                    {"pal_id": "pal-1", "pal_name": "Mia"},
                    {"pal_name": "missing id"},
                ]
            )
        )
        response = self.client.get("/api/tavus/pals", headers={"X-Tavus-Api-Key": "header-key"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {"pals": [{"pal_id": "pal-1", "pal_name": "Mia"}]},
        )

    def test_end_conversation_returns_ended_flag(self) -> None:
        self._patch_service(end_conversation=AsyncMock(return_value=None))
        response = self.client.delete(
            "/api/tavus/conversations/conv-9",
            headers={"X-Tavus-Api-Key": "header-key"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ended": True})


if __name__ == "__main__":
    unittest.main()
