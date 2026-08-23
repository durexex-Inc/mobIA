from fastapi import Request

from mobia.domain.messages.service import IngestionService
from mobia.infra.db import get_sessionmaker


def get_ingestion_service(request: Request) -> IngestionService:
    return IngestionService(get_sessionmaker(), getattr(request.app.state, "redis_pool", None))
