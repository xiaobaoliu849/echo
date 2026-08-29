from __future__ import annotations

from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from main import app
from routers.audio_overview import audio_overview_service


@pytest.fixture
def streaming_client(tmp_path: Path):
    db_file = tmp_path / "audio_stream_test.db"
    out_dir = tmp_path / "audio_stream_out"
    out_dir.mkdir(parents=True, exist_ok=True)

    orig_db = audio_overview_service.db_path
    orig_out = audio_overview_service.output_dir

    audio_overview_service.db_path = db_file
    audio_overview_service.output_dir = out_dir
    audio_overview_service._init_db()

    client = TestClient(app)
    yield client, out_dir

    audio_overview_service.db_path = orig_db
    audio_overview_service.output_dir = orig_out


def test_podcast_audio_full_and_partial_range_streaming(streaming_client):
    client, out_dir = streaming_client

    # 1. Create a known binary payload (4096 bytes)
    payload_bytes = bytes([i % 256 for i in range(4096)])
    audio_file = out_dir / "test_podcast.mp3"
    audio_file.write_bytes(payload_bytes)

    podcast = audio_overview_service.create_podcast(
        topic="Range Streaming Podcast",
        language="zh",
        audio_path=str(audio_file),
        script_lines=[{"role": "A", "text": "Test streaming audio"}],
    )
    podcast_id = podcast["id"]

    # 2. Full Audio Request (200 OK)
    resp = client.get(f"/api/audio-overview/podcasts/{podcast_id}/audio")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "audio/mpeg"
    assert resp.headers.get("accept-ranges") == "bytes"
    assert int(resp.headers["content-length"]) == 4096
    assert resp.content == payload_bytes

    # 3. HTTP Range: bytes=0-499 (First 500 bytes -> 206 Partial Content)
    resp_r1 = client.get(
        f"/api/audio-overview/podcasts/{podcast_id}/audio",
        headers={"Range": "bytes=0-499"},
    )
    assert resp_r1.status_code == 206
    assert resp_r1.headers["content-range"] == "bytes 0-499/4096"
    assert resp_r1.headers["content-length"] == "500"
    assert resp_r1.content == payload_bytes[0:500]

    # 4. HTTP Range: bytes=500-999 (Mid-stream slice -> 206 Partial Content)
    resp_r2 = client.get(
        f"/api/audio-overview/podcasts/{podcast_id}/audio",
        headers={"Range": "bytes=500-999"},
    )
    assert resp_r2.status_code == 206
    assert resp_r2.headers["content-range"] == "bytes 500-999/4096"
    assert resp_r2.headers["content-length"] == "500"
    assert resp_r2.content == payload_bytes[500:1000]

    # 5. HTTP Range: bytes=3000- (Open-ended range -> 206 Partial Content)
    resp_r3 = client.get(
        f"/api/audio-overview/podcasts/{podcast_id}/audio",
        headers={"Range": "bytes=3000-"},
    )
    assert resp_r3.status_code == 206
    assert resp_r3.headers["content-range"] == "bytes 3000-4095/4096"
    assert resp_r3.headers["content-length"] == "1096"
    assert resp_r3.content == payload_bytes[3000:]

    # 6. HTTP Range: bytes=-256 (Suffix range -> 206 Partial Content)
    resp_suffix = client.get(
        f"/api/audio-overview/podcasts/{podcast_id}/audio",
        headers={"Range": "bytes=-256"},
    )
    assert resp_suffix.status_code == 206
    assert resp_suffix.headers["content-range"] == "bytes 3840-4095/4096"
    assert resp_suffix.headers["content-length"] == "256"
    assert resp_suffix.content == payload_bytes[-256:]

    # 7. HTTP Range: Out-of-bounds (416 Range Not Satisfiable)
    resp_oob = client.get(
        f"/api/audio-overview/podcasts/{podcast_id}/audio",
        headers={"Range": "bytes=10000-"},
    )
    assert resp_oob.status_code == 416
    assert resp_oob.headers.get("content-range") in ("*/4096", "bytes */4096")


def test_podcast_audio_streaming_error_handling(streaming_client):
    client, out_dir = streaming_client

    # 1. Non-existent podcast ID
    resp_not_found = client.get("/api/audio-overview/podcasts/88888/audio")
    assert resp_not_found.status_code == 404
    detail = resp_not_found.json()["detail"]
    assert detail["code"] == "AUDIO_OVERVIEW_NOT_FOUND"

    # 2. Podcast record pointing to a missing file on disk
    missing_file_podcast = audio_overview_service.create_podcast(
        topic="Missing Disk File",
        language="zh",
        audio_path=str(out_dir / "deleted_file.mp3"),
        script_lines=[],
    )
    resp_file_missing = client.get(f"/api/audio-overview/podcasts/{missing_file_podcast['id']}/audio")
    assert resp_file_missing.status_code == 404
    assert resp_file_missing.json()["detail"]["code"] == "AUDIO_OVERVIEW_AUDIO_FILE_NOT_FOUND"
    assert resp_file_missing.json()["detail"]["meta"]["podcast_id"] == missing_file_podcast["id"]
