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
        self.assertEqual(kwargs["url"], "https://tavusapi.com/v2/pals?limit=100&page=1")

    async def test_list_faces_returns_face_items(self) -> None:
        service = TavusService(api_key="tavus-key")

        response = Mock()
        response.status_code = 200
        response.json.return_value = {
            "data": [
                {
                    "face_id": "rc9cff32ceba",
                    "face_name": "Rio",
                    "model_name": "phoenix-4.5",
                    "status": "completed",
                }
            ]
        }
        request = AsyncMock(return_value=response)

        with patch("services.tavus_service.httpx.AsyncClient") as client_cls:
            client_cls.return_value = _make_client_mock(request=request)

            faces = await service.list_faces()

        self.assertEqual(faces[0]["face_id"], "rc9cff32ceba")
        self.assertEqual(faces[0]["model_name"], "phoenix-4.5")
        _, kwargs = request.call_args
        self.assertEqual(kwargs["url"], "https://tavusapi.com/v2/faces?limit=100&page=1")

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
        self.assertEqual(kwargs["method"], "POST")
        self.assertEqual(kwargs["url"], "https://tavusapi.com/v2/conversations/conv-gone/end")

    async def test_official_data_envelope_and_pagination(self) -> None:
        for method, path, id_key in (("list_pals", "pals", "pal_id"), ("list_faces", "faces", "face_id")):
            with self.subTest(method=method):
                service = TavusService(api_key="key")
                pages = [{"data": [{id_key: "first"}], "total_count": 2},
                         {"data": [{id_key: "second"}], "total_count": 2}]
                with patch.object(service, "_request_json", AsyncMock(side_effect=pages)) as request:
                    result = await getattr(service, method)()
                self.assertEqual([item[id_key] for item in result], ["first", "second"])
                self.assertEqual(request.await_args.args, ("GET", f"/v2/{path}?limit=100&page=2"))

    async def test_invalid_list_does_not_silently_become_empty(self) -> None:
        service = TavusService(api_key="key")
        for payload in ({"unexpected": []}, {"data": None}):
            with patch.object(service, "_request_json", AsyncMock(return_value=payload)):
                with self.assertRaises(TavusError):
                    await service.list_pals()

    async def test_empty_page_stops_when_total_changes(self) -> None:
        service = TavusService(api_key="key")
        with patch.object(service, "_request_json", AsyncMock(return_value={"data": [], "total_count": 10})) as request:
            self.assertEqual(await service.list_faces(), [])
            request.assert_awaited_once()

    async def test_face_override_and_free_test_mode_are_forwarded(self) -> None:
        service = TavusService(api_key="key")
        result = {"conversation_id": "test", "conversation_url": "https://tavus.daily.co/test", "status": "ended"}
        with patch.object(service, "_request_json", AsyncMock(return_value=result)) as request:
            await service.create_conversation(pal_id="pal", face_id="phoenix45-face", test_mode=True)
        self.assertEqual(request.await_args.kwargs["json_payload"],
                         {"pal_id": "pal", "face_id": "phoenix45-face", "test_mode": True})

    async def test_create_rejects_null_or_missing_join_fields(self) -> None:
        service = TavusService(api_key="key")
        for payload in ({"conversation_id": "id", "conversation_url": None},
                        {"conversation_url": "https://tavus.daily.co/test"}):
            with patch.object(service, "_request_json", AsyncMock(return_value=payload)):
                with self.assertRaises(TavusError):
                    await service.create_conversation(pal_id="pal")

    async def test_end_accepts_empty_success_response(self) -> None:
        request = AsyncMock(return_value=Mock(status_code=200, text=""))
        with patch("services.tavus_service.httpx.AsyncClient") as client_cls:
            client_cls.return_value = _make_client_mock(request=request)
            await TavusService(api_key="key").end_conversation("conv")
        self.assertEqual(request.await_args.kwargs["method"], "POST")
        self.assertTrue(request.await_args.kwargs["url"].endswith("/conv/end"))

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
