"""Podcast writes must commit metadata and script as one unit."""

import sqlite3

import pytest

from services.audio_overview_service import AudioOverviewService


@pytest.fixture
def service(tmp_path):
    # Exercise the real database without constructing provider clients.
    instance = AudioOverviewService.__new__(AudioOverviewService)
    instance.db_path = tmp_path / "podcasts.db"
    instance._init_db()
    return instance


def test_failed_script_write_rolls_back_metadata_and_previous_script(service):
    original = service.create_podcast(
        topic="Original topic", language="en",
        script_lines=[{"role": "A", "text": "Original line"}],
    )
    with service._connect() as connection:
        connection.execute("""
            CREATE TRIGGER reject_broken_script BEFORE INSERT ON podcast_scripts
            WHEN NEW.content = 'reject me'
            BEGIN SELECT RAISE(ABORT, 'simulated storage failure'); END
        """)
    with pytest.raises(sqlite3.IntegrityError, match="simulated storage failure"):
        service.update_podcast(
            original["id"], topic="New topic", language="zh",
            script_lines=[{"role": "B", "text": "reject me"}],
        )
    assert service.get_podcast(original["id"]) == original


def test_updates_metadata_and_normalized_script_together(service):
    original = service.create_podcast(topic="Original", script_lines=[])
    updated = service.update_podcast(
        original["id"], topic=" Updated ", language="en",
        script_lines=[{"role": "b", "text": " First "}, {"role": "other", "text": "Second"}],
    )
    assert updated["topic"] == "Updated"
    assert updated["language"] == "en"
    assert updated["script_lines"] == [{"role": "B", "text": "First"}, {"role": "A", "text": "Second"}]
    assert service.get_podcast(original["id"]) == updated


def test_script_only_save_preserves_metadata_and_can_clear_lines(service):
    original = service.create_podcast(topic="Keep topic", language="en", script_lines=[{"text": "Old"}])
    assert service.save_script(original["id"], [{"role": "b", "content": " Replacement "}]) == [{"role": "B", "text": "Replacement"}]
    assert service.save_script(original["id"], []) == []
    saved = service.get_podcast(original["id"])
    assert saved["topic"] == "Keep topic"
    assert saved["language"] == "en"
    assert saved["script_lines"] == []


def test_script_save_rejects_missing_podcast_without_creating_orphans(service):
    with pytest.raises(ValueError, match="podcast not found"):
        service.save_script(999, [{"role": "A", "text": "Never stored"}])
    assert service.get_script(999) == []
