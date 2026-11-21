import json
import os
import re
from uuid import uuid4

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.utils.function_calling import convert_to_openai_tool


ERROR_CODE = re.compile(r"\b(?:ERR[- ]?)?(\d{3})\b", re.I)
SEATS = re.compile(r"(?<!\d)(\d{1,3})\s*(?:个?席位|人)")
MONTHS = re.compile(r"(?<!\d)(\d{1,3})\s*个?月")


class DemoModel(BaseChatModel):
    """Deterministic chat responses for the offline examples and comparison."""

    tool_names: frozenset[str] = frozenset()

    @property
    def _llm_type(self) -> str:
        return "support-demo"

    def bind_tools(self, tools, *, tool_choice=None, **kwargs):
        names = frozenset(convert_to_openai_tool(tool)["function"]["name"] for tool in tools)
        return self.model_copy(update={"tool_names": names})

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        start = next(index for index in range(len(messages) - 1, -1, -1) if isinstance(messages[index], HumanMessage))
        text = str(messages[start].content).strip()
        response = self.next_message(text, messages[start + 1:])
        return ChatResult(generations=[ChatGeneration(message=response)])

    def next_message(self, text, history):
        if history and isinstance(history[-1], ToolMessage):
            message = history[-1]
            data = json.loads(message.content)
            seats = SEATS.search(text)
            months = MONTHS.search(text)
            if message.name == "lookup_plan" and data.get("status") == "found" and (seats or months):
                count = int(seats[1]) if seats else 1
                duration = int(months[1]) if months else 1
                return self.call("calculate", expression=f"{data['monthly_price']} * {count} * {duration}")
            return AIMessage(content=data.get("answer") or "工具未能返回可用结果。")
        if text.startswith("计算"):
            return self.call("calculate", expression=text[2:].lstrip(" ：:"))
        if any(word in text for word in ("发票", "开票", "账单", "扣款")):
            return self.call("invoice_policy")
        code = ERROR_CODE.search(text)
        if code:
            return self.call("lookup_error", code=code[1])
        plan = next((name for name in ("基础版", "专业版") if name in text), None)
        if plan:
            return self.call("lookup_plan", plan=plan)
        if self.tool_names == {"lookup_error"}:
            return AIMessage(content="请提供三位错误码和操作步骤，例如报错 429。")
        if "lookup_plan" in self.tool_names and "invoice_policy" not in self.tool_names:
            return AIMessage(content="你想了解基础版还是专业版？如需报价，请同时提供席位数和月数。")
        return AIMessage(content="请提供错误码、想了解的套餐或发票问题，也可输入「计算 (99 * 3)」。")

    def call(self, name, **arguments):
        if name not in self.tool_names:
            return AIMessage(content="当前角色无法处理这个请求，请补充问题或换一个模式。")
        return AIMessage(content="", tool_calls=[{"name": name, "args": arguments, "id": uuid4().hex}])


def select_model(mode: str = "demo"):
    if mode == "demo":
        return DemoModel()
    if mode != "qwen":
        raise ValueError("请选择 demo 或 qwen。")
    credential = os.getenv("DASHSCOPE_API_KEY", "").strip()
    if not credential:
        raise ValueError("当前进程缺少百炼凭据。")
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        model="qwen4-max",
        api_key=credential,
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        use_responses_api=False,
        streaming=False,
        extra_body={"enable_thinking": False},
        max_tokens=512,
        max_retries=0,
        timeout=15,
    )
