from __future__ import annotations

import json
import uuid
from typing import Any, AsyncIterator

import httpx
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Route

from localbot.config import LocalbotConfig, load_config
from localbot.paths import SESSION_ID_PATH, resolve_config_path
from localbot.providers import build_backend, provider_available, upstream_headers
from localbot.tracker import record_event


def _load_config() -> LocalbotConfig:
    return load_config(resolve_config_path())


def _session_affinity() -> str | None:
    if SESSION_ID_PATH.exists():
        value = SESSION_ID_PATH.read_text().strip()
        if value:
            return value
    return None


def _backend_chain(config: LocalbotConfig, claude_alias: str) -> list[dict[str, Any]]:
    primary_id = config.routing.model_id_for_alias(claude_alias)
    chain_ids = [primary_id]
    for model_id in config.routing.fallbacks:
        if model_id not in chain_ids:
            chain_ids.append(model_id)

    backends: list[dict[str, Any]] = []
    for model_id in chain_ids:
        if not provider_available(config, model_id):
            continue
        backends.append(build_backend(config, config.model_by_id(model_id)))
    if not backends:
        raise RuntimeError("No backends available. Check provider API keys in .env")
    return backends


def _retryable_status(status_code: int) -> bool:
    return status_code in {403, 429, 503}


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text", "")))
        return "".join(parts)
    return str(content or "")


def _anthropic_tools(tools: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
    if not tools:
        return None
    return [
        {
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool.get("description", ""),
                "parameters": tool.get("input_schema")
                or {"type": "object", "properties": {}},
            },
        }
        for tool in tools
    ]


def _tool_choice(body: dict[str, Any]) -> str | dict[str, Any] | None:
    choice = body.get("tool_choice")
    if choice is None:
        return None
    if isinstance(choice, str):
        return choice
    if not isinstance(choice, dict):
        return None
    kind = choice.get("type")
    if kind in {"auto", "any", "none"}:
        return "required" if kind == "any" else kind
    if kind == "tool" and choice.get("name"):
        return {
            "type": "function",
            "function": {"name": choice["name"]},
        }
    return "auto"


def _to_openai_messages(body: dict[str, Any]) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    system = body.get("system")
    if system:
        messages.append({"role": "system", "content": _text(system)})

    for message in body.get("messages") or []:
        role = message["role"]
        content = message.get("content")

        if role == "user" and isinstance(content, list):
            text_parts: list[str] = []
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "text":
                    text_parts.append(str(block.get("text", "")))
                if block.get("type") == "tool_result":
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": block.get("tool_use_id"),
                            "content": _text(block.get("content")),
                        }
                    )
            if text_parts:
                messages.append({"role": "user", "content": "".join(text_parts)})
            continue

        if role == "assistant" and isinstance(content, list):
            text_parts = []
            tool_calls = []
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "text":
                    text_parts.append(block.get("text", ""))
                if block.get("type") == "tool_use":
                    tool_calls.append(
                        {
                            "id": block.get("id"),
                            "type": "function",
                            "function": {
                                "name": block.get("name"),
                                "arguments": json.dumps(block.get("input") or {}),
                            },
                        }
                    )
            entry: dict[str, Any] = {
                "role": "assistant",
                "content": "".join(text_parts) or None,
            }
            if tool_calls:
                entry["tool_calls"] = tool_calls
            messages.append(entry)
            continue

        messages.append({"role": role, "content": _text(content)})

    return messages


def _build_upstream(body: dict[str, Any], backend: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": backend["model"],
        "messages": _to_openai_messages(body),
        "max_tokens": body.get("max_tokens", 4096),
        "stream": bool(body.get("stream")),
    }
    tools = _anthropic_tools(body.get("tools"))
    if tools:
        payload["tools"] = tools
        payload["parallel_tool_calls"] = True
    tool_choice = _tool_choice(body)
    if tool_choice is not None:
        payload["tool_choice"] = tool_choice
    payload.update(backend.get("extra_body") or {})
    return payload


