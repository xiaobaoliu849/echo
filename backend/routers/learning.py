from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from services.learning_service import LearningItemError, LearningRepository


router = APIRouter()
_repository: LearningRepository | None = None


def get_repository() -> LearningRepository:
    global _repository
    if _repository is None:
        _repository = LearningRepository()
    return _repository


class LearningItemCreate(BaseModel):
    text: str = Field(min_length=1, max_length=300)
    kind: Literal["phrase", "sentence"] = "phrase"
    meaning: str = Field(default="", max_length=300)
    context: str = Field(default="", max_length=600)
    language: str = Field(default="English", max_length=40)
    source_feedback_id: int | None = None


class ReviewSubmit(BaseModel):
    item_id: int
    result: Literal["again", "good"]


@router.post("/items")
def create_item(payload: LearningItemCreate) -> dict[str, Any]:
    try:
        item, created = get_repository().add_item(**payload.model_dump())
    except LearningItemError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"item": item, "created": created}


@router.get("/items")
def list_items(limit: int = Query(200, ge=1, le=1000)) -> dict[str, Any]:
    return {"items": get_repository().list_items(limit=limit)}


@router.delete("/items/{item_id}")
def delete_item(item_id: int) -> dict[str, Any]:
    if not get_repository().delete_item(item_id):
        raise HTTPException(status_code=404, detail="Item not found.")
    return {"deleted": True}


@router.get("/reviews/due")
def due_reviews(limit: int = Query(20, ge=1, le=200)) -> dict[str, Any]:
    repo = get_repository()
    return {"items": repo.due_items(limit=limit), "stats": repo.stats()}


@router.post("/reviews")
def submit_review(payload: ReviewSubmit) -> dict[str, Any]:
    repo = get_repository()
    item = repo.review(payload.item_id, payload.result)
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found.")
    return {"item": item, "stats": repo.stats()}


@router.get("/stats")
def learning_stats() -> dict[str, Any]:
    return get_repository().stats()
