from __future__ import annotations

import asyncio
import json
import os
from contextlib import AsyncExitStack
from datetime import timedelta
from typing import Any

from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from .settings import Settings


class CatalogMcpClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._stack: AsyncExitStack | None = None
        self._session: ClientSession | None = None
        self._lock = asyncio.Lock()
        self._tool_cache: list[dict[str, Any]] | None = None

    async def start(self) -> None:
        async with self._lock:
            if self._session is not None:
                return
            env = dict(os.environ)
            server = StdioServerParameters(
                command=self.settings.catalog_mcp_command,
                args=self.settings.catalog_mcp_args,
                env=env,
                cwd=str(self.settings.catalog_mcp_cwd),
            )
            self._stack = AsyncExitStack()
            read_stream, write_stream = await self._stack.enter_async_context(stdio_client(server))
            self._session = await self._stack.enter_async_context(ClientSession(read_stream, write_stream))
            await self._session.initialize()

    async def close(self) -> None:
        async with self._lock:
            if self._stack is not None:
                await self._stack.aclose()
            self._stack = None
            self._session = None
            self._tool_cache = None

    async def list_tools(self) -> list[dict[str, Any]]:
        await self.start()
        if self._tool_cache is not None:
            return self._tool_cache
        assert self._session is not None
        result = await self._session.list_tools()
        tools = []
        for tool in result.tools:
            tools.append(
                {
                    "name": tool.name,
                    "description": tool.description or "",
                    "parameters": dict(tool.inputSchema or {"type": "object", "properties": {}}),
                }
            )
        self._tool_cache = tools
        return tools

    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        await self.start()
        assert self._session is not None
        result = await self._session.call_tool(
            name,
            arguments or {},
            read_timeout_seconds=timedelta(milliseconds=self.settings.request_timeout_ms),
        )
        parsed_content = []
        for item in result.content:
            if getattr(item, "type", None) == "text":
                text = item.text
                try:
                    parsed_content.append(json.loads(text))
                except Exception:
                    parsed_content.append(text)
            else:
                parsed_content.append(item.model_dump())
        return {
            "tool": name,
            "is_error": bool(result.isError),
            "content": parsed_content,
        }

