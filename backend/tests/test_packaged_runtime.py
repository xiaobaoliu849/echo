import sys

from fastapi.testclient import TestClient

from services import config_loader
from services.realtime_memory_session import _resolve_pending_cache_path


def test_explicit_data_directory_never_migrates_developer_secrets(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    (source / "config.json").write_text('{"secret": "must-not-copy"}')
    monkeypatch.setattr(config_loader, "PROJECT_ROOT", source)
    monkeypatch.setenv("ECHO_DATA_DIR", str(tmp_path / "profile"))
    assert not config_loader.get_data_file_path("config.json").exists()
    assert _resolve_pending_cache_path().parent == tmp_path / "profile"


def test_frozen_runtime_never_migrates_developer_secrets(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(config_loader, "PROJECT_ROOT", tmp_path)
    (tmp_path / "config.json").write_text('{"secret": "must-not-copy"}')
    monkeypatch.setenv("ECHO_DATA_DIR", str(tmp_path / "profile"))
    assert not config_loader.get_data_file_path("config.json").exists()


def test_desktop_startup_identity_and_same_origin_assets(tmp_path, monkeypatch):
    from main import create_app

    dist = tmp_path / "frontend"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text('<div id="root"></div><script src="./assets/app.js"></script>')
    (dist / "assets" / "app.js").write_text('console.log("ready")')
    monkeypatch.setenv("VOICESPIRIT_FRONTEND_DIST", str(dist))
    monkeypatch.setenv("ECHO_DATA_DIR", str(tmp_path / "profile"))
    monkeypatch.setenv("ECHO_DESKTOP_INSTANCE_ID", "owned-backend")
    with TestClient(create_app()) as client:
        assert client.get("/").json()["desktop_instance_id"] == "owned-backend"
        assert client.get("/app/").status_code == 200
        assert client.get("/app/assets/app.js").text == 'console.log("ready")'
        assert client.get("/app/assets/missing.js").status_code == 404


def test_electron_diagnostics_use_its_profile(tmp_path, monkeypatch):
    from services.desktop_diagnostics_service import get_runtime_dir

    monkeypatch.setenv("ECHO_DESKTOP_INSTANCE_ID", "owned-backend")
    monkeypatch.setenv("ECHO_DATA_DIR", str(tmp_path))
    assert get_runtime_dir() == tmp_path


def test_tts_default_cache_is_outside_read_only_installation(tmp_path, monkeypatch):
    from services.tts_service import TTSService

    monkeypatch.setenv("ECHO_DATA_DIR", str(tmp_path))
    service = TTSService()
    assert service.output_dir == tmp_path / "temp_audio"
    assert service.output_dir.is_dir()
