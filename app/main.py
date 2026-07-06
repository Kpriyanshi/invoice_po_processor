from fastapi import FastAPI

from app.api.v1.router import router as v1_router
from app.core.logging import setup_logging


def create_app() -> FastAPI:
    setup_logging()

    app = FastAPI(
        title='Invoice and PO Processing',
        description='Gmail Pub/Sub webhook for invoice classification and storage',
        version='1.0.0',
    )

    app.include_router(v1_router)

    return app


app = create_app()
