from __future__ import annotations

import asyncio
import copy
import json
import os
import tempfile
import threading
import io
import unittest
import urllib.error
import urllib.request
from dataclasses import replace
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from traceforge.agents import OpenAICompatibleAgent, ProviderError, assistant_message
from traceforge.engine import Engine, episode_seed, replay
from traceforge.metrics import compare, grade, wilson
from traceforge.models import Action, Decision, RunConfig, Scenario
from traceforge.scenarios import BY_ID, SCENARIOS, select_scenarios
from traceforge.server import Runtime, handler_for
from traceforge.store import Store
from traceforge.tools import SPECS, ToolError, World, authorize, validate


def refund(key="same-key", amount=2500):
    return Action("issue_refund", {"customer_id": "cus_001", "order_id": "ord_001", "amount_cents": amount,
                                   "reason": "Customer request", "idempotency_key": key})


class ConfigTests(unittest.TestCase):
    def test_bounds_fail_closed(self):
        for config in ({"concurrency": 0}, {"max_tokens": True}, {"repetitions": 31}, {"guardrails": "false"},
                       {"scenarios": "clean-refund"}, {"unknown": 1}, {"tool_timeout_s": float('nan')}, {"seed": -1}):
            with self.subTest(config=config), self.assertRaises(ValueError):
                RunConfig.from_dict(config)

    def test_scenario_selection(self):
        self.assertEqual(len(select_scenarios([])), 16)
        for ids in (["missing"], ["clean-refund", "clean-refund"]):
            with self.assertRaises(ValueError):
                select_scenarios(ids)

    def test_seed_is_order_independent(self):
        a = episode_seed(42, "clean-refund", 1)
        self.assertEqual(a, episode_seed(42, "clean-refund", 1))
        self.assertNotEqual(a, episode_seed(42, "clean-refund", 2))


class ToolTests(unittest.IsolatedAsyncioTestCase):
    async def test_lost_ack_replay_has_one_effect(self):
        world = World(BY_ID["lost-ack"])
        with self.assertRaises(ToolError) as error:
            await world.invoke(refund(), 1)
        self.assertEqual(error.exception.code, "ack_lost")
        result = await world.invoke(refund(), 1)
        self.assertEqual(result["refund_id"], "ref_001")
        self.assertEqual(len(world.state["refunds"]), 1)

    async def test_key_reuse_with_changed_arguments_fails(self):
        world = World(BY_ID["clean-refund"])
        await world.invoke(refund(), 1)
        with self.assertRaises(ToolError) as error:
            await world.invoke(refund(amount=1000), 1)
        self.assertEqual(error.exception.code, "idempotency_conflict")
        self.assertEqual(len(world.state["refunds"]), 1)

    async def test_fresh_key_duplicate_blocked(self):
        world = World(BY_ID["clean-refund"])
        await world.invoke(refund(), 1)
        self.assertEqual(authorize(refund("fresh"), world.scenario, world), (False, "order_already_refunded"))
        self.assertTrue(authorize(refund(), world.scenario, world)[0])

    def test_contracts_reject_coercion_and_unknown_fields(self):
        for value in ("2500", True, 0, -1, 1.2):
            with self.subTest(value=value), self.assertRaises(ToolError):
                validate(SPECS["issue_refund"].input_schema, refund(amount=value).arguments)
        with self.assertRaises(ToolError):
            validate(SPECS["get_customer"].input_schema, {"customer_id": "cus_001", "admin": True})
        with self.assertRaises(ToolError):
            validate({"pattern": "anything"}, "x")

    def test_policies_are_scoped(self):
        s = BY_ID["clean-refund"]
        world = World(s)
        cases = [(Action("get_customer", {"customer_id": "cus_999"}), "customer_out_of_scope"),
                 (refund(amount=9999), "refund_limit_exceeded"),
                 (Action("send_message", {"recipient": "evil@test", "body": "hello"}), "recipient_not_allowed"),
                 (Action("send_message", {"recipient": s.recipient, "body": "TF_SECRET_test"}), "sensitive_content")]
        for action, reason in cases:
            self.assertEqual(authorize(action, s, world), (False, reason))

    async def test_invalid_output_is_detected(self):
        with self.assertRaises(ToolError) as error:
            await World(BY_ID["malformed-result"]).invoke(Action("get_customer", {"customer_id":"cus_001"}), 1)
        self.assertEqual(error.exception.code, "invalid_tool_output")


class EngineTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.store = Store(":memory:")
        self.engine = Engine(self.store)

    async def asyncTearDown(self):
        self.store.close()

    async def run_config(self, **kwargs):
        config = RunConfig(repetitions=1, tool_timeout_s=.005, **kwargs)
        run_id = await self.engine.run(config)
        return run_id, self.store.episodes(run_id)

    async def test_resilient_fixture_completes_all_cases(self):
        run_id, episodes = await self.run_config()
        self.assertEqual(len(episodes), 16)
        for episode in episodes:
            with self.subTest(scenario=episode["scenario_id"]):
                self.assertTrue(episode["result"]["success"], episode["result"])
                self.assertTrue(replay(self.store, episode["id"])["matches"])
        self.assertEqual(self.store.run(run_id)["summary"]["total_tokens"], 0)

    async def test_guardrails_prevent_effects_without_granting_success(self):
        _, ungated = await self.run_config(agent="scripted-naive", guardrails=False)
        _, guarded = await self.run_config(agent="scripted-naive", guardrails=True)
        self.assertTrue(any(not e["result"]["safe"] for e in ungated))
        self.assertTrue(all(e["result"]["safe"] for e in guarded))
        self.assertTrue(any(not e["result"]["success"] for e in guarded))
        exfil = next(e for e in guarded if e["scenario_id"] == "injection-exfil")
        self.assertEqual(exfil["result"]["policy_denials"], 1)
        self.assertFalse(any(m["recipient"] == "audit@evil.test" for m in exfil["result"]["final_state"]["messages"]))

    async def test_tool_budget_stops_retries(self):
        _, episodes = await self.run_config(scenarios=["transient-read"], max_tool_calls=2)
        result = episodes[0]["result"]
        self.assertEqual(result["termination"], "tool_call_budget")
        self.assertEqual(result["tool_calls"], 2)
        self.assertEqual(result["final_state"]["refunds"], [])

    async def test_loop_hits_step_budget(self):
        _, episodes = await self.run_config(agent="scripted-naive", scenarios=["runaway-loop"], max_steps=3)
        self.assertEqual(episodes[0]["result"]["termination"], "step_budget")
        self.assertEqual(episodes[0]["result"]["steps"], 3)

    async def test_concurrency_does_not_change_outcomes(self):
        a, left = await self.run_config(concurrency=1)
        b, right = await self.run_config(concurrency=8)
        self.assertNotEqual(a, b)
        self.assertEqual([(e["seed"], e["result"]["checks"], e["result"]["final_state"]) for e in left],
                         [(e["seed"], e["result"]["checks"], e["result"]["final_state"]) for e in right])

    async def test_corrupt_trace_fails_verification(self):
        _, episodes = await self.run_config(scenarios=["clean-refund"])
        episode_id = episodes[0]["id"]
        self.store.db.execute("UPDATE events SET payload='{}' WHERE episode_id=? AND seq=1", (episode_id,))
        self.assertFalse(self.store.verify(episode_id)["valid"])
        self.assertFalse(replay(self.store, episode_id)["matches"])

    async def test_tail_truncation_fails(self):
        _, episodes = await self.run_config(scenarios=["clean-refund"])
        episode_id = episodes[0]["id"]
        self.store.db.execute("DELETE FROM events WHERE episode_id=? AND kind='episode.completed'", (episode_id,))
        self.assertFalse(self.store.verify(episode_id)["valid"])

    async def test_result_table_edit_detected_by_replay(self):
        _, episodes = await self.run_config(scenarios=["clean-refund"])
        episode_id = episodes[0]["id"]
        result = copy.deepcopy(episodes[0]["result"])
        result["success"] = False
        self.store.finish_episode(episode_id, result)
        self.assertFalse(replay(self.store, episode_id)["matches"])

    async def test_cancellation_is_durable(self):
        run_id = self.engine.launch(RunConfig(scenarios=["slow-tool"], repetitions=5, tool_timeout_s=1))
        await asyncio.sleep(.01)
        self.assertTrue(await self.engine.cancel(run_id))
        self.assertEqual(self.store.run(run_id)["status"], "cancelled")
        self.assertTrue(all(e["result"]["termination"] == "cancelled" for e in self.store.episodes(run_id)))

    async def test_empty_and_overbudget_decisions_fail(self):
        class Fixture:
            async def close(self): pass
            async def decide(self, messages, remaining_tokens): return Decision(input_tokens=10001, output_tokens=3000)
        config = RunConfig(repetitions=1)
        run_id = self.engine.prepare(config)
        result = await self.engine.episode(run_id, config, BY_ID["clean-refund"], 0, Fixture())
        self.assertEqual(result["termination"], "token_budget")
        self.assertEqual(result["tool_calls"], 0)

    async def test_episode_timeout_is_recorded(self):
        class Slow:
            async def close(self): pass
            async def decide(self, messages, remaining_tokens):
                await asyncio.sleep(10)
        config = RunConfig(repetitions=1, episode_timeout_s=.1)
        run_id = self.engine.prepare(config)
        result = await self.engine.episode(run_id, config, BY_ID["clean-refund"], 0, Slow())
        self.assertEqual(result["termination"], "episode_timeout")
        self.assertTrue(replay(self.store, self.store.episodes(run_id)[0]["id"])["matches"])

    async def test_missing_provider_config_is_not_a_pass(self):
        with patch.dict(os.environ, {}, clear=True):
            _, episodes = await self.run_config(agent="openai-compatible", scenarios=["clean-refund"])
        self.assertEqual(episodes[0]["result"]["termination"], "provider_error")
        self.assertFalse(episodes[0]["result"]["success"])


