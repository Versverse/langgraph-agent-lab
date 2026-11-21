"""Evaluate a small arithmetic language over bounded numeric values."""

import ast
import math
import operator


MAX_MAGNITUDE = 10**12
BINARY = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv}
UNARY = {ast.UAdd: operator.pos, ast.USub: operator.neg}
FUNCTIONS = {"abs": (abs, 1, 1), "min": (min, 2, 8), "max": (max, 2, 8), "round": (round, 1, 2)}


class ExpressionError(ValueError):
    pass


def evaluate(expression: str) -> int | float:
    text = expression.strip()
    if not text or len(text) > 240:
        raise ExpressionError("表达式长度需在 1 至 240 字符内。")
    try:
        tree = ast.parse(text, mode="eval")
    except (SyntaxError, ValueError):
        raise ExpressionError("请输入单条算术表达式，例如 (99 * 3) + 20。") from None
    if sum(1 for _ in ast.walk(tree)) > 64:
        raise ExpressionError("表达式复杂度超出范围。")
    return visit(tree.body, 0)


def visit(node: ast.AST, depth: int) -> int | float:
    if depth > 12:
        raise ExpressionError("表达式嵌套过深。")
    if isinstance(node, ast.Constant) and type(node.value) in (int, float):
        value = node.value
    elif isinstance(node, ast.BinOp) and type(node.op) in BINARY:
        left, right = visit(node.left, depth + 1), visit(node.right, depth + 1)
        try:
            value = BINARY[type(node.op)](left, right)
        except ZeroDivisionError:
            raise ExpressionError("除数不能为零。") from None
    elif isinstance(node, ast.UnaryOp) and type(node.op) in UNARY:
        value = UNARY[type(node.op)](visit(node.operand, depth + 1))
    elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in FUNCTIONS and not node.keywords:
        function, minimum, maximum = FUNCTIONS[node.func.id]
        if not minimum <= len(node.args) <= maximum:
            raise ExpressionError("函数参数数量超出范围。")
        args = [visit(arg, depth + 1) for arg in node.args]
        if node.func.id == "round" and len(args) == 2 and not (type(args[1]) is int and 0 <= args[1] <= 6):
            raise ExpressionError("round 的精度须为 0 至 6 的整数。")
        value = function(*args)
    else:
        raise ExpressionError("只支持数字、四则运算和 abs、min、max、round。")
    if abs(value) > MAX_MAGNITUDE or not math.isfinite(value):
        raise ExpressionError("数值超出可计算范围。")
    return value
