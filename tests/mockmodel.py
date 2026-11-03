"""A scripted model server for integration tests. No real model, no cost.

Speaks just enough of three APIs for the real agent CLIs:
- Anthropic Messages (Claude Code)      POST /v1/messages
- OpenAI Responses (Codex)               POST /v1/responses
- OpenAI Chat Completions (OpenCode)     POST /v1/chat/completions

Rule: if the latest user prompt contains ``fire:<skill-name>`` and no tool
result is in the conversation yet, the "model" activates that skill the way
each agent expects (Skill tool, reading SKILL.md, skill tool). Otherwise it
answers with plain text. Run: python tests/mockmodel.py 18765
"""

from __future__ import annotations

import json
import re
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

FIRE = re.compile(r"fire:([a-z0-9-]+)")


def _text_of(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(
            c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") in ("text", "input_text")
        )
    return ""


def decide_anthropic(body: dict) -> str | None:
    msgs = body.get("messages", [])
    for m in msgs:
        if isinstance(m.get("content"), list) and any(
            isinstance(c, dict) and c.get("type") == "tool_result" for c in m["content"]
        ):
            return None
    users = [m for m in msgs if m.get("role") == "user"]
    if not users:
        return None
    content = users[-1].get("content")
    # The real prompt is the last text block; earlier blocks are system reminders.
    if isinstance(content, list):
        texts = [c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text"]
        text = texts[-1] if texts else ""
    else:
        text = _text_of(content)
    m = FIRE.search(text)
    return m.group(1) if m else None


def decide_chat(body: dict) -> str | None:
    msgs = body.get("messages", [])
    if any(m.get("role") == "tool" for m in msgs):
        return None
    if msgs and "title generator" in _text_of(msgs[0].get("content")):
        return None
    users = [m for m in msgs if m.get("role") == "user"]
    m = FIRE.search(_text_of(users[-1].get("content"))) if users else None
    return m.group(1) if m else None


def decide_responses(body: dict) -> str | None:
    items = body.get("input", [])
    if isinstance(items, str):
        m = FIRE.search(items)
        return m.group(1) if m else None
    if any(i.get("type") == "function_call_output" for i in items if isinstance(i, dict)):
        return None
    users = [i for i in items if isinstance(i, dict) and i.get("role") == "user"]
    m = FIRE.search(_text_of(users[-1].get("content"))) if users else None
    return m.group(1) if m else None


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):  # quiet
        pass

    def _json(self, code: int, obj) -> None:
        data = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _sse(self, events: list[tuple[str | None, dict | str]]) -> None:
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.send_header("cache-control", "no-cache")
        self.send_header("connection", "close")
        self.end_headers()
        for name, data in events:
            chunk = ""
            if name:
                chunk += f"event: {name}\n"
            chunk += "data: " + (data if isinstance(data, str) else json.dumps(data)) + "\n\n"
            self.wfile.write(chunk.encode())
            self.wfile.flush()
        self.close_connection = True

    def do_GET(self):
        if self.path.rstrip("/").endswith("/models"):
            self._json(200, {"object": "list", "data": [{"id": "mock-model", "object": "model"}]})
        else:
            self._json(404, {"error": {"message": "not found"}})

    def do_POST(self):
        length = int(self.headers.get("content-length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        path = self.path.split("?")[0]
        if path.endswith("/messages/count_tokens"):
            self._json(200, {"input_tokens": 100})
        elif path.endswith("/messages"):
            self.api_anthropic(body)
        elif path.endswith("/responses"):
            self.api_responses(body)
        elif path.endswith("/chat/completions"):
            self.api_chat(body)
        else:
            self._json(404, {"error": {"message": "not found"}})

    # --- Anthropic Messages -------------------------------------------------
    def api_anthropic(self, body: dict) -> None:
        skill = decide_anthropic(body)
        model = body.get("model", "mock-model")
        if skill:
            block = {"type": "tool_use", "id": "toolu_mock1", "name": "Skill", "input": {"skill": skill}}
            stop = "tool_use"
        else:
            block = {"type": "text", "text": "Done."}
            stop = "end_turn"
        if not body.get("stream"):
            self._json(
                200,
                {
                    "id": "msg_mock",
                    "type": "message",
                    "role": "assistant",
                    "model": model,
                    "content": [block],
                    "stop_reason": stop,
                    "stop_sequence": None,
                    "usage": {"input_tokens": 100, "output_tokens": 10},
                },
            )
            return
        events = [
            (
                "message_start",
                {
                    "type": "message_start",
                    "message": {
                        "id": "msg_mock",
                        "type": "message",
                        "role": "assistant",
                        "model": model,
                        "content": [],
                        "stop_reason": None,
                        "stop_sequence": None,
                        "usage": {"input_tokens": 100, "output_tokens": 1},
                    },
                },
            )
        ]
        if skill:
            events += [
                (
                    "content_block_start",
                    {
                        "type": "content_block_start",
                        "index": 0,
                        "content_block": {"type": "tool_use", "id": "toolu_mock1", "name": "Skill", "input": {}},
                    },
                ),
                (
                    "content_block_delta",
                    {
                        "type": "content_block_delta",
                        "index": 0,
                        "delta": {"type": "input_json_delta", "partial_json": json.dumps({"skill": skill})},
                    },
                ),
            ]
        else:
            events += [
                (
                    "content_block_start",
                    {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
                ),
                (
                    "content_block_delta",
                    {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "Done."}},
                ),
            ]
        events += [
            ("content_block_stop", {"type": "content_block_stop", "index": 0}),
            (
                "message_delta",
                {
                    "type": "message_delta",
                    "delta": {"stop_reason": stop, "stop_sequence": None},
                    "usage": {"output_tokens": 10},
                },
            ),
            ("message_stop", {"type": "message_stop"}),
        ]
        self._sse(events)

    # --- OpenAI Chat Completions --------------------------------------------
    def api_chat(self, body: dict) -> None:
        skill = decide_chat(body)
        model = body.get("model", "mock-model")
        base = {"id": "chatcmpl-mock", "object": "chat.completion.chunk", "created": 0, "model": model}
        usage = {"prompt_tokens": 100, "completion_tokens": 10, "total_tokens": 110}
        if skill:
            call = {
                "index": 0,
                "id": "call_mock1",
                "type": "function",
                "function": {"name": "skill", "arguments": json.dumps({"name": skill})},
            }
            delta, finish = {"role": "assistant", "tool_calls": [call]}, "tool_calls"
            message = {
                "role": "assistant",
                "content": None,
                "tool_calls": [{k: v for k, v in call.items() if k != "index"}],
            }
        else:
            delta, finish = {"role": "assistant", "content": "Done."}, "stop"
            message = {"role": "assistant", "content": "Done."}
        if not body.get("stream"):
            self._json(
                200,
                {
                    **base,
                    "object": "chat.completion",
                    "usage": usage,
                    "choices": [{"index": 0, "message": message, "finish_reason": finish}],
                },
            )
            return
        self._sse(
            [
                (None, {**base, "choices": [{"index": 0, "delta": delta, "finish_reason": None}]}),
                (None, {**base, "choices": [{"index": 0, "delta": {}, "finish_reason": finish}], "usage": usage}),
                (None, "[DONE]"),
            ]
        )

    # --- OpenAI Responses -----------------------------------------------------
    def api_responses(self, body: dict) -> None:
        skill = decide_responses(body)
        model = body.get("model", "mock-model")
        if skill:
            item = {
                "type": "function_call",
                "id": "fc_mock1",
                "call_id": "call_mock1",
                "name": "exec_command",
                "arguments": json.dumps({"cmd": f"cat /home/node/work/.agents/skills/{skill}/SKILL.md"}),
                "status": "completed",
            }
        else:
            item = {
                "type": "message",
                "id": "msg_mock1",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "text": "Done.", "annotations": []}],
            }
        usage = {
            "input_tokens": 100,
            "input_tokens_details": {"cached_tokens": 0},
            "output_tokens": 10,
            "output_tokens_details": {"reasoning_tokens": 0},
            "total_tokens": 110,
        }
        resp = {
            "id": "resp_mock",
            "object": "response",
            "created_at": 0,
            "model": model,
            "status": "completed",
            "output": [item],
            "usage": usage,
        }
        events = [
            (
                "response.created",
                {
                    "type": "response.created",
                    "sequence_number": 0,
                    "response": {**resp, "status": "in_progress", "output": []},
                },
            ),
            (
                "response.output_item.added",
                {"type": "response.output_item.added", "sequence_number": 1, "output_index": 0, "item": item},
            ),
        ]
        if not skill:
            events.append(
                (
                    "response.output_text.delta",
                    {
                        "type": "response.output_text.delta",
                        "sequence_number": 2,
                        "item_id": "msg_mock1",
                        "output_index": 0,
                        "content_index": 0,
                        "delta": "Done.",
                    },
                )
            )
        events += [
            (
                "response.output_item.done",
                {"type": "response.output_item.done", "sequence_number": 3, "output_index": 0, "item": item},
            ),
            ("response.completed", {"type": "response.completed", "sequence_number": 4, "response": resp}),
        ]
        self._sse(events)


def serve(port: int = 0, host: str = "0.0.0.0") -> ThreadingHTTPServer:
    """Start the server in a background thread and return it (port 0 = pick a free one)."""
    server = ThreadingHTTPServer((host, port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


if __name__ == "__main__":
    srv = ThreadingHTTPServer(("0.0.0.0", int(sys.argv[1]) if len(sys.argv) > 1 else 18765), Handler)
    srv.serve_forever()
