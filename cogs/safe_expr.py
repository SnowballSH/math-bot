from __future__ import annotations

import re
from typing import Any

from sympy import (
    Abs,
    Add,
    E,
    Float,
    I,
    Integer,
    Mod,
    Mul,
    Pow,
    Rational,
    Symbol,
    acos,
    asin,
    atan,
    binomial,
    ceiling,
    cos,
    cot,
    csc,
    exp,
    factorial,
    floor,
    gcd,
    lcm,
    log,
    pi,
    root,
    sec,
    sin,
    sqrt,
    tan,
)
from sympy.parsing.sympy_parser import (
    auto_number,
    auto_symbol,
    convert_xor,
    factorial_notation,
    parse_expr,
    repeated_decimals,
)

MAX_INPUT_LENGTH = 200

_ALLOWED_CHARS = re.compile(r"[0-9A-Za-z+\-*/^() .,!]*\Z")
_ATTRIBUTE_ACCESS = re.compile(r"\.\s*[A-Za-z_]")

_TRANSFORMATIONS = (
    auto_symbol,
    repeated_decimals,
    auto_number,
    factorial_notation,
    convert_xor,
)

_GLOBAL_DICT: dict[str, Any] = {
    "Symbol": Symbol,
    "Integer": Integer,
    "Float": Float,
    "Rational": Rational,
    "Add": Add,
    "Mul": Mul,
    "Pow": Pow,
    "Mod": Mod,
    "Abs": Abs,
    "abs": Abs,
    "sqrt": sqrt,
    "root": root,
    "exp": exp,
    "log": log,
    "ln": log,
    "factorial": factorial,
    "binomial": binomial,
    "gcd": gcd,
    "lcm": lcm,
    "floor": floor,
    "ceiling": ceiling,
    "sin": sin,
    "cos": cos,
    "tan": tan,
    "asin": asin,
    "acos": acos,
    "atan": atan,
    "sec": sec,
    "csc": csc,
    "cot": cot,
    "pi": pi,
    "E": E,
    "I": I,
}


class UnsafeExpressionError(ValueError):
    pass


def parse_user_expression(text: str) -> Any:
    if len(text) > MAX_INPUT_LENGTH:
        raise UnsafeExpressionError("expression is too long")
    if not _ALLOWED_CHARS.fullmatch(text):
        raise UnsafeExpressionError("expression contains disallowed characters")
    if _ATTRIBUTE_ACCESS.search(text):
        raise UnsafeExpressionError("attribute access is not allowed")
    try:
        return parse_expr(
            text,
            local_dict={},
            global_dict=_GLOBAL_DICT,
            transformations=_TRANSFORMATIONS,
            evaluate=False,
        )
    except UnsafeExpressionError:
        raise
    except Exception as exc:
        raise UnsafeExpressionError(f"could not parse expression: {exc}") from exc
