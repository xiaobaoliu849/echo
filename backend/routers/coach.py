from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query

from services.speaking_coach import CoachRepository


router = APIRouter()
_repository: CoachRepository | None = None


def get_repository() -> CoachRepository:
    global _repository
    if _repository is None:
        _repository = CoachRepository()
    return _repository


@router.get("/feedback")
def list_feedback(
    limit: int = Query(50, ge=1, le=500),
    verdict: Literal["good", "improve"] | None = None,
    session_id: str | None = Query(None, max_length=128),
) -> dict[str, Any]:
    items = get_repository().list_recent(limit=limit, verdict=verdict, session_id=session_id)
    return {"items": items}


@router.get("/summary")
def feedback_summary() -> dict[str, Any]:
    return get_repository().summary()


@router.delete("/feedback/{item_id}")
def delete_feedback(item_id: int) -> dict[str, Any]:
    if not get_repository().delete(item_id):
        raise HTTPException(status_code=404, detail="Feedback not found.")
    return {"deleted": True}
