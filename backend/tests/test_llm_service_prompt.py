"""Tests for the system-prompt date tag injected by LLMService._normalize_messages.

The tag must stay at date precision: a per-second clock rewrote the system
prompt on every request and defeated upstream prompt caching entirely.
"""
from __future__ import annotations

import re
import unittest

from services.llm_service import LLMService


class NormalizeMessagesPromptTests(unittest.TestCase):
    def test_injected_system_prompt_uses_date_precision_only(self) -> None:
        result = LLMService._normalize_messages([{"role": "user", "content": "你好"}])
        system = result[0]["content"]
        self.assertIn("【系统当前日期】", system)
        # No HH:MM:SS component — that would change every second and bust
        # the upstream prompt cache on every request.
        self.assertIsNone(re.search(r"\d{2}:\d{2}:\d{2}", system))
        # Weekday awareness is preserved for "今天星期几" style questions.
        self.assertIn("星期", system)

    def test_existing_system_message_gets_date_tag_prepended(self) -> None:
        result = LLMService._normalize_messages(
            [
                {"role": "system", "content": "你是一个助手。"},
                {"role": "user", "content": "你好"},
            ]
        )
        self.assertTrue(result[0]["content"].startswith("【系统当前日期】"))
        self.assertIn("你是一个助手。", result[0]["content"])

    def test_date_tag_not_duplicated_on_renormalize(self) -> None:
        tagged = LLMService._normalize_messages([{"role": "user", "content": "你好"}])
        again = LLMService._normalize_messages(tagged)
        content = again[0]["content"]
        # The tag prefix (marker + colon) must appear exactly once; the body
        # text may mention the marker in prose, which is fine.
        self.assertEqual(content.count("【系统当前日期】："), 1)
        self.assertTrue(content.startswith("【系统当前日期】："))

    def test_prompt_is_stable_within_a_day(self) -> None:
        # Two consecutive normalizations must produce byte-identical system
        # prompts — the precondition for prompt caching to work at all.
        first = LLMService._normalize_messages([{"role": "user", "content": "你好"}])
        second = LLMService._normalize_messages([{"role": "user", "content": "你好"}])
        self.assertEqual(first[0]["content"], second[0]["content"])


if __name__ == "__main__":
    unittest.main()
