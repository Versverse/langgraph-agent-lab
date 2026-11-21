from __future__ import annotations

import argparse
import json
import re
from threading import Lock
from typing import TypedDict
from uuid import uuid4

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from architectures import build_prebuilt, summarize
from models import DemoModel
from toolkit import ROLE_TOOLS


ORDERS = {"ORD-1001": True, "ORD-1002": False}
ORDER_ID = re.compile(r"\bORD-\d{4}\b", re.IGNORECASE)
CONFIRM = {"确认退款", "确认提交"}
CANCEL = {"取消退款", "取消", "不退款"}
LABELS = {"technical": "技术支持", "sales": "销售", "billing": "账单", "refund": "账单 · 退款", "clarify": "补充信息"}


class SupportState(TypedDict, total=False):
    message: str
    route: str
    status: str
    reply: str
    pending_order: str | None
    receipts: dict[str, str]
    trace: list[dict[str, str]]


class RefundBook:
    """A process-local ledger for simulated orders."""

    def __init__(self):
        self._receipts: dict[str, str] = {}
        self._lock = Lock()

    def get(self, order: str) -> str | None:
        with self._lock:
            return self._receipts.get(order)

    def record(self, order: str) -> tuple[str, bool]:
        with self._lock:
            receipt = self._receipts.get(order)
            if receipt:
                return receipt, False
            receipt = f"DEMO-{order}"
            self._receipts[order] = receipt
            return receipt, True


def supervisor(state: SupportState) -> dict:
    text = state["message"].strip()
    if "退款" in text or (
        state.get("status") in {"needs_order", "awaiting_confirmation"} and text in CONFIRM | CANCEL
    ):
        route = "refund"
    elif any(word in text for word in ("发票", "账单", "支付")):
        route = "billing"
    elif any(word in text.lower() for word in ("报错", "错误", "崩溃", "故障", "bug", "error")):
        route = "technical"
    elif any(word in text for word in ("套餐", "价格", "购买", "优惠", "专业版", "基础版", "报价", "多少钱")):
        route = "sales"
    elif ORDER_ID.fullmatch(text):
        route = "refund"
    else:
        route = "clarify"
    return {"route": route, "trace": [{"node": "Supervisor", "detail": f"路由到{LABELS[route]}", "status": "ok"}]}


def refund(state: SupportState, book: RefundBook) -> dict:
    text = state["message"].strip()
    pending = state.get("pending_order")
    receipts = state.get("receipts", {})

    if text in CANCEL:
        return {"pending_order": None, "status": "cancelled", "reply": "已取消本次退款申请。"}
    if text in CONFIRM:
        if not pending:
            return {"status": "needs_order", "reply": "请先提供要退款的订单号，例如 ORD-1001。"}
        receipt, created = book.record(pending)
        return {
            "pending_order": None, "status": "submitted" if created else "already_submitted",
            "receipts": {**receipts, pending: receipt},
            "reply": f"模拟退款已提交，回执 {receipt}。" if created else f"该订单已有回执 {receipt}。",
        }

    match = ORDER_ID.search(text)
    order = match.group().upper() if match else pending
    if not order or order not in ORDERS:
        return {"pending_order": None, "status": "needs_order", "reply": "请提供有效订单号，例如 ORD-1001。"}
    if receipt := book.get(order):
        return {"pending_order": None, "status": "already_submitted", "reply": f"该订单已有回执 {receipt}。"}
    if not ORDERS[order]:
        return {"pending_order": None, "status": "human_required", "reply": "该模拟订单需由人工复核。"}
    return {
        "pending_order": order, "status": "awaiting_confirmation",
        "reply": f"{order} 符合演示退款条件，请回复「确认退款」或「取消退款」。",
    }


def clarify(_state: SupportState) -> dict:
    return {"reply": "请说明你想咨询产品、技术报错、发票，还是申请退款。"}


def build_graph(model=None):
    model = model if model is not None else DemoModel()
    book = RefundBook()
    agents = {role: build_prebuilt(model, tools, role) for role, tools in ROLE_TOOLS.items()}

    def handle_role(state: SupportState) -> dict:
        role = state["route"]
        result = agents[role].invoke({"messages": [{"role": "user", "content": state["message"]}]},
                                     {"recursion_limit": 14})
        reply, trace = summarize(result["messages"])
        return {"reply": reply, "trace": [
            *state["trace"], {"node": LABELS[role], "detail": "处理本轮问题", "status": "ok"}, *trace,
        ]}

    def handle_refund(state: SupportState) -> dict:
        update = refund(state, book)
        return {**update, "trace": [
            *state["trace"], {"node": "退款状态", "detail": update["reply"], "status": update["status"]},
        ]}

    graph = StateGraph(SupportState)
    graph.add_node("supervisor", supervisor)
    handlers = {**dict.fromkeys(ROLE_TOOLS, handle_role), "refund": handle_refund, "clarify": clarify}
    for name, handler in handlers.items():
        graph.add_node(name, handler)
        graph.add_edge(name, END)
    graph.add_edge(START, "supervisor")
    graph.add_conditional_edges("supervisor", lambda state: state["route"], dict(zip(handlers, handlers)))
    return graph.compile(checkpointer=InMemorySaver())


def main():
    parser = argparse.ArgumentParser(description="Run a local LangGraph customer-support example")
    parser.add_argument("--interactive", action="store_true")
    args = parser.parse_args()
    app = build_graph()
    config = {"configurable": {"thread_id": uuid4().hex}}
    if args.interactive:
        while True:
            try:
                text = input("用户> ").strip()
            except EOFError:
                break
            if text in {"exit", "quit"}:
                break
            if text:
                print(app.invoke({"message": text}, config)["reply"])
    else:
        for text in ("套餐价格多少？", "我要申请退款", "ORD-1001", "发票怎么开？", "确认退款", "帮 ORD-1001 退款"):
            result = app.invoke({"message": text}, config)
            print(json.dumps({"input": text, "route": result["route"], "reply": result["reply"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
