from fastapi import APIRouter

from app.api.v1 import health, queue, webhook

router = APIRouter()
router.include_router(webhook.router)
router.include_router(health.router)
router.include_router(queue.router)
