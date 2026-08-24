import tempfile
import unittest
import os
import time
from pathlib import Path

from fastapi.testclient import TestClient

from tradeforge.api import create_app
from tradeforge.demo_runtime import DemoRuntime


class DashboardApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.runtime = DemoRuntime(Path(self.directory.name) / "dashboard.db")
        self.client = TestClient(create_app(self.runtime))

    def tearDown(self) -> None:
        self.runtime.close()
        self.directory.cleanup()

    def test_dashboard_is_paper_only_and_has_real_positions(self) -> None:
        response = self.client.get("/api/v1/dashboard")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["mode"], "PAPER")
        self.assertFalse(payload["liveExecution"])
        self.assertEqual(len(payload["positions"]), 3)
        self.assertEqual(self.client.get("/").status_code, 200)

    def test_stop_everything_is_backend_enforced_and_positions_remain(self) -> None:
        before = self.client.get("/api/v1/dashboard").json()
        response = self.client.post("/api/v1/control/stop-everything", json={"reason": "API safety test"})
        self.assertEqual(response.status_code, 200)
        stopped = response.json()
        self.assertTrue(stopped["control"]["killSwitch"])
        self.assertEqual(stopped["metrics"]["positions"], before["metrics"]["positions"])
        order_response = self.client.post("/api/v1/demo/orders", json={"instrument_id": "AAPL", "side": "BUY", "notional": "5"})
        self.assertEqual(order_response.status_code, 200)
        self.assertEqual(order_response.json()["decision"], "REJECT")
        self.assertIn("KILL_SWITCH_ACTIVE", order_response.json()["reasons"])

    def test_reset_requires_confirmation_then_resume_is_explicit(self) -> None:
        self.client.post("/api/v1/control/stop-everything", json={"reason": "test"})
        denied = self.client.post("/api/v1/control/reset-kill-switch", json={"owner_confirmed": False})
        self.assertEqual(denied.status_code, 409)
        reset = self.client.post("/api/v1/control/reset-kill-switch", json={"owner_confirmed": True})
        self.assertEqual(reset.status_code, 200)
        self.assertEqual(reset.json()["control"]["state"], "PAUSED")
        resumed = self.client.post("/api/v1/control/resume")
        self.assertEqual(resumed.status_code, 200)
        self.assertEqual(resumed.json()["control"]["state"], "RUNNING")

    def test_failure_scenario_is_stateful_and_unknown_scenario_is_rejected(self) -> None:
        scenario = self.client.post("/api/v1/demo/scenarios/broker-disconnect")
        self.assertEqual(scenario.status_code, 200)
        self.assertEqual(scenario.json()["system"]["broker"], "UNAVAILABLE")
        unknown = self.client.post("/api/v1/demo/scenarios/not-real")
        self.assertEqual(unknown.status_code, 404)

    def test_every_failure_scenario_executes_through_runtime(self) -> None:
        scenarios = (
            "profit-target", "daily-loss", "drawdown", "broker-disconnect",
            "market-data-failure", "stale-price", "partial-fill", "duplicate-order",
            "reconciliation-failure", "manual-trade", "manual-withdrawal", "tax-warning", "kill-switch",
        )
        for scenario in scenarios:
            with self.subTest(scenario=scenario):
                directory = tempfile.TemporaryDirectory()
                runtime = DemoRuntime(Path(directory.name) / "scenario.db")
                try:
                    response = TestClient(create_app(runtime)).post(f"/api/v1/demo/scenarios/{scenario}")
                    self.assertEqual(response.status_code, 200)
                    self.assertIn("control", response.json())
                finally:
                    runtime.close()
                    directory.cleanup()

    def test_production_mode_requires_owner_authentication(self) -> None:
        os.environ["TRADEFORGE_ENV"] = "production"
        os.environ["TRADEFORGE_DASHBOARD_TOKEN"] = "test-owner-token"
        try:
            client = TestClient(create_app(self.runtime))
            self.assertEqual(client.get("/api/v1/dashboard").status_code, 401)
            authorized = client.get("/api/v1/dashboard", headers={"X-TradeForge-Owner-Token": "test-owner-token"})
            self.assertEqual(authorized.status_code, 200)
        finally:
            os.environ.pop("TRADEFORGE_ENV", None)
            os.environ.pop("TRADEFORGE_DASHBOARD_TOKEN", None)

    def test_websocket_stream_publishes_dashboard_state(self) -> None:
        with self.client.websocket_connect("/api/v1/ws") as websocket:
            payload = websocket.receive_json()
        self.assertEqual(payload["mode"], "PAPER")
        self.assertIn("control", payload)

    def test_auto_start_runs_paper_orders_and_pause_stops_worker(self) -> None:
        directory = tempfile.TemporaryDirectory()
        runtime = DemoRuntime(Path(directory.name) / "auto.db", auto_interval_seconds=0.02)
        client = TestClient(create_app(runtime))
        try:
            started = client.post("/api/v1/auto/start")
            self.assertEqual(started.status_code, 200)
            self.assertTrue(started.json()["automation"]["running"])
            time.sleep(0.08)
            running = client.get("/api/v1/dashboard").json()
            self.assertTrue(running["automation"]["tick"] > 0)
            self.assertTrue(any(order["id"].startswith("order_") for order in running["orders"]))
            paused = client.post("/api/v1/auto/pause", json={"reason": "test pause"})
            self.assertEqual(paused.status_code, 200)
            self.assertFalse(paused.json()["automation"]["running"])
        finally:
            runtime.close()
            directory.cleanup()

    def test_end_session_pauses_and_sells_all_paper_positions(self) -> None:
        closed = self.client.post("/api/v1/session/close")
        self.assertEqual(closed.status_code, 200)
        payload = closed.json()
        self.assertEqual(payload["control"]["state"], "PAUSED")
        self.assertEqual(payload["metrics"]["positions"], 0)
        self.assertTrue(any(order["side"] == "SELL" for order in payload["orders"]))

    def test_notifications_can_be_acknowledged(self) -> None:
        self.client.post("/api/v1/control/pause", json={"reason": "notification test"})
        before = self.client.get("/api/v1/dashboard").json()
        self.assertGreater(before["unreadNotifications"], 0)
        acknowledged = self.client.post("/api/v1/notifications/acknowledge")
        self.assertEqual(acknowledged.status_code, 200)
        self.assertEqual(acknowledged.json()["unreadNotifications"], 0)


if __name__ == "__main__":
    unittest.main()
