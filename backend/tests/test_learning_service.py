from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers import learning as learning_router
from services.learning_service import (
    REVIEW_INTERVAL_DAYS,
    LearningItemError,
    LearningRepository,
    next_schedule,
    normalize_item_text,
)

NOW = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)


def test_normalize_item_text() -> None:
    assert normalize_item_text("  Thoroughly   Enjoyed! ") == "thoroughly enjoyed"
    assert normalize_item_text("ＡＢＣ，") == "abc"
    assert normalize_item_text("!!!") == ""


def test_next_schedule_progression_and_reset() -> None:
    step, due = next_schedule(0, "good", now=NOW)
    assert (step, due) == (1, NOW + timedelta(days=REVIEW_INTERVAL_DAYS[1]))
    step, due = next_schedule(len(REVIEW_INTERVAL_DAYS), "good", now=NOW)
    assert step == len(REVIEW_INTERVAL_DAYS)
    assert due == NOW + timedelta(days=REVIEW_INTERVAL_DAYS[-1])
    assert next_schedule(4, "again", now=NOW) == (0, NOW + timedelta(days=REVIEW_INTERVAL_DAYS[0]))


def test_repository_save_dedupe_review_and_stats(tmp_path) -> None:
    repo = LearningRepository(db_path=tmp_path / "learn.db")
    item, created = repo.add_item(text="thoroughly enjoyed", meaning="非常享受", source_feedback_id=3, now=NOW)
    assert created and item["due_at"] == "2026-10-07T12:00:00Z"
    again, created_again = repo.add_item(text="Thoroughly enjoyed.", now=NOW)
    assert not created_again and again["id"] == item["id"]
    # Same text as a different kind is a separate card.
    _, created_sentence = repo.add_item(text="thoroughly enjoyed", kind="sentence", now=NOW)
    assert created_sentence

    with pytest.raises(LearningItemError):
        repo.add_item(text="   ", now=NOW)
    with pytest.raises(LearningItemError):
        repo.add_item(text="x", kind="poem", now=NOW)

    assert len(repo.due_items(now=NOW)) == 2
    reviewed = repo.review(item["id"], "good", now=NOW)
    assert reviewed is not None
    assert reviewed["review_step"] == 1
    assert reviewed["due_at"] == "2026-10-10T12:00:00Z"
    assert [i["kind"] for i in repo.due_items(now=NOW)] == ["sentence"]
    assert len(repo.due_items(now=NOW + timedelta(days=3))) == 2

    lapsed = repo.review(item["id"], "again", now=NOW)
    assert lapsed is not None and lapsed["review_step"] == 0 and lapsed["lapse_count"] == 1
    assert lapsed["review_count"] == 2
    assert repo.review(9999, "good", now=NOW) is None
    with pytest.raises(LearningItemError):
        repo.review(item["id"], "maybe", now=NOW)

    stats = repo.stats(now=NOW)
    assert stats["total_items"] == 2
    assert stats["due_now"] == 1
    assert stats["reviewed_today"] == 2
    assert stats["recalled_today"] == 1

    assert repo.delete_item(item["id"]) is True
    assert repo.delete_item(item["id"]) is False
    assert repo.stats(now=NOW)["reviewed_today"] == 0


def test_learning_router_flow(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(learning_router, "_repository", LearningRepository(db_path=tmp_path / "api.db"))
    app = FastAPI()
    app.include_router(learning_router.router, prefix="/api/learning")
    client = TestClient(app)

    created = client.post("/api/learning/items", json={"text": "a real treat", "meaning": "一次享受"})
    assert created.status_code == 200 and created.json()["created"] is True
    item_id = created.json()["item"]["id"]
    assert client.post("/api/learning/items", json={"text": "A real treat"}).json()["created"] is False
    assert client.post("/api/learning/items", json={"text": "x", "kind": "poem"}).status_code == 422

    due = client.get("/api/learning/reviews/due").json()
    assert [i["id"] for i in due["items"]] == [item_id]
    assert due["stats"]["due_now"] == 1

    reviewed = client.post("/api/learning/reviews", json={"item_id": item_id, "result": "good"})
    assert reviewed.status_code == 200
    assert reviewed.json()["stats"]["due_now"] == 0
    assert client.post("/api/learning/reviews", json={"item_id": 999, "result": "good"}).status_code == 404

    assert len(client.get("/api/learning/items").json()["items"]) == 1
    assert client.delete(f"/api/learning/items/{item_id}").status_code == 200
    assert client.delete(f"/api/learning/items/{item_id}").status_code == 404
