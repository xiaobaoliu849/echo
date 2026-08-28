from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, Mock, patch

from services.tavus_service import TavusError, TavusService


def _make_client_mock(**method_mocks) -> Mock:
    client = AsyncMock()
    client.__aenter__.return_value = client
    client.__aexit__.return_value = None
    for name, mocked in method_mocks.items():
        setattr(client, name, mocked)
    return client


class TavusServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_create_conversation_sends_pal_id_and_api_key(self) -> None:
        service = TavusService(api_key="tavus-key")

        response = Mock()
        response.status_code = 200
        response.json.return_value = {
            "conversation_id": "conv-1",
            "conversation_url": "https://tavus.daily.co/room?t=token",
            "status": "started",
        }
        request = AsyncMock(return_value=response)

        with patch("services.tavus_service.httpx.AsyncClient") as client_cls:
            client_cls.return_value = _make_client_mock(request=request)

            result = await service.create_conversation(pal_id="pal-123")

        self.assertEqual(result["conversation_id"], "conv-1")
        _, kwargs = request.call_args
        self.assertEqual(kwargs["url"], "https://tavusapi.com/v2/conversations")
        self.assertEqual(kwargs["json"]["pal_id"], "pal-123")
        self.assertEqual(kwargs["headers"]["x-api-key"], "tavus-key")

    async def test_create_conversation_rejects_missing_conversation_url(self) -> None:
        service = TavusService(api_key="tavus-key")

        response = Mock()
        response.status_code = 200
        response.json.return_value = {"conversation_id": "conv-1"}
        request = AsyncMock(return_value=response)

        with patch("services.tavus_service.httpx.AsyncClient") as client_cls:
            client_cls.return_value = _make_client_mock(request=request)

            with self.assertRaises(TavusError) as ctx:
                await service.create_conversation(pal_id="pal-123")

        self.assertEqual(ctx.exception.code, "TAVUS_RESPONSE_INVALID")

    async def test_create_conversation_maps_upstream_error(self) -> None:
        service = TavusService(api_key="tavus-key")

        response = Mock()
        response.status_code = 401
        response.text = "invalid api key"
        request = AsyncMock(return_value=response)

        with patch("services.tavus_service.httpx.AsyncClient") as client_cls:
            client_cls.return_value = _make_client_mock(request=request)

            with self.assertRaises(TavusError) as ctx:
                await service.create_conversation(pal_id="pal-123")

        self.assertEqual(ctx.exception.code, "TAVUS_UPSTREAM_ERROR")
        self.assertEqual(ctx.exception.upstream_status, 401)

    async def test_list_pals_returns_items_from_payload(self) -> None:
        service = TavusService(api_key="tavus-key")

        response = Mock()
        response.status_code = 200
        response.json.return_value = {
            "pals": [{"pal_id": "pal-1", "pal_name": "Mia"}]
        }
        request = AsyncMock(return_value=response)

        with patch("services.tavus_service.httpx.AsyncClient") as client_cls:
            client_cls.return_value = _make_client_mock(request=request)

            pals = await service.list_pals()

        self.assertEqual(pals, [{"pal_id": "pal-1", "pal_name": "Mia"}])
        _, kwargs = request.call_args
        self.assertEqual(kwargs["url"], "https://tavusapi.com/v2/pals")

    async def test_end_conversation_treats_404_as_already_ended(self) -> None:
        service = TavusService(api_key="tavus-key")

        gone = Mock()
        gone.status_code = 404
        gone.text = "not found"
        request = AsyncMock(return_value=gone)

        with patch("services.tavus_service.httpx.AsyncClient") as client_cls:
            client_cls.return_value = _make_client_mock(request=request)

            await service.end_conversation("conv-gone")

        _, kwargs = request.call_args
        self.assertEqual(kwargs["method"], "DELETE")
        self.assertEqual(kwargs["url"], "https://tavusapi.com/v2/conversations/conv-gone")

    async def test_end_conversation_raises_on_upstream_failure(self) -> None:
        service = TavusService(api_key="tavus-key")

        response = Mock()
        response.status_code = 500
        response.text = "boom"
        request = AsyncMock(return_value=response)

        with patch("services.tavus_service.httpx.AsyncClient") as client_cls:
            client_cls.return_value = _make_client_mock(request=request)

            with self.assertRaises(TavusError) as ctx:
                await service.end_conversation("conv-1")

        self.assertEqual(ctx.exception.upstream_status, 500)


if __name__ == "__main__":
    unittest.main()
