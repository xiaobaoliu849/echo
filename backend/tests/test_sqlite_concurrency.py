from __future__ import annotations

import concurrent.futures
import sqlite3
import threading
import time
import uuid
from pathlib import Path
import pytest

from services.db_utils import ClosingConnection, get_db_connection
from services.audio_overview_service import AudioOverviewService
from services.voice_agent_session_repository import VoiceAgentSessionRepository
from services.agent_run_repository import AgentRunRepository
from services.audio_agent_repository import AudioAgentRepository
from services.user_auth_service import UserAuthService


def test_closing_connection_lifecycle(tmp_path: Path):
    db_file = tmp_path / "test_lifecycle.db"

    # 1. Normal context manager exit: commit changes and close connection
    conn = get_db_connection(db_file)
    assert isinstance(conn, ClosingConnection)
    assert isinstance(conn, sqlite3.Connection)

    with conn:
        conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT)")
        conn.execute("INSERT INTO items (name) VALUES (?)", ("item_one",))

    # Connection should now be closed
    with pytest.raises(sqlite3.ProgrammingError, match="Cannot operate on a closed database"):
        conn.execute("SELECT * FROM items")

    # Re-open and verify committed data and Row factory access
    with get_db_connection(db_file) as conn2:
        row = conn2.execute("SELECT name FROM items WHERE id = 1").fetchone()
        assert row is not None
        assert row["name"] == "item_one"
        assert row[0] == "item_one"

    # 2. Exception in context manager: rollback changes and close connection
    conn3 = get_db_connection(db_file)
    with pytest.raises(RuntimeError, match="Simulated crash"):
        with conn3:
            conn3.execute("INSERT INTO items (name) VALUES (?)", ("item_two",))
            raise RuntimeError("Simulated crash")

    # Connection must be closed
    with pytest.raises(sqlite3.ProgrammingError, match="Cannot operate on a closed database"):
        conn3.execute("SELECT * FROM items")

    # Verify rollback
    with get_db_connection(db_file) as conn4:
        rows = conn4.execute("SELECT name FROM items").fetchall()
        names = [r["name"] for r in rows]
        assert "item_two" not in names
        assert names == ["item_one"]


def test_db_utils_pragmas_and_directory_creation(tmp_path: Path):
    nested_db_file = tmp_path / "deep" / "nested" / "dir" / "pragmas.db"

    # Verify get_db_connection creates parent directories and applies WAL + busy_timeout
    with get_db_connection(nested_db_file, busy_timeout_ms=5000, wal_mode=True) as conn:
        journal_mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert str(journal_mode).upper() == "WAL"

        busy_timeout = conn.execute("PRAGMA busy_timeout").fetchone()[0]
        assert busy_timeout == 5000


