import argparse
import json
import os
from collections.abc import Callable
from pathlib import Path
from statistics import median
from threading import Lock
from time import perf_counter
from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, StringConstraints

from architectures import build_manual, build_prebuilt, summarize
from models import select_model
from support import build_graph
from toolkit import TOOLS


Mode = Literal["supervisor", "manual", "prebuilt"]
ROOT = Path(__file__).resolve().parent
CASES = (
    ("技术排查", "连续报错 429 怎么办？", "限流", ("lookup_error",)),
    ("产品咨询", "专业版的套餐价格是多少？", "99 元", ("lookup_plan",)),
    ("多步报价", "专业版 3 个席位买 2 个月，多少钱？", "594", ("lookup_plan", "calculate")),
    ("账单咨询", "上个月扣款后，我怎么开电子发票？", "订单详情", ("invoice_policy",)),
    ("未知错误码", "我遇到错误 999，怎么排查？", "暂无", ("lookup_error",)),
)


class RunRequest(BaseModel):
    mode: Mode
    message: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1200)]
    session_id: UUID | None = None


class Lab:
    def __init__(self, model_mode="demo"):
        self.model_mode = model_mode
        model = select_model(model_mode)
        self.graphs = {"supervisor": build_graph(model), "manual": build_manual(model), "prebuilt": build_prebuilt(model)}
        self.sessions: dict[UUID, Lock] = {}

    def run(self, mode: Mode, message: str, session_id: UUID | None = None) -> dict:
        started = perf_counter()
        session_id = session_id or uuid4()
        graph = self.graphs[mode]
        if mode == "supervisor":
            lock = self.sessions.setdefault(session_id, Lock())
            with lock:
                result = graph.invoke({"message": message}, {"configurable": {"thread_id": str(session_id)}})
            reply, trace = result["reply"], result["trace"]
            route, pending = result["route"], result.get("pending_order")
        else:
            result = graph.invoke({"messages": [{"role": "user", "content": message}]}, {"recursion_limit": 14})
            reply, trace = summarize(result["messages"])
            route, pending = None, None
        return {
            "mode": mode, "session_id": str(session_id), "route": route, "pending_order": pending,
            "reply": reply, "trace": trace, "elapsed_ms": round((perf_counter() - started) * 1000, 2),
        }


def compare(lab: Lab) -> list[dict]:
    tool_names = {tool.name for tool in TOOLS}
    results = []
    for mode in lab.graphs:
        rows = []
        for label, message, expected, expected_tools in CASES:
            turn = lab.run(mode, message)
            observed_tools = tuple(item["node"] for item in turn["trace"] if item["node"] in tool_names)
            rows.append({
                "task": label, "passed": expected in turn["reply"] and observed_tools == expected_tools,
                "elapsed_ms": turn["elapsed_ms"], "steps": len(turn["trace"]),
            })
        results.append({"mode": mode, "cases": rows, "passed": sum(row["passed"] for row in rows),
                        "median_ms": round(median(row["elapsed_ms"] for row in rows), 2)})
    return results


def create_app(lab_factory: Callable[[], Lab] | None = None):
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.lab = lab_factory() if lab_factory else Lab(os.getenv("AGENT_LAB_MODE", "demo"))
        yield

    app = FastAPI(title="LangGraph 架构实验台", lifespan=lifespan)

    @app.get("/api/health")
    def health():
        return {"status": "ready", "mode": app.state.lab.model_mode}

    @app.post("/api/run")
    def run(request: RunRequest):
        try:
            return app.state.lab.run(request.mode, request.message, request.session_id)
        except Exception:
            raise HTTPException(status_code=502, detail="运行失败，请检查模型配置或缩小任务范围。") from None

    @app.get("/api/compare")
    def comparison():
        lab = app.state.lab
        return compare(lab if lab.model_mode == "demo" else Lab())

    app.mount("/", StaticFiles(directory=ROOT / "web", html=True), name="web")
    return app


def main():
    parser = argparse.ArgumentParser(description="运行或比较三种 Agent 架构。")
    parser.add_argument("--compare", action="store_true", help="用本地演示模型比较固定用例。")
    parser.add_argument("--mode", choices=("supervisor", "manual", "prebuilt"), default="supervisor")
    parser.add_argument("--question", default="专业版 3 个席位买 2 个月，多少钱？")
    args = parser.parse_args()
    lab = Lab("demo" if args.compare else os.getenv("AGENT_LAB_MODE", "demo"))
    output = compare(lab) if args.compare else lab.run(args.mode, args.question)
    print(json.dumps(output, ensure_ascii=False, indent=2))
    if args.compare and any(row["passed"] != len(CASES) for row in output):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
