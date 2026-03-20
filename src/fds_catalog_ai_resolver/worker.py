from __future__ import annotations

import asyncio
import logging

from .db import JobStore
from .llm import AIResolver
from .mcp_client import CatalogMcpClient
from .settings import Settings


logger = logging.getLogger(__name__)


class Worker:
    def __init__(self, settings: Settings, store: JobStore, mcp_client: CatalogMcpClient, resolver: AIResolver):
        self.settings = settings
        self.store = store
        self.mcp_client = mcp_client
        self.resolver = resolver
        self._stop = asyncio.Event()
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self.run(), name="fds-catalog-ai-worker")

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            await self._task
        await self.mcp_client.close()

    async def run(self) -> None:
        while not self._stop.is_set():
            job = self.store.claim_next_job()
            if not job:
                await asyncio.sleep(self.settings.worker_poll_interval_ms / 1000)
                continue
            job_id = job["id"]
            try:
                self.store.add_event(job_id, "info", "Worker claimed job")
                result = await self.resolver.resolve_job(job_id, job["request"])
                self.store.complete_job(job_id, result)
            except Exception as exc:
                logger.exception("Job %s failed", job_id)
                self.store.fail_job(job_id, str(exc))

