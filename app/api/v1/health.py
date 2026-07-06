from fastapi import APIRouter

from app.schemas.pubsub import StatusResponse

router = APIRouter(tags=['health'])


@router.get('/health', response_model=StatusResponse)
def health() -> StatusResponse:
    return StatusResponse(status='running')