def test_concurrent_multi_repository_stress(tmp_path: Path):
    db_file = tmp_path / "multi_repo_stress.db"
    output_dir = tmp_path / "audio_out"
    output_dir.mkdir(parents=True, exist_ok=True)

    # Instantiate 5 repositories sharing the same SQLite DB file
    audio_overview_svc = AudioOverviewService(db_path=db_file, output_dir=output_dir)
    voice_repo = VoiceAgentSessionRepository(db_path=db_file)
    agent_run_repo = AgentRunRepository(db_path=db_file)
    audio_agent_repo = AudioAgentRepository(db_path=db_file)
    user_auth_svc = UserAuthService(db_path=db_file)

    num_threads = 16
    ops_per_thread = 10
    errors: list[str] = []
    errors_lock = threading.Lock()

    def run_worker(thread_idx: int):
        try:
            for i in range(ops_per_thread):
                op_type = (thread_idx + i) % 5

                if op_type == 0:
                    podcast = audio_overview_svc.create_podcast(
                        topic=f"Podcast {thread_idx}_{i}",
                        language="zh",
                        script_lines=[{"role": "A", "text": "Line 1"}, {"role": "B", "text": "Line 2"}],
                        audio_path=f"/fake/audio_{thread_idx}_{i}.mp3",
                    )
                    pid = podcast["id"]
                    fetched = audio_overview_svc.get_podcast(pid)
                    assert fetched is not None
                    assert fetched["topic"] == f"Podcast {thread_idx}_{i}"

                elif op_type == 1:
                    sess = voice_repo.create_session(
                        provider="doubao",
                        model="doubao-pro",
                        voice="zh_female_1",
                    )
                    sid = sess["id"]
                    voice_repo.add_session_event(
                        session_id=sid,
                        event_type="user_speech",
                        source="user",
                        payload={"text": f"Message {thread_idx}_{i}"},
                    )
                    retrieved_sess = voice_repo.get_session(sid)
                    assert retrieved_sess is not None

                elif op_type == 2:
                    run_id = f"run_{thread_idx}_{i}_{uuid.uuid4().hex[:6]}"
                    agent_run_repo.upsert_run(
                        run_id=run_id,
                        run_type="audio_researcher",
                        source_kind="audio_agent",
                        source_run_id=f"src_{run_id}",
                        title=f"Run {thread_idx}_{i}",
                        status="running",
                    )
                    run_data = agent_run_repo.get_run(run_id)
                    assert run_data is not None
                    assert run_data["id"] == run_id

                elif op_type == 3:
                    email = f"user_{thread_idx}_{i}_{uuid.uuid4().hex[:6]}@example.com"
                    user_auth_svc.register_user(
                        email=email,
                        password="Password123!",
                    )
                    user = user_auth_svc.authenticate_user(
                        email=email,
                        password="Password123!",
                    )
                    assert user is not None
                    assert user["email"] == email

                elif op_type == 4:
                    task_run = audio_agent_repo.create_run(
                        topic=f"Topic {thread_idx}_{i}",
                        language="zh",
                        status="running",
                        current_step="init",
                        provider="mock",
                        model="mock-v1",
                        use_memory=False,
                        input_payload={"test": True},
                    )
                    run_id = task_run["id"]
                    task_res = audio_agent_repo.get_run(run_id)
                    assert task_res is not None

        except Exception as e:
            with errors_lock:
                errors.append(f"Thread {thread_idx} error: {type(e).__name__}: {e}")

    with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = [executor.submit(run_worker, idx) for idx in range(num_threads)]
        concurrent.futures.wait(futures)

    assert not errors, f"Concurrent repository operations encountered errors: {errors}"


def test_concurrent_readers_writers_isolation(tmp_path: Path):
    db_file = tmp_path / "readers_writers.db"

    with get_db_connection(db_file) as conn:
        conn.execute("CREATE TABLE counter (id INTEGER PRIMARY KEY, count INT)")
        conn.execute("INSERT INTO counter (id, count) VALUES (1, 0)")

    stop_event = threading.Event()
    read_samples: list[int] = []
    read_errors: list[str] = []

    def reader_task():
        while not stop_event.is_set():
            try:
                with get_db_connection(db_file) as conn:
                    row = conn.execute("SELECT count FROM counter WHERE id = 1").fetchone()
                    if row:
                        read_samples.append(row["count"])
            except Exception as e:
                read_errors.append(f"Reader error: {type(e).__name__}: {e}")
            time.sleep(0.001)

    def writer_task(writer_id: int):
        for _ in range(30):
            with get_db_connection(db_file) as conn:
                conn.execute("UPDATE counter SET count = count + 1 WHERE id = 1")
            time.sleep(0.002)

    reader_thread = threading.Thread(target=reader_task)
    reader_thread.start()

    writers = [threading.Thread(target=writer_task, args=(i,)) for i in range(4)]
    for w in writers:
        w.start()
    for w in writers:
        w.join()

    stop_event.set()
    reader_thread.join()

    assert not read_errors, f"Concurrent reader experienced errors: {read_errors}"
    assert len(read_samples) > 10

    with get_db_connection(db_file) as conn:
        final_count = conn.execute("SELECT count FROM counter WHERE id = 1").fetchone()["count"]
        assert final_count == 4 * 30
