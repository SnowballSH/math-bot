import asyncio
import os
import io
import json
import re
import sqlite3
import subprocess
import tempfile
import shutil
import logging
from subprocess import CalledProcessError, TimeoutExpired
from typing import Any, Dict, Optional

import discord
from discord.ext import commands

from cogs.answer_check import (
    check_answer,
    check_answer_in_subprocess,
    clean_answer_latex,
    parse_latex_required as _parse_latex_required,
)

logger = logging.getLogger(__name__)

RENDER_TOOL_TIMEOUT_SECONDS = 60
MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_TOOL_LOG_BYTES = 2048
RENDER_CONCURRENCY = 2

_RENDER_SEMAPHORE = asyncio.Semaphore(RENDER_CONCURRENCY)


class MathCog(commands.Cog):
    """Cog for practicing math problems with a persistent leaderboard."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.data_dir = os.path.join(os.path.dirname(__file__), "math500")
        os.makedirs(self.data_dir, exist_ok=True)
        self.db_path = os.path.join(self.data_dir, "math500.db")
        self._ensure_db()
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.active: Dict[int, int] = {}

    def _ensure_db(self) -> None:
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS problems (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    problem     TEXT NOT NULL,
                    solution    TEXT NOT NULL,
                    answer_tex  TEXT NOT NULL,
                    subject     TEXT,
                    level       INTEGER,
                    unique_id   TEXT
                );
                """
            )
            # leaderboard: store only user_id, counts
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS leaderboard (
                    user_id   INTEGER PRIMARY KEY,
                    solved    INTEGER DEFAULT 0,
                    attempted INTEGER DEFAULT 0
                );
                """
            )
            conn.commit()
            problem_count = conn.execute("SELECT COUNT(*) FROM problems").fetchone()[0]
            if problem_count == 0:
                self._populate_problems(conn)
                conn.commit()
        except sqlite3.Error as e:
            logger.error("Database initialization failed: %s", e, exc_info=True)
            raise
        finally:
            conn.close()

    def _populate_problems(self, conn: sqlite3.Connection) -> None:
        inserted = 0
        skipped = 0
        for fname in ("train.jsonl", "test.jsonl"):
            path = os.path.join(self.data_dir, fname)
            if not os.path.exists(path):
                logger.warning("Problems file not found: %s", path)
                continue
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        ex = json.loads(line)
                        ans_tex = self._clean_answer_latex(ex.get("answer", ""))
                        expr = _parse_latex_required(ans_tex)
                        if expr.free_symbols:
                            continue
                        conn.execute(
                            "INSERT INTO problems (problem, solution, answer_tex, subject, level, unique_id)"
                            " VALUES (?, ?, ?, ?, ?, ?)",
                            (
                                ex.get("problem", ""),
                                ex.get("solution", ""),
                                ans_tex,
                                ex.get("subject", ""),
                                ex.get("level", 0),
                                ex.get("unique_id", ""),
                            ),
                        )
                        inserted += 1
                    except Exception as e:
                        skipped += 1
                        logger.debug("Skipping invalid example: %s", e)
                        continue
        logger.info("Loaded %s math problems; skipped %s examples", inserted, skipped)

    def _get_random_problem(
        self, subject: Optional[str] = None, level: Optional[int] = None
    ) -> Optional[sqlite3.Row]:
        sql = "SELECT * FROM problems"
        params: list = []
        filters: list = []
        if subject:
            filters.append("LOWER(subject) = LOWER(?)")
            params.append(subject)
        if level is not None:
            filters.append("level = ?")
            params.append(level)
        if filters:
            sql += " WHERE " + " AND ".join(filters)
        sql += " ORDER BY RANDOM() LIMIT 1"
        try:
            return self.conn.execute(sql, params).fetchone()
        except sqlite3.Error as e:
            logger.error("Failed to fetch problem: %s", e, exc_info=True)
            return None

    def _update_leaderboard(
        self, user: discord.abc.User, solved_inc: int, attempted_inc: int
    ) -> None:
        uid = user.id
        try:
            self.conn.execute(
                """
                INSERT INTO leaderboard(user_id, solved, attempted)
                VALUES (?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    solved    = leaderboard.solved    + excluded.solved,
                    attempted = leaderboard.attempted + excluded.attempted
                """,
                (uid, solved_inc, attempted_inc),
            )
            self.conn.commit()
        except sqlite3.Error as e:
            logger.error(
                "Leaderboard update failed for user %s: %s", uid, e, exc_info=True
            )

    @staticmethod
    def _clean_answer_latex(ans: str) -> str:
        return clean_answer_latex(ans)

    @staticmethod
    def _convert_tags(text: str) -> str:
        """Convert <math> and <asy> HTML tags to plain LaTeX/Asy blocks."""
        text = re.sub(
            r"<math>(.*?)</math>",
            lambda m: f"${m.group(1)}$",
            text,
            flags=re.DOTALL | re.IGNORECASE,
        )
        text = re.sub(
            r"<asy>(.*?)</asy>",
            lambda m: f"[asy]{m.group(1)}[/asy]",
            text,
            flags=re.DOTALL | re.IGNORECASE,
        )
        return text

    @staticmethod
    def _render_text_image(text: str) -> io.BytesIO:
        """Render LaTeX or Asymptote text to an image."""
        # Preprocess custom math tags
        text = MathCog._convert_tags(text)

        # Detect Asymptote blocks of the form [asy]...[/asy]
        asy_pattern = re.compile(r"\[asy\](.*?)\[/asy\]", re.DOTALL | re.IGNORECASE)
        has_asy = False

        def _asy_repl(match: re.Match) -> str:
            nonlocal has_asy
            has_asy = True
            code = match.group(1).strip()
            if "unitsize" not in code:
                code = "unitsize(38pt);\n" + code
            if "import olympiad;" not in code:
                code = "import olympiad;\n" + code
            return (
                "\n\\begin{center}\n\\begin{asy}\n"
                + code
                + "\n\\end{asy}\n\\end{center}\n"
            )

        text = asy_pattern.sub(_asy_repl, text)

        preamble = [
            "\\documentclass{article}",
            "\\usepackage[margin=10pt]{geometry}",
            "\\usepackage[active,tightpage]{preview}",
            "\\PreviewEnvironment{preview}",
            "\\setlength\\PreviewBorder{10pt}",
            "\\usepackage{xcolor,amsmath,amssymb}",
        ]

        if has_asy:
            preamble.append("\\usepackage{asymptote}")

        doc = (
            "\n".join(preamble)
            + "\n\\begin{document}\n\\begin{preview}\n"
            + f"{text}\n"
            + "\\end{preview}\n\\end{document}\n"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            tex_path = os.path.join(tmpdir, "out.tex")
            with open(tex_path, "w", encoding="utf-8") as f:
                f.write(doc)
            if has_asy:
                olymp = os.path.join(
                    os.path.dirname(__file__), "math500", "olympiad.asy"
                )
                if os.path.exists(olymp):
                    shutil.copy(olymp, tmpdir)
            try:
                MathCog._run_render_tool(
                    [
                        "pdflatex",
                        "-interaction=nonstopmode",
                        "-halt-on-error",
                        tex_path,
                    ],
                    tmpdir,
                )

                if has_asy:
                    for asy_file in sorted(
                        p for p in os.listdir(tmpdir) if p.endswith(".asy")
                    ):
                        MathCog._run_render_tool(["asy", asy_file], tmpdir)

                    MathCog._run_render_tool(
                        [
                            "pdflatex",
                            "-interaction=nonstopmode",
                            "-halt-on-error",
                            tex_path,
                        ],
                        tmpdir,
                    )

                MathCog._run_render_tool(
                    [
                        "pdftocairo",
                        "-png",
                        "-singlefile",
                        "-r",
                        "150",
                        os.path.join(tmpdir, "out.pdf"),
                        os.path.join(tmpdir, "out"),
                    ],
                    tmpdir,
                )
            except FileNotFoundError as e:
                logger.error("LaTeX tool missing: %s", e)
                raise RuntimeError(f"Rendering tool not found: {e}") from e
            except TimeoutExpired as e:
                logger.error("LaTeX subprocess timed out: %s", e)
                raise RuntimeError("Rendering timed out") from e
            except CalledProcessError as e:
                logger.error(
                    "LaTeX subprocess failed: %s; log tail: %s",
                    e,
                    MathCog._read_tool_log(tmpdir),
                )
                raise RuntimeError("Failed to render LaTeX") from e

            buf = io.BytesIO()
            img_path = os.path.join(tmpdir, "out.png")
            if not os.path.exists(img_path):
                logger.error("Expected image not found: %s", img_path)
                raise RuntimeError("Rendered image not found")
            if os.path.getsize(img_path) > MAX_IMAGE_BYTES:
                logger.error("Rendered image exceeds size cap: %s", img_path)
                raise RuntimeError("Rendered image too large")
            with open(img_path, "rb") as img_file:
                buf.write(img_file.read())
            buf.seek(0)
            return buf

    @staticmethod
    def _run_render_tool(args: list[str], cwd: str) -> None:
        log_path = os.path.join(cwd, "tool-output.log")
        with open(log_path, "ab") as log_file:
            subprocess.run(
                args,
                cwd=cwd,
                stdout=log_file,
                stderr=log_file,
                check=True,
                timeout=RENDER_TOOL_TIMEOUT_SECONDS,
            )

    @staticmethod
    def _read_tool_log(cwd: str) -> str:
        log_path = os.path.join(cwd, "tool-output.log")
        try:
            with open(log_path, "rb") as log_file:
                log_file.seek(0, os.SEEK_END)
                size = log_file.tell()
                log_file.seek(max(0, size - MAX_TOOL_LOG_BYTES))
                return log_file.read().decode(errors="replace")
        except OSError:
            return ""

    def _check_answer(
        self, user_ans: str, correct_expr: Any
    ) -> tuple[bool, Optional[str]]:
        return check_answer(user_ans, correct_expr)

    @staticmethod
    def _parse_problem_args(args: str | None) -> tuple[Optional[str], Optional[int]]:
        """Parse arguments for the problem command.

        Returns a tuple ``(subject, level)`` where each value may be ``None``.
        Matching is case-insensitive and subjects may contain spaces.
        Example::

            subject, level = MathCog._parse_problem_args(
                "subject=Counting & Probability level=3"
            )
        """

        subject = None
        level = None
        if not args:
            return subject, level

        m_level = re.search(r"level=(\d+)", args, re.IGNORECASE)
        if m_level:
            level = int(m_level.group(1))

        m_subject = re.search(r"subject=([^\n]*?)(?=\s+level=|$)", args, re.IGNORECASE)
        if m_subject:
            subject = m_subject.group(1).strip()

        return subject, level

    async def _send_image_embed(
        self,
        ctx: commands.Context,
        text: str,
        title: str,
        color: discord.Color,
        footer: Optional[str] = None,
    ) -> None:
        try:
            async with _RENDER_SEMAPHORE:
                buf = await asyncio.to_thread(self._render_text_image, text)
        except RuntimeError as e:
            logger.error("Image rendering error for '%s': %s", title, e)
            await ctx.send(f"Error rendering LaTeX: {e}\nRaw LaTeX:\n```{text}```")
            return

        file = discord.File(buf, filename="image.png")
        embed = discord.Embed(title=title, color=color)
        embed.set_image(url="attachment://image.png")
        if footer:
            embed.set_footer(text=footer)
        await ctx.send(file=file, embed=embed)

    async def cog_command_error(
        self, ctx: commands.Context, error: commands.CommandError
    ) -> None:
        if isinstance(error, commands.CommandOnCooldown):
            await ctx.send(
                f"⏳ Slow down — try again in {error.retry_after:.1f} seconds."
            )
            return
        logger.error("Command error in %s: %s", ctx.command, error, exc_info=error)

    @commands.group(name="math", invoke_without_command=True)
    async def math(self, ctx: commands.Context) -> None:
        commands_list = (
            f"`{ctx.clean_prefix}math problem [subject=<subject>] [level=<n>]` → new problem",
            f"`{ctx.clean_prefix}math submit <answer>` → submit answer",
            f"`{ctx.clean_prefix}math giveup` → show solution",
            f"`{ctx.clean_prefix}math current` → view current",
            f"`{ctx.clean_prefix}math leaderboard [rate]` → show leaderboard",
            f"`{ctx.clean_prefix}math options` → list subjects and levels",
        )
        await ctx.send("__**Math commands**__\n" + "\n".join(commands_list))

    @math.command(name="problem")
    @commands.cooldown(1, 15, commands.BucketType.user)
    async def math_problem(
        self, ctx: commands.Context, *, args: Optional[str] = None
    ) -> None:
        try:
            subject, level = self._parse_problem_args(args)

            uid = ctx.author.id
            if uid in self.active:
                await ctx.send("You already have an active problem.")
                return

            row = self._get_random_problem(subject, level)
            if not row:
                msg = "No problems"
                if subject:
                    msg += f" for subject `{subject}`"
                if level is not None:
                    msg += f" at level {level}"
                await ctx.send(msg + ".")
                return

            self.active[uid] = row["id"]
            extras = []
            if subject:
                extras.append(subject)
            if level is not None:
                extras.append(f"level {level}")
            title = "📝 Problem" + (" — " + ", ".join(extras) if extras else "")

            await self._send_image_embed(
                ctx,
                row["problem"],
                title,
                discord.Color.dark_blue(),
                f"Submit with `{ctx.clean_prefix}math submit <answer>`",
            )
        except Exception as e:
            logger.exception("Error in problem command: %s", e)
            await ctx.send("An unexpected error occurred. Please try again later.")

    @math.command(name="submit", aliases=["answer"])
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def math_submit(self, ctx: commands.Context, *, user_ans: str) -> None:
        try:
            uid = ctx.author.id
            if uid not in self.active:
                await ctx.send(
                    f"No active problem. Use `{ctx.clean_prefix}math problem` to start."
                )
                return

            pid = self.active[uid]
            row = self.conn.execute(
                "SELECT solution, answer_tex FROM problems WHERE id = ?", (pid,)
            ).fetchone()
            correct, err = await check_answer_in_subprocess(user_ans, row["answer_tex"])

            if not correct:
                if err == "invalid":
                    msg = "Invalid format."
                elif err == "timeout":
                    msg = (
                        "⏱️ Evaluation took too long. Try a simpler form of your answer."
                    )
                else:
                    msg = f"❌ Incorrect. Try again or use `{ctx.clean_prefix}math giveup`."
                await ctx.send(msg)
                return

            self._update_leaderboard(ctx.author, solved_inc=1, attempted_inc=1)
            del self.active[uid]

            await self._send_image_embed(
                ctx, row["solution"], "✅ Correct! Solution", discord.Color.green()
            )
        except Exception as e:
            logger.exception("Error in submit command: %s", e)
            await ctx.send("An unexpected error occurred. Please try again later.")

    @math.command(name="giveup")
    @commands.cooldown(1, 10, commands.BucketType.user)
    async def math_giveup(self, ctx: commands.Context) -> None:
        try:
            uid = ctx.author.id
            if uid not in self.active:
                await ctx.send(
                    f"No active problem. Use `{ctx.clean_prefix}math problem` to start."
                )
                return

            pid = self.active.pop(uid)
            row = self.conn.execute(
                "SELECT solution FROM problems WHERE id = ?", (pid,)
            ).fetchone()
            self._update_leaderboard(ctx.author, solved_inc=0, attempted_inc=1)

            await self._send_image_embed(
                ctx, row["solution"], "ℹ️ Solution", discord.Color.orange()
            )
        except Exception as e:
            logger.exception("Error in giveup command: %s", e)
            await ctx.send("An unexpected error occurred. Please try again later.")

    @math.command(name="current")
    @commands.cooldown(1, 10, commands.BucketType.user)
    async def math_current(self, ctx: commands.Context) -> None:
        try:
            uid = ctx.author.id
            if uid not in self.active:
                await ctx.send(
                    f"No active problem. Use `{ctx.clean_prefix}math problem` to start."
                )
                return

            row = self.conn.execute(
                "SELECT problem FROM problems WHERE id = ?", (self.active[uid],)
            ).fetchone()

            await self._send_image_embed(
                ctx,
                row["problem"],
                "🔎 Current",
                discord.Color.dark_blue(),
                f"Submit with `{ctx.clean_prefix}math submit <answer>` or `{ctx.clean_prefix}math giveup`",
            )
        except Exception as e:
            logger.exception("Error in current command: %s", e)
            await ctx.send("An unexpected error occurred. Please try again later.")

    @math.command(name="options")
    async def math_options(self, ctx: commands.Context) -> None:
        """List all available subjects and levels."""
        try:
            subjects_rows = self.conn.execute(
                "SELECT DISTINCT subject FROM problems WHERE subject != '' ORDER BY subject"
            ).fetchall()
            subjects = [r["subject"] for r in subjects_rows if r["subject"]]

            levels_rows = self.conn.execute(
                "SELECT DISTINCT level FROM problems ORDER BY level"
            ).fetchall()
            levels = [str(r["level"]) for r in levels_rows if r["level"] is not None]

            lines = []
            if subjects:
                lines.append("__**Subjects**__: " + ", ".join(subjects))
            if levels:
                lines.append("__**Levels**__: " + ", ".join(levels))
            if not lines:
                lines.append("No subjects or levels found.")

            await ctx.send("\n".join(lines))
        except Exception as e:
            logger.exception("Error in options command: %s", e)
            await ctx.send("An unexpected error occurred. Please try again later.")

    @math.command(name="leaderboard")
    async def math_leaderboard(
        self, ctx: commands.Context, sort_by: Optional[str] = None
    ) -> None:
        try:
            key = (sort_by or "solved").lower()
            if key in ("rate", "solve_rate"):
                order = "CAST(solved AS FLOAT)/attempted DESC"
                title = "📊 Leaderboard by solve rate"
            else:
                order = "solved DESC"
                title = "📊 Leaderboard by solved count"

            rows = self.conn.execute(
                f"""
                SELECT user_id, solved, attempted,
                       CASE WHEN attempted>0
                            THEN ROUND(solved*100.0/attempted,1)||'%'
                            ELSE 'N/A'
                       END AS rate
                FROM leaderboard
                ORDER BY {order};
                """
            ).fetchall()

            lines = []
            for i, r in enumerate(rows):
                if ctx.guild is None:
                    user = await self.bot.fetch_user(r["user_id"])
                else:
                    user = ctx.guild.get_member(
                        r["user_id"]
                    ) or await self.bot.fetch_user(r["user_id"])
                name = user.display_name if hasattr(user, "display_name") else user.name
                lines.append(
                    f"{i + 1}. {name} — {r['solved']}/{r['attempted']} ({r['rate']})"
                )

            await ctx.send(f"**{title}**\n" + "\n".join(lines))
        except Exception as e:
            logger.exception("Error in leaderboard command: %s", e)
            await ctx.send("An unexpected error occurred. Please try again later.")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(MathCog(bot))
