import unittest
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

from fastapi.testclient import TestClient

from expressions import ExpressionError, evaluate
from lab import CASES, Lab, compare, create_app


class ExpressionTests(unittest.TestCase):
    def test_allows_bounded_arithmetic_and_named_functions(self):
        self.assertEqual(evaluate("max(10, abs(-12)) * 2 + round(1.234, 2)"), 25.23)

    def test_rejects_disallowed_syntax_and_limits(self):
        for expression in (
            'open("demo.txt")', "import math", "(1).real", "2 ** 30", "False",
            "round(1, 8)", "1 / 0", "1e12 * 10", "1 " * 150,
        ):
            with self.subTest(expression=expression), self.assertRaises(ExpressionError):
                evaluate(expression)


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.lab = Lab()

    def test_same_case_set_passes_in_all_architectures(self):
        result = compare(self.lab)
        self.assertEqual([row["mode"] for row in result], ["supervisor", "manual", "prebuilt"])
        self.assertTrue(all(row["passed"] == len(CASES) for row in result))

    def test_both_single_agent_modes_return_a_clear_rejection(self):
        for mode in ("manual", "prebuilt"):
            with self.subTest(mode=mode):
                turn = self.lab.run(mode, '计算 open("demo.txt")')
                self.assertIn("只支持数字", turn["reply"])
                self.assertEqual(turn["trace"][-1]["status"], "rejected")

    def test_invoice_with_an_order_id_reaches_billing(self):
        result = self.lab.run("supervisor", "ORD-1001 的发票怎么开？")
        self.assertEqual(result["route"], "billing")
        self.assertEqual(result["trace"][-1]["node"], "invoice_policy")
        self.assertIsNone(result["pending_order"])

    def test_parallel_refund_confirmations_share_one_receipt(self):
        threads = [uuid4(), uuid4()]
        for thread in threads:
            self.assertEqual(self.lab.run("supervisor", "ORD-1001", thread)["pending_order"], "ORD-1001")
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda thread: self.lab.run("supervisor", "确认退款", thread), threads))
        self.assertCountEqual([turn["trace"][-1]["status"] for turn in results], ["submitted", "already_submitted"])
        self.assertTrue(all("DEMO-ORD-1001" in turn["reply"] for turn in results))

    def test_normal_http_entry_points(self):
        with TestClient(create_app()) as client:
            self.assertEqual(client.get("/").status_code, 200)
            self.assertEqual(client.get("/api/health").json(), {"status": "ready", "mode": "demo"})
            body = {"mode": "manual", "message": "专业版 3 个席位买 2 个月，多少钱？"}
            result = client.post("/api/run", json=body)
            self.assertEqual(result.status_code, 200)
            data = result.json()
            self.assertIn("594", data["reply"])
            self.assertEqual([step["node"] for step in data["trace"]], ["模型", "lookup_plan", "模型", "calculate"])
            self.assertEqual(client.post("/api/run", json={**body, "message": "   "}).status_code, 422)
            self.assertEqual(len(client.get("/api/compare").json()), 3)
