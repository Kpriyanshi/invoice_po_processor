from fastapi import APIRouter

from app.services.exception_queue import load_queue

router = APIRouter(tags=['queue'])


@router.get('/queue')
def view_queue() -> list:
    return load_queue()