def _parse_tool_input(raw: str) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass
    return {"raw": raw}


def _anthropic_from_openai_message(
    model: str,
    message: dict[str, Any],
    usage: dict[str, Any],
) -> dict[str, Any]:
    content: list[dict[str, Any]] = []
    text = message.get("content") or ""
    if text:
        content.append({"type": "text", "text": text})

    tool_calls = message.get("tool_calls") or []
    for tool_call in tool_calls:
        fn = tool_call.get("function") or {}
        content.append(
            {
                "type": "tool_use",
                "id": tool_call.get("id") or f"toolu_{uuid.uuid4().hex[:12]}",
                "name": fn.get("name"),
                "input": _parse_tool_input(fn.get("arguments") or ""),
            }
        )

    if not content:
        content.append({"type": "text", "text": ""})

    return {
        "id": f"msg_{uuid.uuid4().hex[:12]}",
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": content,
        "stop_reason": "tool_use" if tool_calls else "end_turn",
        "usage": {
            "input_tokens": int(usage.get("prompt_tokens") or 0),
            "output_tokens": int(usage.get("completion_tokens") or 0),
        },
    }


def _record_usage(backend: dict[str, Any], usage: dict[str, Any]) -> None:
    input_tokens = int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
    output_tokens = int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)
    input_rate = backend["input_cost_per_m"] / 1_000_000
    output_rate = backend["output_cost_per_m"] / 1_000_000
    record_event(
        model=backend["model"],
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=(input_tokens * input_rate) + (output_tokens * output_rate),
    )


def _sse(event: str, data: dict[str, Any]) -> bytes:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode()


async def _stream_anthropic(body: dict[str, Any]) -> AsyncIterator[bytes]:
    config = _load_config()
    claude_alias = str(body.get("model") or "claude-haiku-4-20250514")
    backends = _backend_chain(config, claude_alias)
    message_id = f"msg_{uuid.uuid4().hex[:12]}"
    model = claude_alias

    yield _sse(
        "message_start",
        {
            "type": "message_start",
            "message": {
                "id": message_id,
                "type": "message",
                "role": "assistant",
                "model": model,
                "content": [],
                "stop_reason": None,
                "usage": {"input_tokens": 0, "output_tokens": 0},
            },
        },
    )

    block_index = -1
    current_kind: str | None = None
    tool_states: dict[int, dict[str, Any]] = {}
    input_tokens = 0
    output_tokens = 0
    saw_tool_calls = False

    backend = backends[-1]
    async with httpx.AsyncClient(timeout=120.0) as client:
        for index, candidate in enumerate(backends):
            async with client.stream(
                "POST",
                candidate["url"],
                headers=upstream_headers(candidate, _session_affinity()),
                json=_build_upstream(body, candidate),
            ) as response:
                if _retryable_status(response.status_code) and index < len(backends) - 1:
                    continue
                if response.status_code >= 400:
                    detail = await response.aread()
                    yield _sse(
                        "error",
                        {
                            "type": "error",
                            "error": {"type": "api_error", "message": detail.decode()},
                        },
                    )
                    return
                backend = candidate
                async for line in response.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data = line[6:]
                    if data == "[DONE]":
                        break

                    chunk = json.loads(data)
                    usage = chunk.get("usage") or {}
                    input_tokens = int(usage.get("prompt_tokens") or input_tokens)
                    output_tokens = int(usage.get("completion_tokens") or output_tokens)

                    choice = (chunk.get("choices") or [{}])[0]
                    delta = choice.get("delta") or {}
                    finish_reason = choice.get("finish_reason")

                    text = delta.get("content")
                    if text:
                        if current_kind != "text":
                            block_index += 1
                            current_kind = "text"
                            yield _sse(
                                "content_block_start",
                                {
                                    "type": "content_block_start",
                                    "index": block_index,
                                    "content_block": {"type": "text", "text": ""},
                                },
                            )
                        yield _sse(
                            "content_block_delta",
                            {
                                "type": "content_block_delta",
                                "index": block_index,
                                "delta": {"type": "text_delta", "text": text},
                            },
                        )

                    for tool_delta in delta.get("tool_calls") or []:
                        saw_tool_calls = True
                        idx = int(tool_delta.get("index") or 0)
                        state = tool_states.setdefault(
                            idx,
                            {"id": None, "name": None, "arguments": "", "block_index": None},
                        )

                        if tool_delta.get("id"):
                            state["id"] = tool_delta["id"]
                        function = tool_delta.get("function") or {}
                        if function.get("name"):
                            state["name"] = function["name"]
                        if function.get("arguments"):
                            state["arguments"] += function["arguments"]

                        if state["block_index"] is None and state["id"] and state["name"]:
                            if current_kind == "text":
                                yield _sse(
                                    "content_block_stop",
                                    {"type": "content_block_stop", "index": block_index},
                                )
                            block_index += 1
                            state["block_index"] = block_index
                            current_kind = "tool"
                            yield _sse(
                                "content_block_start",
                                {
                                    "type": "content_block_start",
                                    "index": block_index,
                                    "content_block": {
                                        "type": "tool_use",
                                        "id": state["id"],
                                        "name": state["name"],
                                        "input": {},
                                    },
                                },
                            )

                        if state["block_index"] is not None and function.get("arguments"):
                            yield _sse(
                                "content_block_delta",
                                {
                                    "type": "content_block_delta",
                                    "index": state["block_index"],
                                    "delta": {
                                        "type": "input_json_delta",
                                        "partial_json": function["arguments"],
                                    },
                                },
                            )

                    if finish_reason == "tool_calls":
                        saw_tool_calls = True
                break

    if current_kind == "text":
        yield _sse(
            "content_block_stop",
            {"type": "content_block_stop", "index": block_index},
        )

    for state in tool_states.values():
        if state["block_index"] is not None:
            yield _sse(
                "content_block_stop",
                {"type": "content_block_stop", "index": state["block_index"]},
            )

    stop_reason = "tool_use" if saw_tool_calls else "end_turn"
    _record_usage(backend, {"prompt_tokens": input_tokens, "output_tokens": output_tokens})
    yield _sse(
        "message_delta",
        {
            "type": "message_delta",
            "delta": {"stop_reason": stop_reason, "stop_sequence": None},
            "usage": {"output_tokens": output_tokens},
        },
    )
    yield _sse("message_stop", {"type": "message_stop"})


