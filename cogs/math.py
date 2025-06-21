import os
import io
import json
import re
import sqlite3
import subprocess
import tempfile
import logging
from subprocess import PIPE, CalledProcessError
from typing import Any, Dict, Optional

import discord
from discord.ext import commands
from sympy import N
from sympy.parsing.latex import parse_latex

logger = logging.getLogger(__name__)


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
        first_init = not os.path.exists(self.db_path)
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
            if first_init:
                self._populate_problems(conn)
                conn.commit()
        except sqlite3.Error as e:
            logger.error("Database initialization failed: %s", e, exc_info=True)
            raise
        finally:
            conn.close()

    def _populate_problems(self, conn: sqlite3.Connection) -> None:
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
                        expr = parse_latex(ans_tex)
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
                    except (json.JSONDecodeError, Exception) as e:
                        logger.warning("Skipping invalid example: %s", e)
                        continue

    def _get_random_problem(
        self, subject: Optional[str] = None, level: Optional[int] = None
    ) -> Optional[sqlite3.Row]:
        sql = "SELECT * FROM problems"
        params: list = []
        filters: list = []
        if subject:
            filters.append("subject = ?")
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
        cleaned = re.sub(r"\\boxed\s*\{([^}]*)\}", r"\1", ans)
        return cleaned.replace("$$", "$")

    def _render_text_image(self, text: str) -> io.BytesIO:
        # Detect Asymptote blocks of the form [asy]...[/asy]
        asy_pattern = re.compile(r"\[asy\](.*?)\[/asy\]", re.DOTALL)
        has_asy = False

        def repl(match: re.Match[str]) -> str:
            nonlocal has_asy
            has_asy = True
            body = match.group(1).strip()
            if "import olympiad" not in body:
                body = "import olympiad;\n" + body
            return "\n\\begin{asy}\n" + body + "\n\\end{asy}\n"

        text = asy_pattern.sub(repl, text)

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
            try:
                subprocess.run(
                    [
                        "pdflatex",
                        "-interaction=nonstopmode",
                        "-halt-on-error",
                        tex_path,
                    ],
                    cwd=tmpdir,
                    stdout=PIPE,
                    stderr=PIPE,
                    check=True,
                )

                if has_asy:
                    for asy_file in sorted(
                        p for p in os.listdir(tmpdir) if p.endswith(".asy")
                    ):
                        subprocess.run(
                            ["asy", asy_file],
                            cwd=tmpdir,
                            stdout=PIPE,
                            stderr=PIPE,
                            check=True,
                        )

                    subprocess.run(
                        [
                            "pdflatex",
                            "-interaction=nonstopmode",
                            "-halt-on-error",
                            tex_path,
                        ],
                        cwd=tmpdir,
                        stdout=PIPE,
                        stderr=PIPE,
                        check=True,
                    )

                subprocess.run(
                    [
                        "pdftocairo",
                        "-png",
                        "-singlefile",
                        "-r",
                        "150",
                        os.path.join(tmpdir, "out.pdf"),
                        os.path.join(tmpdir, "out"),
                    ],
                    cwd=tmpdir,
                    stdout=PIPE,
                    stderr=PIPE,
                    check=True,
                )
            except FileNotFoundError as e:
                logger.error("LaTeX tool missing: %s", e)
                raise RuntimeError(f"Rendering tool not found: {e}") from e
            except CalledProcessError as e:
                logger.error(
                    "LaTeX subprocess failed: %s; stdout: %s; stderr: %s",
                    e,
                    e.stdout,
                    e.stderr,
                )
                raise RuntimeError("Failed to render LaTeX") from e

            buf = io.BytesIO()
            img_path = os.path.join(tmpdir, "out.png")
            if not os.path.exists(img_path):
                logger.error("Expected image not found: %s", img_path)
                raise RuntimeError("Rendered image not found")
            with open(img_path, "rb") as img_file:
                buf.write(img_file.read())
            buf.seek(0)
            return buf

    def _check_answer(
        self, user_ans: str, correct_expr: Any
    ) -> tuple[bool, Optional[str]]:
        ans = self._clean_answer_latex(user_ans).strip().replace("$", "")
        try:
            ue = parse_latex(ans)
            if ue.free_symbols:
                return False, "invalid"
            diff = abs(float(N(ue, 15)) - float(N(correct_expr, 15)))
        except Exception:
            try:
                val = eval(ans, {"__builtins__": None}, {})
                if not isinstance(val, (int, float)):
                    return False, "invalid"
                diff = abs(val - float(N(correct_expr, 15)))
            except Exception:
                return False, "invalid"
        return (True, None) if diff < 1e-6 else (False, "wrong")

    async def _send_image_embed(
        self,
        ctx: commands.Context,
        text: str,
        title: str,
        color: discord.Color,
        footer: Optional[str] = None,
    ) -> None:
        try:
            buf = self._render_text_image(text)
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

    @commands.group(name="math", invoke_without_command=True)
    async def math(self, ctx: commands.Context) -> None:
        commands_list = (
            f"`{ctx.clean_prefix}math problem [subject=<subject>] [level=<n>]` → new problem",
            f"`{ctx.clean_prefix}math submit <answer>` → submit answer",
            f"`{ctx.clean_prefix}math giveup` → show solution",
            f"`{ctx.clean_prefix}math current` → view current",
            f"`{ctx.clean_prefix}math leaderboard [rate]` → show leaderboard",
        )
        await ctx.send("__**Math commands**__\n" + "\n".join(commands_list))

    @math.command(name="problem")
    async def math_problem(
        self, ctx: commands.Context, *, args: Optional[str] = None
    ) -> None:
        try:
            subject = None
            level = None
            if args:
                m = re.search(r"subject=([^\s]+)", args)
                if m:
                    subject = m.group(1)
                m2 = re.search(r"level=(\d+)", args)
                if m2:
                    level = int(m2.group(1))

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
    async def math_submit(self, ctx: commands.Context, *, user_ans: str) -> None:
        try:
            uid = ctx.author.id
            if uid not in self.active:
                await ctx.send("No active problem. Use `math problem` to start.")
                return

            pid = self.active[uid]
            row = self.conn.execute(
                "SELECT solution, answer_tex FROM problems WHERE id = ?", (pid,)
            ).fetchone()
            correct_expr = parse_latex(row["answer_tex"])
            correct, err = self._check_answer(user_ans, correct_expr)

            if not correct:
                msg = (
                    "Invalid format."
                    if err == "invalid"
                    else "❌ Incorrect. Try again or use `math giveup`."
                )
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
    async def math_giveup(self, ctx: commands.Context) -> None:
        try:
            uid = ctx.author.id
            if uid not in self.active:
                await ctx.send("No active problem. Use `math problem` to start.")
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
    async def math_current(self, ctx: commands.Context) -> None:
        try:
            uid = ctx.author.id
            if uid not in self.active:
                await ctx.send("No active problem. Use `math problem` to start.")
                return

            row = self.conn.execute(
                "SELECT problem FROM problems WHERE id = ?", (self.active[uid],)
            ).fetchone()

            await self._send_image_embed(
                ctx,
                row["problem"],
                "🔎 Current",
                discord.Color.dark_blue(),
                f"Submit with `{ctx.clean_prefix}math submit <answer>` or `math giveup`",
            )
        except Exception as e:
            logger.exception("Error in current command: %s", e)
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
                    f"{i+1}. {name} — {r['solved']}/{r['attempted']} ({r['rate']})"
                )

            await ctx.send(f"**{title}**\n" + "\n".join(lines))
        except Exception as e:
            logger.exception("Error in leaderboard command: %s", e)
            await ctx.send("An unexpected error occurred. Please try again later.")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(MathCog(bot))
