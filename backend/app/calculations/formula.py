import ast
import operator

from decimal import Decimal, DivisionByZero, InvalidOperation, localcontext
from typing import Callable

from app.errors import InvalidInputError, InvalidOperationError

MAX_FORMULA_AST_NODES = 100
MAX_FORMULA_ABSOLUTE_VALUE = Decimal("1e100")
BINARY_OPERATORS: dict[type[ast.operator], Callable[[Decimal, Decimal], Decimal]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
}
UNARY_OPERATORS: dict[type[ast.unaryop], Callable[[Decimal], Decimal]] = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}


def validate_formula(expression: str, input_names: set[str]) -> ast.Expression:
    try:
        parsed = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        location = f" at column {exc.offset}" if exc.offset is not None else ""
        raise InvalidInputError(f"Invalid formula syntax{location}: {exc.msg}") from exc

    nodes = list(ast.walk(parsed))

    if len(nodes) > MAX_FORMULA_AST_NODES:
        raise InvalidInputError(
            f"Formula cannot contain more than {MAX_FORMULA_AST_NODES} operations",
        )

    used_names: set[str] = set()

    for node in nodes:
        if isinstance(node, ast.Name):
            used_names.add(node.id)
            continue
        if isinstance(node, ast.Constant):
            if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
                raise InvalidInputError("Formula constants must be numbers")
            continue
        if isinstance(node, ast.BinOp):
            if type(node.op) not in BINARY_OPERATORS:
                raise InvalidInputError("Formulas only support +, -, *, and /")
            continue
        if isinstance(node, ast.UnaryOp):
            if type(node.op) not in UNARY_OPERATORS:
                raise InvalidInputError("Formulas only support unary + and -")
            continue
        if isinstance(
            node,
            (
                ast.Expression,
                ast.Load,
                ast.Add,
                ast.Sub,
                ast.Mult,
                ast.Div,
                ast.UAdd,
                ast.USub,
            ),
        ):
            continue
        raise InvalidInputError(
            "Formulas may only contain numbers, input names, parentheses, and arithmetic",
        )

    unknown_names = sorted(used_names - input_names)

    if unknown_names:
        raise InvalidInputError(
            "Formula references undeclared inputs: " + ", ".join(unknown_names),
        )

    unused_names = sorted(input_names - used_names)

    if unused_names:
        raise InvalidInputError(
            "Formula declares unused inputs: " + ", ".join(unused_names),
        )

    return parsed


def evaluate_formula(expression: str, inputs: dict[str, Decimal]) -> Decimal:
    parsed = validate_formula(expression, set(inputs))

    try:
        with localcontext() as context:
            context.prec = 38
            return _bounded_decimal(_evaluate_node(parsed.body, inputs))
    except (DivisionByZero, InvalidOperation, ZeroDivisionError) as exc:
        raise InvalidOperationError(
            "Formula could not be calculated: division by zero"
        ) from exc


def _evaluate_node(node: ast.expr, inputs: dict[str, Decimal]) -> Decimal:
    if isinstance(node, ast.Name):
        return inputs[node.id]

    if isinstance(node, ast.Constant):
        return _bounded_decimal(Decimal(str(node.value)))

    if isinstance(node, ast.UnaryOp):
        operation = UNARY_OPERATORS[type(node.op)]
        return _bounded_decimal(operation(_evaluate_node(node.operand, inputs)))

    if isinstance(node, ast.BinOp):
        operation = BINARY_OPERATORS[type(node.op)]
        left = _evaluate_node(node.left, inputs)
        right = _evaluate_node(node.right, inputs)
        return _bounded_decimal(operation(left, right))

    raise InvalidInputError("Unsupported formula expression")


def _bounded_decimal(value: Decimal) -> Decimal:
    if not value.is_finite() or abs(value) > MAX_FORMULA_ABSOLUTE_VALUE:
        raise InvalidOperationError(
            "Formula result is outside the supported numeric range"
        )
    return value
