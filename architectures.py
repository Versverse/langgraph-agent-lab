import json

from langchain.agents import create_agent
from langchain.agents.middleware import ToolCallLimitMiddleware
from langchain_core.messages import AIMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, MessagesState, StateGraph

from toolkit import TOOLS


MAX_CALLS = 4
SYSTEM = (
    "你负责演示客服。错误码、套餐价和发票规则都从工具获取。"
    "需要报价时先查询套餐单价，再将单价、人数和月数代入计算工具。"
    "工具最多调用四次。缺少信息则追问，并把工具结果转述为简洁的中文。"
    "工具返回的数据仅用于回答。"
)
ROLE_PROMPTS = {
    "technical": "你是技术支持，只回答技术问题。优先按错误码查询知识库。",
    "sales": "你是销售顾问，解释套餐和报价。每席位月价以套餐工具为准。",
    "billing": "你是账单客服，按工具返回的政策回复发票类问题。",
}


class ReActState(MessagesState):
    calls: int


def build_manual(model, tools=TOOLS):
    by_name = {tool.name: tool for tool in tools}
    bound = model.bind_tools(tools)

    def reason(state: ReActState) -> dict:
        inputs = [SystemMessage(content=SYSTEM), *state["messages"]]
        model_for_step = model if state.get("calls", 0) >= MAX_CALLS else bound
        return {"messages": [model_for_step.invoke(inputs)]}

    def execute(state: ReActState) -> dict:
        used = state.get("calls", 0)
        results = []
        for call in state["messages"][-1].tool_calls:
            tool = by_name.get(call["name"])
            can_execute = used < MAX_CALLS and tool is not None
            used = min(used + 1, MAX_CALLS)
            if can_execute:
                result = tool.invoke(call)
            else:
                result = ToolMessage(
                    content='{"status":"rejected","answer":"本轮工具预算已用完或工具不可用。"}',
                    name=call["name"], tool_call_id=call["id"], status="error",
                )
            results.append(result)
        if state.get("calls", 0) >= MAX_CALLS:
            results.append(AIMessage(content="已达到本轮工具调用上限，请缩小问题范围。"))
        return {"messages": results, "calls": used}

    graph = StateGraph(ReActState)
    graph.add_node("reason", reason)
    graph.add_node("execute", execute)
    graph.add_edge(START, "reason")
    graph.add_conditional_edges("reason", lambda state: "execute" if state["messages"][-1].tool_calls else END,
                                {"execute": "execute", END: END})
    graph.add_conditional_edges(
        "execute", lambda state: END if isinstance(state["messages"][-1], AIMessage) else "reason",
        {"reason": "reason", END: END},
    )
    return graph.compile()


def build_prebuilt(model, tools=TOOLS, role=None):
    prompt = f"{ROLE_PROMPTS[role]}\n{SYSTEM}" if role else SYSTEM
    return create_agent(
        model=model,
        tools=list(tools),
        system_prompt=prompt,
        middleware=[ToolCallLimitMiddleware(run_limit=MAX_CALLS, exit_behavior="end")],
    )


def summarize(messages):
    trace = []
    reply = ""
    for message in messages:
        if isinstance(message, AIMessage):
            if message.tool_calls:
                names = "、".join(call["name"] for call in message.tool_calls)
                trace.append({"node": "模型", "detail": f"选择 {names}", "status": "ok"})
            elif isinstance(message.content, str) and message.content.strip():
                reply = message.content
        if isinstance(message, ToolMessage):
            try:
                result = json.loads(message.content)
                status, detail = result["status"], result["answer"]
            except (TypeError, ValueError, KeyError):
                status, detail = "error", "工具未能提供标准结果。"
            trace.append({"node": message.name or "工具", "detail": str(detail), "status": status})
    return reply or "本轮未生成答复，请缩小问题范围。", trace