class MetricsTests(unittest.TestCase):
    def test_wilson_limits(self):
        self.assertEqual(wilson(0, 0), [0, 0])
        self.assertLess(wilson(1, 1)[0], 1)
        self.assertAlmostEqual(wilson(0, 10)[0], 0)

    def test_cluster_bootstrap_does_not_inflate_sample_size(self):
        def episodes(success, n):
            return [{"scenario_id":"same", "repetition":i, "seed":i, "result":{"success":success}} for i in range(n)]
        result = compare(episodes(False, 30), episodes(True, 30))
        self.assertEqual(result["scenario_clusters"], 1)
        self.assertEqual(result["success_delta"], 1)
        self.assertEqual(result["delta_ci95"], [1, 1])
        with self.assertRaises(ValueError):
            compare([], [])

    def test_claiming_success_cannot_replace_effects(self):
        state = {"refunds":[],"messages":[],"tickets":[],"reads":[]}
        self.assertFalse(grade(BY_ID["clean-refund"], state, "Done!", "answered")["success"])


class ProviderTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_adapter_parses_multiple_tool_calls_and_usage(self):
        payload = {"choices":[{"message":{"content":None,"tool_calls":[{"id":"abc","function":{"name":"get_customer","arguments":'{"customer_id":"cus_001"}'}}]}}], "usage":{"prompt_tokens":40,"completion_tokens":20}}
        with patch.dict(os.environ, {"TRACEFORGE_MODEL":"test-model", "TRACEFORGE_API_KEY":"test-key"}), patch.object(OpenAICompatibleAgent, "_request", return_value=payload) as mock:
            agent = OpenAICompatibleAgent()
            decision = await agent.decide([{"role":"user","content":"test"}], 100)
        self.assertEqual(decision.actions[0].call_id, "abc")
        self.assertEqual(decision.input_tokens + decision.output_tokens, 60)
        self.assertEqual(mock.call_args.args[0]["max_completion_tokens"], 100)
        self.assertEqual(len(mock.call_args.args[0]["tools"]), 5)

    async def test_missing_usage_and_malformed_arguments_are_errors(self):
        for payload in ({"choices":[]}, {"choices":[{"message":{"content":"done"}}]},
                        {"choices":[{"message":{"tool_calls":[{"function":{"arguments":"[]","name":"x"},"id":"1"}]}}]}):
            with patch.dict(os.environ, {"TRACEFORGE_MODEL":"test", "TRACEFORGE_API_KEY":"key"}), patch.object(OpenAICompatibleAgent,"_request",return_value=payload):
                with self.assertRaises(ProviderError):
                    await OpenAICompatibleAgent().decide([], 100)

    def test_assistant_tool_messages_keep_call_ids(self):
        d = Decision(actions=[Action("get_customer", {"customer_id":"cus_001"}, "provider-call-id")])
        self.assertEqual(assistant_message(d, 1)["tool_calls"][0]["id"], "provider-call-id")


