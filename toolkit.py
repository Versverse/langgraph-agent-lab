import json

from langchain_core.tools import tool

from expressions import ExpressionError, evaluate


PLANS = {"基础版": 49, "专业版": 99}
ERRORS = {
    "429": "请求触发限流。降低并发，按 Retry-After 提示等待后重试。",
    "401": "请求未通过认证。检查登录状态与授权，再发起请求。",
    "503": "服务暂不可用。等待服务恢复后重试，并保留请求编号。",
}


def result(**fields) -> str:
    return json.dumps(fields, ensure_ascii=False)


@tool
def lookup_error(code: str) -> str:
    """按三位错误码查询演示技术知识库。"""
    code = code.strip()
    answer = ERRORS.get(code)
    return result(status="found", answer=answer) if answer else result(
        status="missing", answer="暂无该错误码的记录，请提供错误提示和操作步骤。"
    )


@tool
def lookup_plan(plan: str) -> str:
    """查询演示套餐的每席位月价，套餐名为基础版或专业版。"""
    if plan not in PLANS:
        return result(status="missing", answer="请选择基础版或专业版。")
    return result(status="found", plan=plan, monthly_price=PLANS[plan],
                  answer=f"{plan}为每席位每月 {PLANS[plan]} 元。")


@tool
def invoice_policy() -> str:
    """查询演示客服的电子发票政策。"""
    return result(status="found", answer="订单完成后，可在订单详情申请电子发票。请核对发票抬头。")


@tool
def calculate(expression: str) -> str:
    """计算一条算术表达式。支持四则运算和 abs、min、max、round。"""
    try:
        value = evaluate(expression)
    except ExpressionError as error:
        return result(status="rejected", answer=str(error))
    return result(status="ok", value=value, answer=f"计算结果为 {value:g}。")


ROLE_TOOLS = {
    "technical": (lookup_error,),
    "sales": (lookup_plan, calculate),
    "billing": (invoice_policy,),
}
TOOLS = (lookup_error, lookup_plan, invoice_policy, calculate)
