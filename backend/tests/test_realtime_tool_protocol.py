import unittest

from services.realtime_tool_protocol import (
    RealtimeToolCall,
    dashscope_supports_native_tools,
    dashscope_tool_declarations,
    native_tool_declarations,
    parse_tool_arguments,
    tool_call_to_request,
)


class RealtimeToolProtocolTests(unittest.TestCase):
    def test_declarations_expose_only_non_side_effecting_tools(self) -> None:
        names = [item["name"] for item in native_tool_declarations()]
        self.assertEqual(names, ["search_web", "recall_memory"])
        self.assertNotIn("translate_text", names)
        self.assertNotIn("summarize_transcript", names)
        self.assertNotIn("synthesize_tts", names)
        self.assertNotIn("create_audio_agent_run", names)

    def test_dashscope_declarations_use_nested_function_shape(self) -> None:
        tools = dashscope_tool_declarations()
        self.assertEqual(tools[0]["type"], "function")
        self.assertEqual(tools[0]["function"]["name"], "search_web")
        self.assertNotIn("name", tools[0])

    def test_model_support_is_explicitly_current_qwen_realtime_only(self) -> None:
        self.assertTrue(dashscope_supports_native_tools("qwen3.5-omni-plus-realtime"))
        self.assertTrue(dashscope_supports_native_tools("qwen3.5-omni-flash-realtime-2026-03-15"))
        self.assertTrue(dashscope_supports_native_tools("qwen-audio-3.0-realtime-plus"))
        self.assertTrue(dashscope_supports_native_tools("qwen-audio-3.0-realtime-flash"))
        self.assertFalse(dashscope_supports_native_tools("qwen3-omni-flash-realtime-2025-12-01"))
        self.assertFalse(dashscope_supports_native_tools("qwen-audio-2.0-realtime-plus"))
        self.assertFalse(dashscope_supports_native_tools("qwen3.5-omni-plus"))
        self.assertFalse(dashscope_supports_native_tools("custom-qwen3.5-omni-plus-realtime"))
        self.assertFalse(dashscope_supports_native_tools("qwen3.5-omni-plus-realtime-fake"))
        self.assertFalse(dashscope_supports_native_tools("qwen3.5-omni-plus-livetranslate"))

    def test_arguments_require_json_object_and_required_fields(self) -> None:
        self.assertEqual(parse_tool_arguments('{"query":"weather"}'), {"query": "weather"})
        with self.assertRaisesRegex(ValueError, "valid JSON"):
            parse_tool_arguments("{")
        with self.assertRaisesRegex(ValueError, "JSON object"):
            parse_tool_arguments("[]")
        with self.assertRaisesRegex(ValueError, "query"):
            tool_call_to_request(RealtimeToolCall("Google", "call-1", "search_web", {}))

    def test_translation_arguments_are_normalized_for_existing_executor(self) -> None:
        request = tool_call_to_request(
            RealtimeToolCall(
                "Google",
                "call-translate",
                "translate_text",
                {"text": "你好", "target_language": "English"},
            )
        )
        self.assertEqual(request.query, "你好\n目标语言:English")

    def test_missing_call_id_and_unknown_tool_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "provider_call_id"):
            tool_call_to_request(RealtimeToolCall("Google", "", "search_web", {"query": "x"}))
        with self.assertRaisesRegex(ValueError, "Unsupported realtime tool"):
            tool_call_to_request(RealtimeToolCall("Google", "call-2", "delete_files", {}))


if __name__ == "__main__":
    unittest.main()