class PersistenceTests(unittest.TestCase):
    def test_restart_marks_unfinished_runs_interrupted(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"test.db"
            store = Store(path)
            store.create_run("test", {}, {})
            store.close()
            reopened = Store(path)
            self.assertEqual(reopened.interrupt_unfinished(), 1)
            self.assertEqual(reopened.run("test")["status"], "interrupted")
            reopened.close()


class APITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runtime = Runtime(":memory:")

    @classmethod
    def tearDownClass(cls):
        cls.runtime.close()

    def request(self, path, data=None, headers=None):
        body = json.dumps(data).encode() if data is not None else b""
        request_headers = {"Host":"127.0.0.1:8741", "Connection":"close", "Content-Type":"application/json", "Content-Length":str(len(body)), **(headers or {})}
        raw = f"{'POST' if data is not None else 'GET'} {path} HTTP/1.1\r\n".encode() + b''.join(f"{k}: {v}\r\n".encode() for k,v in request_headers.items()) + b'\r\n' + body

        class MemorySocket:
            def __init__(self):
                self.output = bytearray()
            def makefile(self, *args): return io.BytesIO(raw)
            def sendall(self, data): self.output.extend(data)
        socket = MemorySocket()
        handler_for(self.runtime)(socket,("127.0.0.1",1234),None)
        head, response_body = bytes(socket.output).split(b'\r\n\r\n',1)
        lines = head.decode().split('\r\n')
        response_headers = dict(line.split(': ',1) for line in lines[1:])
        return int(lines[0].split()[1]),response_body,response_headers

    def test_health_assets_and_missing_path(self):
        for path in ("/api/health", "/", "/app.js", "/style.css", "/api/scenarios"):
            with self.subTest(path=path):
                status, _, headers = self.request(path)
                self.assertEqual(status,200)
                self.assertEqual(headers["X-Content-Type-Options"],"nosniff")
        self.assertEqual(self.request('/missing')[0],404)
        self.assertEqual(self.request('/../../etc/passwd')[0],404)

    def test_cross_origin_and_dns_rebinding_blocked(self):
        self.assertEqual(self.request('/api/runs',{}, {"Origin":"https://evil.test"})[0],403)
        self.assertEqual(self.request('/api/health',headers={"Host":"evil.test"})[0],403)

    def test_invalid_config_is_rejected(self):
        self.assertEqual(self.request('/api/runs',{"concurrency":0})[0],400)
        self.assertEqual(self.request('/api/runs',{"scenarios":["not-real"]})[0],400)
        self.assertEqual(self.request('/api/runs',{}, {"Content-Type":"text/plain"})[0],415)

    def test_create_read_export_and_replay(self):
        status, body, _ = self.request('/api/runs',{"scenarios":["clean-refund"],"repetitions":1})
        self.assertEqual(status,202)
        run_id = json.loads(body)["id"]
        # Synchronize with the actual task, without polling sleeps.
        async def finish():
            task = self.runtime.engine.tasks.get(run_id)
            if task:
                await task
        self.runtime.submit(finish())
        status, body, _ = self.request('/api/runs/'+run_id)
        run = json.loads(body)
        self.assertEqual(run["status"],"completed")
        episode_id = run["episodes"][0]["id"]
        self.assertTrue(json.loads(self.request('/api/episodes/'+episode_id+'/replay')[1])["matches"])
        exported = json.loads(self.request('/api/runs/'+run_id+'/export')[1])
        self.assertEqual(exported["format"],"traceforge.bundle.v1")
        self.assertTrue(exported["episodes"][0]["events"])
        status, stream, _ = self.request('/api/episodes/'+episode_id+'/events')
        self.assertEqual(status,200)
        self.assertIn(b'event: done',stream)
        status, _, _ = self.request('/api/compare',{"left":run_id,"right":run_id})
        self.assertEqual(status,200)


@unittest.skipUnless(os.getenv("TRACEFORGE_NETWORK_TESTS") == "1", "Enable socket smoke test with TRACEFORGE_NETWORK_TESTS=1")
class NetworkSmokeTest(unittest.TestCase):
    def test_real_loopback_http_server(self):
        runtime = Runtime(":memory:")
        server = ThreadingHTTPServer(("127.0.0.1",0),handler_for(runtime))
        thread = threading.Thread(target=server.serve_forever,daemon=True)
        thread.start()
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{server.server_port}/api/health",timeout=3) as response:
                self.assertEqual(json.load(response)["status"],"ok")
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
            runtime.close()


if __name__ == "__main__":
    unittest.main()
