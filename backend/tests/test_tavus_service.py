from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, Mock, patch

import services.tavus_service as tavus_module
from services.tavus_service import TavusError, TavusService


def _make_service(api_key: str = "tavus-key") -> TavusService:
    return TavusService(api_key=api_key)


def _make_client_mock(**method_mocks) -> Mock:
    client = AsyncMock()
    client.__aenter__.return_value = client
    client.__aexit__.return_value = None
    for name, mocked in method_mocks.items():
        setattr(client, name, mocked)
    return client


def _mock_response(status_code: int, json_data=None, text: str = "") -> Mock:
    resp = Mock()
    resp.status_code = status_code
    resp.text = text
    if json_data is not None:
        resp.json.return_value = json_data
    else:
        resp.json.side_effect = ValueError("no body")
    return resp


class TavusServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        # Clear the module-level list cache between tests so caching does not
        # bleed across unrelated test cases.
        tavus_module._list_cache.clear()

    async def test_create_conversation_sends_pal_id_and_api_key(self) -> None:
        service = _make_service("tavus-key")

        response = _mock_response(200, {
            "conversation_id": "conv-1",
            "conversation_url": "https://tavus.daily.co/room?t=token",
            "status": "started",
        })
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
        service = _make_service()
        response = _mock_response(200, {"conversation_id": "conv-1"})
        request = AsyncMock(return_value=response)

        with patch("services.tavus_service.httpx.AsyncClient") as client_cls:
            client_cls.return_value = _make_client_mock(request=request)
            with self.assertRaises(TavusError) as ctx:
                await service.create_conversation(pal_id="pal-123")

        self.assertEqual(ctx.exception.code, "TAVUS_RESPONSE_INVALID")

    async def test_create_conversation_maps_upstream_error(self) -> None:
        service = _make_service()
        response = _mock_response(401, text="invalid api key")
        request = AsyncMock(return_value=response)

        with patch("services.tavus_service.httpx.AsyncClient") as client_cls:
            client_cls.return_value = _make_client_mock(request=request)
            with self.assertRaises(TavusError) as ctx:
                await service.create_conversation(pal_id="pal-123")

        self.assertEqual(ctx.exception.code, "TAVUS_UPSTREAM_ERROR")
        self.assertEqual(ctx.exception.upstream_status, 401)

    async def test_list_pals_returns_items_from_payload(self) -> None:
        service = _make_service()
        response = _mock_response(200, {"pals": [{"pal_id": "pal-1", "pal_name": "Mia"}]})
        request = AsyncMock(return_value=response)

        with patch("services.tavus_service.httpx.AsyncClient") as client_cls:
            client_cls.return_value = _make_client_mock(request=request)
            pals = await service.list_pals()

        self.assertEqual(pals, [{"pal_id": "pal-1", "pal_name": "Mia"}])
        _, kwargs = request.call_args
        self.assertEqual(kwargs["url"], "https://tavusapi.com/v2/pals?limit=100&page=1")

    async def test_list_faces_returns_face_items(self) -> None:
        service = _make_service()
        response = _mock_response(200, {
            "data": [
                {
                    "face_id": "rc9cff32ceba",
                    "face_name": "Rio",
                    "model_name": "phoenix-4.5",
                    "status": "completed",
                }
            ]
        })
        request = AsyncMock(return_value=response)

        with patch("services.tavus_service.httpx.AsyncClient") as client_cls:
            client_cls.return_value = _make_client_mock(request=request)
            faces = await service.list_faces()

        self.assertEqual(faces[0]["face_id"], "rc9cff32ceba")
        self.assertEqual(faces[0]["model_name"], "phoenix-4.5")
        _, kwargs = request.call_args
        self.assertEqual(kwargs["url"], "https://tavusapi.com/v2/faces?limit=100&page=1")

    async def test_end_conversation_treats_404_as_already_ended(self) -> None:
        service = _make_service()
        gone = _mock_response(404, text="not found")
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
                service = _make_service()
                pages = [{"data": [{id_key: "first"}], "total_count": 2},
                         {"data": [{id_key: "second"}], "total_count": 2}]
                with patch.object(service, "_request_json", AsyncMock(side_effect=pages)) as request:
                    result = await getattr(service, method)()
                self.assertEqual([item[id_key] for item in result], ["first", "second"])
                self.assertEqual(request.await_args.args, ("GET", f"/v2/{path}?limit=100&page=2"))

    async def test_invalid_list_does_not_silently_become_empty(self) -> None:
        service = _make_service()
        for payload in ({"unexpected": []}, {"data": None}):
            with patch.object(service, "_request_json", AsyncMock(return_value=payload)):
                with self.assertRaises(TavusError):
                    await service.list_pals()

    async def test_empty_page_stops_when_total_changes(self) -> None:
        service = _make_service()
        with patch.object(service, "_request_json", AsyncMock(return_value={"data": [], "total_count": 10})) as request:
            self.assertEqual(await service.list_faces(), [])
            request.assert_awaited_once()

    async def test_face_override_and_free_test_mode_are_forwarded(self) -> None:
        service = _make_service()
        result = {"conversation_id": "test", "conversation_url": "https://tavus.daily.co/test", "status": "ended"}
        with patch.object(service, "_request_json", AsyncMock(return_value=result)) as request:
            await service.create_conversation(pal_id="pal", face_id="phoenix45-face", test_mode=True)
        self.assertEqual(request.await_args.kwargs["json_payload"],
                         {"pal_id": "pal", "face_id": "phoenix45-face", "test_mode": True})

    async def test_create_rejects_null_or_missing_join_fields(self) -> None:
        service = _make_service()
        for payload in ({"conversation_id": "id", "conversation_url": None},
                        {"conversation_url": "https://tavus.daily.co/test"}):
            with patch.object(service, "_request_json", AsyncMock(return_value=payload)):
                with self.assertRaises(TavusError):
                    await service.create_conversation(pal_id="pal")

    async def test_end_accepts_empty_success_response(self) -> None:
        request = AsyncMock(return_value=_mock_response(200, text=""))
        with patch("services.tavus_service.httpx.AsyncClient") as client_cls:
            client_cls.return_value = _make_client_mock(request=request)
            await _make_service().end_conversation("conv")
        self.assertEqual(request.await_args.kwargs["method"], "POST")
        self.assertTrue(request.await_args.kwargs["url"].endswith("/conv/end"))

    async def test_end_conversation_raises_on_upstream_failure(self) -> None:
        service = _make_service()
        response = _mock_response(500, text="boom")
        request = AsyncMock(return_value=response)

        with patch("services.tavus_service.httpx.AsyncClient") as client_cls:
            client_cls.return_value = _make_client_mock(request=request)
            with self.assertRaises(TavusError) as ctx:
                await service.end_conversation("conv-1")

        self.assertEqual(ctx.exception.upstream_status, 500)

    # --- Cache behaviour ---

    async def test_list_pals_uses_cache_on_second_call(self) -> None:
        service = _make_service()
        resp = _mock_response(200, {"pals": [{"pal_id": "p1", "pal_name": "A"}]})
        request = AsyncMock(return_value=resp)

        with patch("services.tavus_service.httpx.AsyncClient") as client_cls:
            client_cls.return_value = _make_client_mock(request=request)
            first = await service.list_pals()
            second = await service.list_pals()

        # Network should only have been called once; second result from cache.
        request.assert_awaited_once()
        self.assertEqual(first, second)

    async def test_list_faces_uses_cache_on_second_call(self) -> None:
        service = _make_service()
        resp = _mock_response(200, {"data": [{"face_id": "f1", "face_name": "R"}]})
        request = AsyncMock(return_value=resp)

        with patch("services.tavus_service.httpx.AsyncClient") as client_cls:
            client_cls.return_value = _make_client_mock(request=request)
            first = await service.list_faces()
            second = await service.list_faces()

        request.assert_awaited_once()
        self.assertEqual(first, second)

    async def test_cache_is_keyed_per_api_key(self) -> None:
        svc_a = _make_service("key-a")
        svc_b = _make_service("key-b")
        resp_a = _mock_response(200, {"pals": [{"pal_id": "a"}]})
        resp_b = _mock_response(200, {"pals": [{"pal_id": "b"}]})
        req_a = AsyncMock(return_value=resp_a)
        req_b = AsyncMock(return_value=resp_b)

        with patch("services.tavus_service.httpx.AsyncClient") as client_cls:
            client_cls.return_value = _make_client_mock(request=req_a)
            pals_a = await svc_a.list_pals()

        with patch("services.tavus_service.httpx.AsyncClient") as client_cls:
            client_cls.return_value = _make_client_mock(request=req_b)
            pals_b = await svc_b.list_pals()

        self.assertEqual(pals_a[0]["pal_id"], "a")
        self.assertEqual(pals_b[0]["pal_id"], "b")

    async def test_expired_catalogs_are_removed_on_next_lookup(self) -> None:
        first = _make_service("old-key")
        second = _make_service("new-key")
        with patch("services.tavus_service.time.monotonic", return_value=100):
            with patch.object(first, "_request_json", AsyncMock(return_value={"pals": [{"pal_id": "old"}]})):
                await first.list_pals()
            with patch.object(first, "_request_json", AsyncMock(return_value={"faces": [{"face_id": "old-face"}]})):
                await first.list_faces()
        with patch("services.tavus_service.time.monotonic", return_value=401):
            with patch.object(second, "_request_json", AsyncMock(return_value={"pals": [{"pal_id": "new"}]})):
                await second.list_pals()

        self.assertEqual(list(tavus_module._list_cache), [f"pals:{second.api_key}:{second.api_url}"])

    async def test_catalog_cache_evicts_oldest_key_at_capacity(self) -> None:
        services = [_make_service(f"key-{index}") for index in range(3)]
        with patch.object(tavus_module, "_LIST_CACHE_MAX_ENTRIES", 2):
            for service in services:
                with patch.object(service, "_request_json", AsyncMock(return_value={"pals": []})):
                    await service.list_pals()
            self.assertEqual(len(tavus_module._list_cache), 2)
            self.assertNotIn(f"pals:{services[0].api_key}:{services[0].api_url}", tavus_module._list_cache)
            with patch.object(services[0], "_request_json", AsyncMock(return_value={"pals": [{"pal_id": "fetched-again"}]})) as request:
                self.assertEqual((await services[0].list_pals())[0]["pal_id"], "fetched-again")
                request.assert_awaited_once()
            self.assertEqual(len(tavus_module._list_cache), 2)


if __name__ == "__main__":
    unittest.main()
