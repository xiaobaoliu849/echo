from __future__ import annotations

import asyncio
import os
import unittest
from typing import Any
from unittest.mock import MagicMock, patch

import httpx

from main import create_app


class PdfExtractTests(unittest.TestCase):
    def setUp(self) -> None:
        self._auth_env_patcher = patch.dict(
            os.environ,
            {"VOICESPIRIT_API_TOKEN": "test-api-token"},
            clear=False,
        )
        self._auth_env_patcher.start()
        self.app = create_app()

    def tearDown(self) -> None:
        self._auth_env_patcher.stop()

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        if method.upper() in {"POST", "PUT", "PATCH", "DELETE"} and path.startswith("/api/"):
            headers = dict(kwargs.get("headers") or {})
            if "Authorization" not in headers:
                headers["Authorization"] = "Bearer test-api-token"
                kwargs["headers"] = headers

        async def runner() -> httpx.Response:
            transport = httpx.ASGITransport(app=self.app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                return await client.request(method, path, **kwargs)

        return asyncio.run(runner())

    def test_extract_pdf_validation_error(self) -> None:
        files = {"file": ("test.txt", b"some text content", "text/plain")}
        response = self._request("POST", "/api/tts/extract-pdf", files=files)
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertEqual(data["detail"]["code"], "PDF_EXTRACT_BAD_REQUEST")
        self.assertIn("Only PDF files are supported", data["detail"]["message"])

    def test_extract_pdf_success_mocked(self) -> None:
        mock_page1 = MagicMock()
        mock_page1.extract_text.return_value = "Hello World"
        mock_page2 = MagicMock()
        mock_page2.extract_text.return_value = "This is page 2"

        mock_reader = MagicMock()
        mock_reader.is_encrypted = False
        mock_reader.pages = [mock_page1, mock_page2]

        with patch("pypdf.PdfReader", return_value=mock_reader):
            files = {"file": ("test.pdf", b"%PDF-1.4 mock content", "application/pdf")}
            response = self._request("POST", "/api/tts/extract-pdf", files=files)

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["filename"], "test.pdf")
        self.assertEqual(data["page_count"], 2)
        self.assertEqual(data["text"], "Hello World\n\nThis is page 2")
        self.assertTrue(data["has_text"])

    def test_extract_pdf_corrupt_file_returns_400(self) -> None:
        # A corrupt/unreadable PDF is a client-input problem: 400, not 500.
        with patch("pypdf.PdfReader", side_effect=Exception("Corrupt PDF file")):
            files = {"file": ("test.pdf", b"corrupt bytes", "application/pdf")}
            response = self._request("POST", "/api/tts/extract-pdf", files=files)

        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertEqual(data["detail"]["code"], "PDF_EXTRACT_BAD_REQUEST")
        self.assertIn("Corrupt PDF file", data["detail"]["message"])

    def test_extract_pdf_encrypted_returns_400(self) -> None:
        mock_reader = MagicMock()
        mock_reader.is_encrypted = True

        with patch("pypdf.PdfReader", return_value=mock_reader), \
             patch.object(mock_reader, "decrypt", side_effect=Exception("hard lock")):
            files = {"file": ("locked.pdf", b"%PDF-1.4 encrypted", "application/pdf")}
            response = self._request("POST", "/api/tts/extract-pdf", files=files)

        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertEqual(data["detail"]["code"], "PDF_EXTRACT_ENCRYPTED")

    def test_polish_pdf_text_success_mocked(self) -> None:
        async def fake_chat_completion(*args: Any, **kwargs: Any) -> dict[str, Any]:
            return {"provider": "MockProvider", "model": "mock-model", "reply": "This is polished text."}

        with patch("services.llm_service.LLMService.chat_completion", new=fake_chat_completion):
            response = self._request(
                "POST",
                "/api/tts/polish-pdf-text",
                json={"text": "raw text with math symbols $f(a) | b$"}
            )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["provider"], "MockProvider")
        self.assertEqual(data["model"], "mock-model")
        self.assertEqual(data["polished_text"], "This is polished text.")

    def test_polish_pdf_text_bad_request(self) -> None:
        response = self._request("POST", "/api/tts/polish-pdf-text", json={"text": "   "})
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertEqual(data["detail"]["code"], "TTS_POLISH_BAD_REQUEST")

