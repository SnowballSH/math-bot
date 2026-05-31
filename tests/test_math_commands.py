from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import discord
import pytest

from cogs.math import MathCog
from tests.conftest import FakeBot, FakeContext, FakeUser


@pytest.fixture
def math_cog(tmp_path: Path) -> Iterator[MathCog]:
    cog = object.__new__(MathCog)
    cog.bot = cast(Any, FakeBot())
    cog.data_dir = str(tmp_path)
    cog.db_path = str(tmp_path / "math500.db")
    cog.active = {}
    cog._ensure_db()
    cog.conn = sqlite3.connect(cog.db_path, check_same_thread=False)
    cog.conn.row_factory = sqlite3.Row
    cog.conn.execute(
        """
        INSERT INTO problems (problem, solution, answer_tex, subject, level, unique_id)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        ("What is 2+3?", "Solution is 5.", "5", "Algebra", 1, "p1"),
    )
    cog.conn.commit()
    try:
        yield cog
    finally:
        cog.conn.close()


@pytest.mark.asyncio
async def test_math_help(math_cog: MathCog) -> None:
    ctx = FakeContext()

    await cast(Any, MathCog.math.callback)(math_cog, ctx)

    assert "Math commands" in ctx.last_message
    assert "!math problem" in ctx.last_message


@pytest.mark.asyncio
async def test_math_problem_current_submit_and_leaderboard(
    math_cog: MathCog, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx = FakeContext(author=FakeUser(id=55))
    images: list[tuple[str, str, str | None]] = []

    async def fake_send_image(
        _ctx: Any,
        text: str,
        title: str,
        _color: discord.Color,
        footer: str | None = None,
    ) -> None:
        images.append((text, title, footer))

    monkeypatch.setattr(math_cog, "_send_image_embed", fake_send_image)

    await cast(Any, MathCog.math_problem.callback)(
        math_cog, ctx, args="subject=Algebra level=1"
    )
    assert math_cog.active[55] == 1
    assert images[-1][0] == "What is 2+3?"
    assert "Algebra" in images[-1][1]

    await cast(Any, MathCog.math_current.callback)(math_cog, ctx)
    assert images[-1][0] == "What is 2+3?"

    await cast(Any, MathCog.math_submit.callback)(math_cog, ctx, user_ans="2+3")
    assert "Correct" in images[-1][1]
    assert 55 not in math_cog.active

    await cast(Any, MathCog.math_leaderboard.callback)(math_cog, ctx)
    assert "user-55" in ctx.last_message
    assert "1/1" in ctx.last_message


@pytest.mark.asyncio
async def test_math_submit_invalid_wrong_and_giveup(
    math_cog: MathCog, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx = FakeContext(author=FakeUser(id=56))
    images: list[str] = []

    async def fake_send_image(
        _ctx: Any,
        text: str,
        _title: str,
        _color: discord.Color,
        footer: str | None = None,
    ) -> None:
        images.append(text + (footer or ""))

    monkeypatch.setattr(math_cog, "_send_image_embed", fake_send_image)
    math_cog.active[56] = 1

    await cast(Any, MathCog.math_submit.callback)(math_cog, ctx, user_ans="x")
    assert ctx.last_message == "Invalid format."
    assert 56 in math_cog.active

    await cast(Any, MathCog.math_submit.callback)(math_cog, ctx, user_ans="4")
    assert "Incorrect" in ctx.last_message
    assert 56 in math_cog.active

    await cast(Any, MathCog.math_giveup.callback)(math_cog, ctx)
    assert images[-1] == "Solution is 5."
    assert 56 not in math_cog.active


@pytest.mark.asyncio
async def test_math_options_and_no_problem(math_cog: MathCog) -> None:
    ctx = FakeContext()

    await cast(Any, MathCog.math_options.callback)(math_cog, ctx)
    assert "Algebra" in ctx.last_message
    assert "1" in ctx.last_message

    await cast(Any, MathCog.math_problem.callback)(
        math_cog, ctx, args="subject=Geometry level=5"
    )
    assert "No problems" in ctx.last_message


@pytest.mark.asyncio
async def test_send_image_embed_error(
    math_cog: MathCog, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx = FakeContext()

    def fail_render(_text: str) -> None:
        raise RuntimeError("missing tool")

    monkeypatch.setattr(MathCog, "_render_text_image", staticmethod(fail_render))

    await math_cog._send_image_embed(
        ctx=cast(Any, ctx), text="x", title="T", color=discord.Color.red()
    )

    assert "Error rendering LaTeX" in ctx.last_message


def test_ensure_db_populates_from_jsonl(tmp_path: Path) -> None:
    valid = {
        "problem": "What is 2+3?",
        "solution": "5",
        "answer": "5",
        "subject": "Algebra",
        "level": 1,
        "unique_id": "valid",
    }
    symbolic = {
        "problem": "Symbolic",
        "solution": "x",
        "answer": "x",
        "subject": "Algebra",
        "level": 1,
        "unique_id": "symbolic",
    }
    (tmp_path / "train.jsonl").write_text(
        json.dumps(valid) + "\n" + json.dumps(symbolic) + "\n",
        encoding="utf-8",
    )
    (tmp_path / "test.jsonl").write_text("", encoding="utf-8")

    cog = object.__new__(MathCog)
    cog.data_dir = str(tmp_path)
    cog.db_path = str(tmp_path / "math500.db")
    cog._ensure_db()

    conn = sqlite3.connect(cog.db_path)
    try:
        count = conn.execute("SELECT COUNT(*) FROM problems").fetchone()[0]
        leaderboard_count = conn.execute("SELECT COUNT(*) FROM leaderboard").fetchone()[
            0
        ]
    finally:
        conn.close()

    assert count == 1
    assert leaderboard_count == 0


def test_render_text_image_latex_and_asy() -> None:
    latex = MathCog._render_text_image(r"<math>x+1</math>")
    asy = MathCog._render_text_image(r"<asy>draw((0,0)--(1,0));</asy>")

    assert latex.getbuffer().nbytes > 0
    assert asy.getbuffer().nbytes > 0
