import os, sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import pytest
from sympy.parsing.latex import parse_latex
from cogs.math import MathCog


@pytest.fixture
def cog():
    # Create MathCog instance without running __init__ to avoid side effects
    return object.__new__(MathCog)


def test_clean_answer_strips_boxed(cog):
    assert MathCog._clean_answer_latex(r"\boxed{5}") == "5"


def test_clean_answer_collapse_dollars(cog):
    assert MathCog._clean_answer_latex(r"$$5$$") == "$5$"
    assert MathCog._clean_answer_latex(r"$$\boxed{3}$$") == "$3$"


def test_check_answer_correct_simple(cog):
    expr = parse_latex("5")
    assert MathCog._check_answer(cog, "5", expr) == (True, None)
    assert MathCog._check_answer(cog, "$5$", expr) == (True, None)
    assert MathCog._check_answer(cog, r"$\boxed{5}$", expr) == (True, None)


def test_check_answer_wrong(cog):
    expr = parse_latex("5")
    assert MathCog._check_answer(cog, "6", expr) == (False, "wrong")


def test_check_answer_invalid(cog):
    expr = parse_latex("5")
    assert MathCog._check_answer(cog, "five", expr) == (False, "invalid")


def test_check_answer_numeric_expression(cog):
    expr = parse_latex("5")
    assert MathCog._check_answer(cog, "2+3", expr) == (True, None)


def test_check_answer_malicious_input(cog):
    expr = parse_latex("5")
    ok, err = MathCog._check_answer(cog, "__import__('os').system('echo hi')", expr)
    assert not ok
