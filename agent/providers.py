"""Run the same agent on any LLM that speaks the OpenAI chat-completions format
with tool calling: Google Gemini (free tier), Groq, Ollama (local, free), or OpenAI.

    python -m agent.agent --provider gemini --chat "Assess IMO 9900002"

Settings come from environment variables:
    GEMINI_API_KEY      key from aistudio.google.com (provider "gemini")
    GROQ_API_KEY        key from console.groq.com (provider "groq")
    AGENT_MODEL         override the provider's default model
    AGENT_BASE_URL      any other OpenAI-compatible server (provider "openai")
    AGENT_API_KEY       key for that server

The tools, system prompt, and rules are identical to the Claude version in
agent/agent.py; only the message format differs.
"""
import copy
import json
import os
import time

PRESETS = {
    "gemini": {"base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
               "key_env": "GEMINI_API_KEY", "model": "gemini-3.8-flash",
               "signup": "https://aistudio.google.com (free, no card)"},
    "groq": {"base_url": "https://api.groq.com/openai/v1",
             "key_env": "GROQ_API_KEY", "model": None,
             "signup": "https://console.groq.com (free tier); set AGENT_MODEL to a model that supports tool use"},
    "ollama": {"base_url": "http://localhost:11434/v1", "key_env": None, "model": None,
               "signup": "https://ollama.com, then `ollama pull <model>`; set AGENT_MODEL to that model"},
    "openai": {"base_url": None, "key_env": "AGENT_API_KEY", "model": None,
               "signup": "set AGENT_BASE_URL, AGENT_API_KEY and AGENT_MODEL"},
}

RETRY_STATUS = {429, 500, 502, 503, 504}


def to_openai_tools(anthropic_tools: list) -> list:
    """Convert our tool schemas to OpenAI format. Also simplifies nullable fields
    (["string", "null"] -> "string") because some providers, Gemini included,
    reject type arrays. The model can still send null; our tools accept it."""
    def simplify(node):
        if isinstance(node, dict):
            node = {k: simplify(v) for k, v in node.items()}
            t = node.get("type")
            if isinstance(t, list):
                non_null = [x for x in t if x != "null"]
                node["type"] = non_null[0] if len(non_null) == 1 else non_null
                if "null" in t:
                    node["description"] = (node.get("description", "") + " Use null if unknown.").strip()
            if isinstance(node.get("enum"), list):
                node["enum"] = [x for x in node["enum"] if x is not None]
            return node
        if isinstance(node, list):
            return [simplify(x) for x in node]
        return node

    return [{"type": "function",
             "function": {"name": t["name"], "description": t["description"],
                          "parameters": simplify(copy.deepcopy(t["input_schema"]))}}
            for t in anthropic_tools]


def resolve(provider: str) -> dict:
    if provider not in PRESETS:
        raise SystemExit(f"Unknown provider '{provider}'. Choose from: anthropic, {', '.join(PRESETS)}")
    p = PRESETS[provider]
    base_url = os.environ.get("AGENT_BASE_URL") or p["base_url"]
    model = os.environ.get("AGENT_MODEL") or p["model"]
    key = os.environ.get(p["key_env"]) if p["key_env"] else "ollama"
    missing = [name for name, v in (("base URL (AGENT_BASE_URL)", base_url), ("model (AGENT_MODEL)", model),
                                    (f"API key ({p['key_env']})", key)) if not v]
    if missing:
        raise SystemExit(f"Provider '{provider}' needs: {', '.join(missing)}. Get started: {p['signup']}")
    return {"base_url": base_url, "model": model, "api_key": key}


class OpenAICompatSession:
    """Same agent loop as AgentSession, in OpenAI chat-completions format."""

    def __init__(self, provider: str = "gemini", client=None, model=None, system_prompt=None,
                 tools=None, max_steps=12, sleep=time.sleep):
        from agent.agent import SYSTEM_PROMPT, MAX_STEPS  # noqa: F401  (avoid import cycle at module load)
        from agent.tools import TOOL_SCHEMAS
        if client is None:
            from openai import OpenAI
            cfg = resolve(provider)
            client = OpenAI(base_url=cfg["base_url"], api_key=cfg["api_key"])
            model = model or cfg["model"]
        self.client, self.model, self.provider = client, model, provider
        self.tools = to_openai_tools(tools or TOOL_SCHEMAS)
        self.messages = [{"role": "system", "content": system_prompt or SYSTEM_PROMPT}]
        self.max_steps, self.sleep = max_steps, sleep

    def _create(self):
        """Call the model, waiting and retrying on free-tier rate limits."""
        delay = 5
        for attempt in range(6):
            try:
                return self.client.chat.completions.create(
                    model=self.model, messages=self.messages, tools=self.tools,
                    tool_choice="auto", max_tokens=2000, temperature=0)
            except Exception as e:  # openai.APIStatusError and friends
                status = getattr(e, "status_code", None)
                if status not in RETRY_STATUS or attempt == 5:
                    raise
                self.sleep(delay)
                delay = min(delay * 2, 60)

    def ask(self, text: str, on_event=print) -> str:
        from agent.tools import run_tool
        self.messages.append({"role": "user", "content": text})
        for _ in range(self.max_steps):
            msg = self._create().choices[0].message
            calls = msg.tool_calls or []
            entry = {"role": "assistant", "content": msg.content or (None if calls else "")}
            if calls:
                entry["tool_calls"] = [{"id": c.id, "type": "function",
                                        "function": {"name": c.function.name,
                                                     "arguments": c.function.arguments or "{}"}}
                                       for c in calls]
            self.messages.append(entry)
            if not calls:
                return msg.content or ""
            for c in calls:
                try:
                    args = json.loads(c.function.arguments or "{}")
                except json.JSONDecodeError as e:
                    args, out = {}, {"error": f"tool arguments were not valid JSON: {e}"}
                else:
                    out = None
                on_event({"event": "tool_call", "tool": c.function.name, "input": args})
                if out is None:
                    out = run_tool(c.function.name, args)
                on_event({"event": "tool_result", "tool": c.function.name, "output": out})
                self.messages.append({"role": "tool", "tool_call_id": c.id, "content": json.dumps(out)})
        return "Stopped: step limit reached without a final memo."