async def messages(request: Request) -> Response:
    if request.headers.get("authorization") is None:
        return JSONResponse({"error": "missing authorization"}, status_code=401)

    body = await request.json()
    if body.get("stream"):
        return StreamingResponse(_stream_anthropic(body), media_type="text/event-stream")

    config = _load_config()
    claude_alias = str(body.get("model") or "claude-haiku-4-20250514")
    backends = _backend_chain(config, claude_alias)
    response = None
    backend = backends[-1]
    async with httpx.AsyncClient(timeout=120.0) as client:
        for candidate in backends:
            response = await client.post(
                candidate["url"],
                headers=upstream_headers(candidate, _session_affinity()),
                json=_build_upstream({**body, "stream": False}, candidate),
            )
            if _retryable_status(response.status_code) and candidate is not backends[-1]:
                continue
            backend = candidate
            break

    if response is None or response.status_code >= 400:
        detail = response.json() if response is not None else {"error": "upstream unavailable"}
        status = response.status_code if response is not None else 502
        return JSONResponse(detail, status_code=status)

    payload = response.json()
    choice = (payload.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    usage = payload.get("usage") or {}
    _record_usage(backend, usage)
    return JSONResponse(
        _anthropic_from_openai_message(
            str(body.get("model") or "claude-haiku-4-20250514"),
            message,
            usage,
        )
    )


async def health(_: Request) -> Response:
    return JSONResponse({"status": "ok"})


app = Starlette(
    routes=[
        Route("/health/liveliness", health, methods=["GET"]),
        Route("/v1/messages", messages, methods=["POST"]),
    ],
)
