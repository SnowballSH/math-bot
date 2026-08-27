from __future__ import annotations

import io
import json
import sys
import time

import pytest
from sympy.parsing.latex import parse_latex

from cogs.answer_check import (
    check_answer,
    check_answer_in_subprocess,
    check_answer_text,
    main,
)


@pytest.fixture
def correct_five():
    return parse_latex("5")


def test_check_answer_correct(correct_five) -> None:
    assert check_answer("5", correct_five) == (True, None)
    assert check_answer("$5$", correct_five) == (True, None)
    assert check_answer("2+3", correct_five) == (True, None)
    assert check_answer(r"$\boxed{5}$", correct_five) == (True, None)


def test_check_answer_wrong_and_invalid(correct_five) -> None:
    assert check_answer("6", correct_five) == (False, "wrong")
    assert check_answer("five", correct_five) == (False, "invalid")
    assert check_answer("x + 1", correct_five) == (False, "invalid")


def test_check_answer_rejects_hostile(correct_five) -> None:
    hostile = [
        "__import__('os').system('echo hi')",
        "Symbol('x').__class__",
        "().__class__.__mro__[1].__subclasses__()",
        "9" * 500,
    ]
    for text in hostile:
        assert check_answer(text, correct_five) == (False, "invalid")


def test_check_answer_attribute_access_never_evaluates(correct_five) -> None:
    correct, err = check_answer("(1).conjugate + 4", correct_five)
    assert not correct
    assert err in ("invalid", "wrong")


def test_check_answer_text() -> None:
    assert check_answer_text("2+3", "5") == (True, None)
    assert check_answer_text("4", "5") == (False, "wrong")
    assert check_answer_text("5", r"\frac{") == (False, "invalid")


def test_worker_main_roundtrip(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    payload = json.dumps({"user_ans": "2+3", "answer_tex": "5"})
    monkeypatch.setattr(sys, "stdin", io.StringIO(payload))
    main()
    assert json.loads(capsys.readouterr().out) == {"correct": True, "error": None}


@pytest.mark.asyncio
async def test_subprocess_checks_normal_answer() -> None:
    assert await check_answer_in_subprocess("2+3", "5", timeout=60.0) == (True, None)


@pytest.mark.asyncio
async def test_subprocess_kills_slow_expression() -> None:
    start = time.monotonic()
    result = await check_answer_in_subprocess(r"\cos(9^{9^{9}})", "5", timeout=3.0)
    elapsed = time.monotonic() - start
    assert result == (False, "timeout")
    assert elapsed < 20
