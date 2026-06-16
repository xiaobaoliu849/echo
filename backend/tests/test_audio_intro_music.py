from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from typing import Any

from services.audio_overview_service import AudioOverviewService


class FakeTtsService:
    def __init__(self, output_dir: Path) -> None:
        self.output_dir = output_dir
        self.calls: list[dict[str, Any]] = []

    async def generate_audio(self, *, text: str, voice: str, rate: str) -> tuple[str, str, bool]:
        self.calls.append({"text": text, "voice": voice, "rate": rate})
        path = self.output_dir / f"segment_{len(self.calls)}.mp3"
        path.write_bytes(b"fake mp3 segment")
        return str(path), "", False


class AudioOverviewIntroMusicTests(unittest.TestCase):
    def test_synthesize_podcast_prepends_generated_intro_music(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            output_dir = root / "audio"
            output_dir.mkdir()
            fake_tts = FakeTtsService(output_dir)
            service = AudioOverviewService(
                db_path=root / "voice_spirit.db",
                output_dir=output_dir,
                tts_service=fake_tts,  # type: ignore[arg-type]
            )
            podcast = service.create_podcast(
                topic="AI research",
                language="zh",
                script_lines=[
                    {"role": "A", "text": "开场"},
                    {"role": "B", "text": "分析"},
                ],
            )
            intro_path = output_dir / "intro.mp3"
            intro_path.write_bytes(b"fake intro")
            captured_segments: list[Path] = []

            def fake_intro(*, style: str, duration_ms: int) -> Path:
                self.assertEqual(style, "bright")
                self.assertEqual(duration_ms, 3200)
                return intro_path

            def fake_merge(
                segment_paths: list[Path],
                output_path: Path,
                *,
                gap_ms: int,
                strategy: str,
            ) -> dict[str, Any]:
                captured_segments.extend(segment_paths)
                output_path.write_bytes(b"merged")
                return {"merge_strategy": strategy, "gap_ms_applied": gap_ms}

            service._create_intro_music_file = fake_intro  # type: ignore[method-assign]
            service._merge_audio_files = fake_merge  # type: ignore[method-assign]

            result = asyncio.run(
                service.synthesize_podcast_audio(
                    int(podcast["id"]),
                    voice_a="voice-a",
                    voice_b="voice-b",
                    intro_music=True,
                    intro_music_style="bright",
                    intro_music_duration_ms=3200,
                    merge_strategy="pydub",
                    gap_ms=400,
                )
            )

            self.assertEqual(captured_segments[0], intro_path)
            self.assertEqual(len(captured_segments), 3)
            self.assertEqual(result["line_count"], 2)
            self.assertTrue(result["intro_music"])
            self.assertEqual(result["intro_music_style"], "bright")
            self.assertEqual(result["intro_music_duration_ms"], 3200)
            self.assertEqual(result["merge_strategy"], "pydub")
            self.assertEqual(result["gap_ms_applied"], 400)


if __name__ == "__main__":
    unittest.main()
