"""The OpenAI-compatible adapter (Gemini, Groq, Ollama...), tested with a fake
client so no API key or network is needed."""
import json
from types import SimpleNamespace as NS

from agent.providers import OpenAICompatSession, to_openai_tools
from agent.tools import TOOL_SCHEMAS


def _walk(node):
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v)


def test_tool_schemas_convert_without_type_arrays_or_null_enums():
    tools = to_openai_tools(TOOL_SCHEMAS)
    assert [t["function"]["name"] for t in tools] == [t["name"] for t in TOOL_SCHEMAS]
    for node in _walk([t["function"]["parameters"] for t in tools]):
        assert not isinstance(node.get("type"), list)
        assert None not in node.get("enum", [])
    json.dumps(tools)  # must serialize for the API
    assert TOOL_SCHEMAS[4]["input_schema"]["properties"]["year_built"]["type"] == ["integer", "null"]  # original untouched


def _call(name, args, cid="c1"):
    return NS(id=cid, function=NS(name=name, arguments=json.dumps(args)))


def _reply(content=None, calls=None):
    return NS(choices=[NS(message=NS(content=content, tool_calls=calls))])


class FakeClient:
    def __init__(self, replies, fail_first=0):
        self.replies, self.fail_first, self.sent = list(replies), fail_first, []
        self.chat = NS(completions=self)

    def create(self, **kw):
        if self.fail_first:
            self.fail_first -= 1
            err = Exception("rate limited")
            err.status_code = 429
            raise err
        self.sent.append([dict(m) for m in kw["messages"]])
        return self.replies.pop(0)


def test_loop_runs_tools_and_keeps_history():
    client = FakeClient([_reply(calls=[_call("get_psc_history", {"imo": "9900002"})]),
                         _reply("RECOMMENDATION: REFER"),
                         _reply("follow-up answer")])
    s, events = OpenAICompatSession(client=client, model="fake"), []
    assert s.ask("Assess IMO 9900002", events.append) == "RECOMMENDATION: REFER"
    assert events[1]["output"]["detentions"] == 3
    roles = [m["role"] for m in client.sent[1]]
    assert roles == ["system", "user", "assistant", "tool"]
    s.ask("What if it had one fewer detention?", events.append)
    assert [m["role"] for m in client.sent[2]][-1] == "user" and len(client.sent[2]) == 6


def test_bad_json_arguments_become_a_tool_error_not_a_crash():
    bad = NS(id="c1", function=NS(name="get_psc_history", arguments="{not json"))
    client = FakeClient([_reply(calls=[bad]), _reply("done")])
    events = []
    assert OpenAICompatSession(client=client, model="fake").ask("x", events.append) == "done"
    assert "error" in events[1]["output"]


def test_rate_limits_are_retried():
    waits = []
    client = FakeClient([_reply("ok")], fail_first=2)
    s = OpenAICompatSession(client=client, model="fake", sleep=waits.append)
    assert s.ask("hi", lambda e: None) == "ok" and waits == [5, 10]


def test_missing_key_gives_a_helpful_message(monkeypatch):
    from agent import providers
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    try:
        providers.resolve("gemini")
    except SystemExit as e:
        assert "GEMINI_API_KEY" in str(e) and "aistudio" in str(e)
    else:
        raise AssertionError("expected a SystemExit")


def test_real_openai_sdk_against_local_fake_server(monkeypatch):
    """End to end through the real `openai` library (installed in CI) and HTTP,
    against a tiny local server that answers like Gemini's OpenAI-compatible API."""
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    import pytest
    openai = pytest.importorskip("openai")
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            seen.append(body)
            last = body["messages"][-1]
            if last["role"] == "user":
                msg = {"role": "assistant", "content": None, "tool_calls": [{
                    "id": "call_1", "type": "function",
                    "function": {"name": "get_psc_history", "arguments": json.dumps({"imo": "9900002"})}}]}
            else:
                msg = {"role": "assistant", "content": "RECOMMENDATION: REFER [get_psc_history]"}
            out = json.dumps({"id": "x", "object": "chat.completion", "created": 0, "model": body["model"],
                              "choices": [{"index": 0, "message": msg, "finish_reason": "stop"}],
                              "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    for var in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
        monkeypatch.delenv(var, raising=False)
    try:
        client = openai.OpenAI(base_url=f"http://127.0.0.1:{server.server_port}/v1", api_key="test")
        events = []
        memo = OpenAICompatSession(client=client, model="fake-model").ask("Assess IMO 9900002", events.append)
    finally:
        server.shutdown()
    assert memo.startswith("RECOMMENDATION: REFER")
    assert events[1]["output"]["detentions"] == 3
    assert seen[0]["tools"][0]["type"] == "function" and seen[0]["model"] == "fake-model"
    tool_msg = seen[1]["messages"][-1]
    assert tool_msg["role"] == "tool" and tool_msg["tool_call_id"] == "call_1"


def test_bad_key_stops_with_a_clear_message():
    class Rejecting:
        def __init__(self):
            self.chat = NS(completions=self)

        def create(self, **kw):
            err = Exception("API key not valid")
            err.status_code = 401
            raise err

    try:
        OpenAICompatSession(client=Rejecting(), model="fake").ask("hi", lambda e: None)
    except SystemExit as e:
        assert "key was rejected" in str(e)
    else:
        raise AssertionError("expected a SystemExit")
