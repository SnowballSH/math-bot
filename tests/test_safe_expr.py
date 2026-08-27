from __future__ import annotations

import pytest
from sympy import N

from cogs.safe_expr import (
    MAX_INPUT_LENGTH,
    UnsafeExpressionError,
    parse_user_expression,
)


@pytest.mark.parametrize(
    "text",
    [
        "__import__('os').system('echo hi')",
        "().__class__.__mro__[1].__subclasses__()",
        "Symbol('x').__class__",
        "(1).conjugate",
        "1 .denominator",
        "cos.func",
        "open('/etc/passwd')",
        "'a'.join('bc')",
        '"a" + "b"',
        "[1,2]",
        "{1: 2}",
        "a=1",
        "1;2",
        "1|2",
        "lambda: 1",
        "x\\y",
        "exec(1)",
        "eval(1)",
        "9" * (MAX_INPUT_LENGTH + 1),
        ("2**" * 80) + "2",
    ],
)
def test_hostile_inputs_rejected(text: str) -> None:
    with pytest.raises(UnsafeExpressionError):
        parse_user_expression(text)


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("5", 5.0),
        ("2+3", 5.0),
        ("3/4", 0.75),
        ("2^10", 1024.0),
        ("2**10", 1024.0),
        ("sqrt(16)", 4.0),
        ("6!", 720.0),
        ("binomial(5,2)", 10.0),
        ("1.5", 1.5),
        (".5 + 0.25", 0.75),
        ("gcd(12, 18)", 6.0),
        ("Abs(-3)", 3.0),
    ],
)
def test_safe_inputs_evaluate(text: str, value: float) -> None:
    expr = parse_user_expression(text)
    assert not expr.free_symbols
    assert abs(float(N(expr, 15)) - value) < 1e-9


def test_unknown_names_become_symbols() -> None:
    expr = parse_user_expression("open")
    assert expr.free_symbols

    expr = parse_user_expression("x + 1")
    assert expr.free_symbols


def test_length_cap_boundary() -> None:
    parse_user_expression("1" + "+1" * ((MAX_INPUT_LENGTH - 1) // 2))
    with pytest.raises(UnsafeExpressionError):
        parse_user_expression("1" + "+1" * (MAX_INPUT_LENGTH // 2 + 1))
