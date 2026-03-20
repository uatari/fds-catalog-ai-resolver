from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any, Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .db import JobStore
from .llm import AIResolver
from .mcp_client import CatalogMcpClient
from .settings import Settings, load_settings
from .worker import Worker


class ConversationItem(BaseModel):
    role: Literal["user", "assistant", "system"] = "user"
    text: str


class ResolveJobRequest(BaseModel):
    query: str = Field(min_length=1)
    family_name: str | None = None
    unit_name: str | None = None
    conversation: list[ConversationItem] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AppState:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.store = JobStore(settings.sqlite_path)
        self.mcp_client = CatalogMcpClient(settings)
        self.resolver = AIResolver(settings, self.mcp_client, self.store)
        self.worker = Worker(settings, self.store, self.mcp_client, self.resolver)


def create_app() -> FastAPI:
    settings = load_settings()
    logging.basicConfig(level=getattr(logging, settings.log_level, logging.INFO))

    state = AppState(settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        if state.settings.run_worker:
            await state.worker.start()
        yield
        if state.settings.run_worker:
            await state.worker.stop()

    app = FastAPI(title="FDS Catalog AI Resolver", version="0.1.0", lifespan=lifespan)
    app.state.container = state

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {
            "ok": True,
            "worker_enabled": state.settings.run_worker,
            "sqlite_path": str(state.settings.sqlite_path),
            "catalog_mcp_cwd": str(state.settings.catalog_mcp_cwd),
            "model": state.settings.openai_model,
        }

    @app.post("/jobs/resolve")
    async def create_resolve_job(body: ResolveJobRequest) -> dict[str, Any]:
        if not state.settings.openai_api_key:
            raise HTTPException(status_code=500, detail="OPENAI_API_KEY is not configured")
        job = state.store.create_job(
            "resolve_catalog_request",
            {
                "query": body.query,
                "family_name": body.family_name,
                "unit_name": body.unit_name,
                "conversation": [item.model_dump() for item in body.conversation],
                "metadata": body.metadata,
            },
        )
        return job

    @app.get("/jobs")
    async def list_jobs(limit: int = 50) -> list[dict[str, Any]]:
        return state.store.list_jobs(limit=min(max(limit, 1), 200))

    @app.get("/jobs/{job_id}")
    async def get_job(job_id: str) -> dict[str, Any]:
        try:
            return state.store.get_job(job_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Job not found") from exc

    @app.get("/jobs/{job_id}/events")
    async def get_job_events(job_id: str) -> list[dict[str, Any]]:
        try:
            state.store.get_job(job_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Job not found") from exc
        return state.store.list_events(job_id)

    @app.post("/jobs/{job_id}/retry")
    async def retry_job(job_id: str) -> dict[str, Any]:
        try:
            state.store.get_job(job_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Job not found") from exc
        return state.store.retry_job(job_id)

    return app


app = create_app()

