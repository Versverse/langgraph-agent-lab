import unittest

from support import build_graph


class SupportTests(unittest.TestCase):
    def setUp(self):
        self.graph = build_graph()

    def send(self, text, session="A"):
        return self.graph.invoke({"message": text}, {"configurable": {"thread_id": session}})

    def test_refund_wins_over_sales_keywords(self):
        self.assertEqual(self.send("购买套餐后怎么退款？")["route"], "refund")

    def test_another_turn_can_switch_role(self):
        self.assertEqual(self.send("套餐价格多少？")["route"], "sales")
        self.assertEqual(self.send("怎么开发票？")["route"], "billing")

    def test_wait_for_confirmation_then_deduplicate(self):
        self.assertEqual(self.send("申请退款")["status"], "needs_order")
        result = self.send("ORD-1001")
        self.assertEqual(result["status"], "awaiting_confirmation")
        self.assertFalse(result.get("receipts"))
        self.send("请问发票怎么开？")
        receipt = self.send("确认退款")
        self.assertEqual(receipt["receipts"], {"ORD-1001": "DEMO-ORD-1001"})
        self.assertEqual(self.send("帮 ORD-1001 退款")["status"], "already_submitted")

    def test_plain_confirmation_cannot_start_refund(self):
        result = self.send("确认退款")
        self.assertEqual(result["status"], "needs_order")
        self.assertFalse(result.get("receipts"))

    def test_cancel_clears_pending_order(self):
        self.send("ORD-1001")
        result = self.send("取消")
        self.assertEqual(result["status"], "cancelled")
        self.assertIsNone(result["pending_order"])
        self.assertFalse(self.send("确认退款").get("receipts"))

    def test_ineligible_order_hands_off(self):
        result = self.send("ORD-1002")
        self.assertEqual(result["status"], "human_required")
        self.assertFalse(result.get("receipts"))

    def test_sessions_do_not_share_pending_orders(self):
        self.send("ORD-1001", "A")
        self.assertEqual(self.send("确认退款", "B")["status"], "needs_order")
        self.assertEqual(self.send("确认退款", "A")["status"], "submitted")
