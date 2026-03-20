from __future__ import annotations

import json
from typing import Any

from openai import AsyncOpenAI

from .db import JobStore
from .mcp_client import CatalogMcpClient
from .settings import Settings


SYSTEM_PROMPT = """You resolve Fence Deck Supply product requests.

Use MCP tools instead of guessing.
Prefer exact SKU lookup first when available.
Use fuzzy and family tools for loose phrasing.
Use get_family_rules for family-specific behavior when family is known.
Use get_bom_rules only for BOM/component requests.
If there are too many products, ask one concise clarifying question using the suggested facet.
Never invent SKUs, prices, or products.
Return JSON only:
{
  "status": "resolved" | "needs_clarification" | "not_found",
  "answer": "short operator-facing answer",
  "family_name": "optional family slug",
  "unit_name": "optional unit",
  "products": [],
  "follow_up_questions": [],
  "notes": []
}
"""


def _build_user_prompt(payload: dict[str, Any]) -> str:
    parts = [f"Query: {payload['query']}"]
    if payload.get("family_name"):
        parts.append(f"Family hint: {payload['family_name']}")
    if payload.get("unit_name"):
        parts.append(f"Unit hint: {payload['unit_name']}")
    conversation = payload.get("conversation") or []
    if conversation:
        parts.append("Conversation:")
        for item in conversation[-8:]:
            role = item.get("role", "user")
            text = item.get("text", "")
            parts.append(f"- {role}: {text}")
    metadata = payload.get("metadata") or {}
    if metadata:
        parts.append(f"Metadata: {json.dumps(metadata, ensure_ascii=True)}")
    return "\n".join(parts)


class AIResolver:
    def __init__(self, settings: Settings, mcp_client: CatalogMcpClient, store: JobStore):
        self.settings = settings
        self.mcp_client = mcp_client
        self.store = store
        self.client = AsyncOpenAI(api_key=settings.openai_api_key, base_url=settings.openai_base_url)

    async def resolve_job(self, job_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        tools = await self.mcp_client.list_tools()
        openai_tools = []
        for tool in tools:
            schema = dict(tool["parameters"])
            schema.pop("$schema", None)
            openai_tools.append(
                {
                    "type": "function",
                    "name": tool["name"],
                    "description": tool["description"],
                    "parameters": schema,
                }
            )

        self.store.add_event(job_id, "info", "Loaded MCP tools", {"count": len(openai_tools)})
        prompt = _build_user_prompt(payload)

        response = await self.client.responses.create(
            model=self.settings.openai_model,
            input=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            tools=openai_tools,
        )
        self.store.add_event(job_id, "info", "Started OpenAI resolution", {"model": self.settings.openai_model})

        while True:
            function_calls = [item for item in response.output if item.type == "function_call"]
            if not function_calls:
                text = response.output_text.strip()
                try:
                    result = json.loads(text)
                except Exception:
                    result = {
                        "status": "needs_clarification",
                        "answer": text,
                        "family_name": payload.get("family_name"),
                        "unit_name": payload.get("unit_name"),
                        "products": [],
                        "follow_up_questions": [],
                        "notes": ["Model returned non-JSON output."],
                    }
                result.setdefault("status", "needs_clarification")
                result.setdefault("answer", "")
                result.setdefault("products", [])
                result.setdefault("follow_up_questions", [])
                result.setdefault("notes", [])
                return result

            tool_outputs: list[dict[str, Any]] = []
            for call in function_calls:
                args = json.loads(call.arguments or "{}")
                self.store.add_event(job_id, "info", "Calling MCP tool", {"tool": call.name, "arguments": args})
                result = await self.mcp_client.call_tool(call.name, args)
                self.store.add_event(job_id, "info", "MCP tool returned", {"tool": call.name, "is_error": result["is_error"]})
                tool_outputs.append(
                    {
                        "type": "function_call_output",
                        "call_id": call.call_id,
                        "output": json.dumps(result, ensure_ascii=True),
                    }
                )

            response = await self.client.responses.create(
                model=self.settings.openai_model,
                previous_response_id=response.id,
                input=tool_outputs,
                tools=openai_tools,
            )

