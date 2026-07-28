from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services.exception_queue import get_pending_reviews, load_queue, mark_reviewed

router = APIRouter(tags=['queue'])


class ReviewRequest(BaseModel):
    approved: bool


@router.get('/queue')
def view_queue() -> list:
    return load_queue()


@router.get('/queue/pending')
def view_pending_queue() -> list:
    return get_pending_reviews()


@router.post('/queue/{case_id}/review')
def review_case(case_id: str, body: ReviewRequest) -> dict:
    updated = mark_reviewed(case_id, body.approved)
    if not updated:
        raise HTTPException(status_code=404, detail=f'case_id not found: {case_id}')
    return {
        'case_id': case_id,
        'status': 'approved' if body.approved else 'rejected',
    }
