from __future__ import annotations

from typing import Any, cast

import pytest

from cogs.prac import PracticeCog
from tests.conftest import FakeBot, FakeContext


@pytest.fixture
def cog() -> PracticeCog:
    return PracticeCog(cast(Any, FakeBot()))


@pytest.mark.asyncio
async def test_prac_help(cog: PracticeCog) -> None:
    ctx = FakeContext()

    await cast(Any, PracticeCog.prac.callback)(cog, ctx)

    assert "Practice commands" in ctx.last_message
    assert "!prac square" in ctx.last_message


@pytest.mark.asyncio
async def test_square_submit_wrong_then_correct(
    cog: PracticeCog, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx = FakeContext()
    monkeypatch.setattr("cogs.prac.random.randint", lambda _start, _end: 12)

    await cast(Any, PracticeCog.prac_square.callback)(cog, ctx)
    assert cog.problems[ctx.author.id]["answer"] == 144

    await cast(Any, PracticeCog.prac_submit.callback)(cog, ctx, "143")
    assert "not correct" in ctx.last_message
    assert ctx.author.id in cog.problems

    await cast(Any, PracticeCog.prac_submit.callback)(cog, ctx, "144")
    assert "Correct" in ctx.last_message
    assert ctx.author.id not in cog.problems


@pytest.mark.asyncio
async def test_submit_rejects_missing_and_non_integer(cog: PracticeCog) -> None:
    ctx = FakeContext()

    await cast(Any, PracticeCog.prac_submit.callback)(cog, ctx, "x")
    assert "don't have an active problem" in ctx.last_message

    cog.problems[ctx.author.id] = {"type": "square", "n": 5, "answer": 25}
    await cast(Any, PracticeCog.prac_submit.callback)(cog, ctx, "twenty-five")
    assert "integer answer" in ctx.last_message
    assert ctx.author.id in cog.problems


@pytest.mark.asyncio
async def test_modinv_current_and_giveup(
    cog: PracticeCog, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx = FakeContext()
    values = iter([7, 3])
    monkeypatch.setattr("cogs.prac.random.randint", lambda _start, _end: next(values))

    await cast(Any, PracticeCog.prac_modinv.callback)(cog, ctx)
    assert cog.problems[ctx.author.id]["answer"] == 5

    await cast(Any, PracticeCog.prac_current.callback)(cog, ctx)
    assert "inverse of 3 modulo 7" in ctx.last_message

    await cast(Any, PracticeCog.prac_giveup.callback)(cog, ctx)
    assert "answer was: **5**" in ctx.last_message
    assert ctx.author.id not in cog.problems


@pytest.mark.asyncio
async def test_active_problem_blocks_new_problem(cog: PracticeCog) -> None:
    ctx = FakeContext()
    cog.problems[ctx.author.id] = {"type": "square", "n": 2, "answer": 4}

    await cast(Any, PracticeCog.prac_square.callback)(cog, ctx)

    assert "already have an active problem" in ctx.last_message


@pytest.mark.asyncio
async def test_missing_current_and_giveup(cog: PracticeCog) -> None:
    ctx = FakeContext()

    await cast(Any, PracticeCog.prac_current.callback)(cog, ctx)
    assert "don't have an active problem" in ctx.last_message

    await cast(Any, PracticeCog.prac_giveup.callback)(cog, ctx)
    assert "don't have an active problem to give up" in ctx.last_message


@pytest.mark.asyncio
async def test_unknown_problem_type_fallback(cog: PracticeCog) -> None:
    ctx = FakeContext()
    cog.problems[ctx.author.id] = cast(Any, {"type": "unknown", "answer": 9})

    await cast(Any, PracticeCog.prac_current.callback)(cog, ctx)
    assert "Unknown problem type" in ctx.last_message

    await cast(Any, PracticeCog.prac_giveup.callback)(cog, ctx)
    assert "Unknown problem" in ctx.last_message
    assert "answer was: **9**" in ctx.last_message
