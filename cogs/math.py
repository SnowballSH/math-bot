import io
import json
import os
import random
import re
import subprocess
import tempfile
from subprocess import PIPE
from typing import Any, Dict, List, Tuple, Optional

import discord
from discord.ext import commands
from sympy import N
from sympy.parsing.latex import parse_latex


class MathCog(commands.Cog):
    """Cog for practicing math problems with a persistent leaderboard."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.data_dir = os.path.join(os.path.dirname(__file__), "math500")
        self.bank = self._load_bank()
        self.active: Dict[int, int] = {}
        self.lb_path = os.path.join(self.data_dir, "leaderboard.json")
        self.leaderboard = self._load_leaderboard()

    def _load_bank(self) -> List[Dict[str, Any]]:
        """Load or preprocess problems from local jsonl, caching only numeric answers."""
        cache = os.path.join(self.data_dir, "math500_bank.json")
        if os.path.exists(cache):
            with open(cache) as cf:
                raw = json.load(cf)
        else:
            raw = []
            for fname in ("train.jsonl", "test.jsonl"):
                path = os.path.join(self.data_dir, fname)
                if not os.path.exists(path):
                    continue
                with open(path) as f:
                    for line in f:
                        try:
                            ex = json.loads(line)
                            ans = self._clean_answer_latex(ex.get("answer", ""))
                            expr = parse_latex(ans)
                            if expr.free_symbols:
                                continue
                            raw.append(
                                {
                                    "problem": ex.get("problem", ""),
                                    "solution": ex.get("solution", ""),
                                    "answer_tex": ans,
                                }
                            )
                        except Exception:
                            continue
            os.makedirs(self.data_dir, exist_ok=True)
            with open(cache, "w") as cf:
                json.dump(raw, cf)
        bank: List[Dict[str, Any]] = []
        for e in raw:
            try:
                expr = parse_latex(e["answer_tex"])
                bank.append({**e, "expr": expr})
            except Exception:
                continue
        if not bank:
            raise RuntimeError("No valid examples in local dataset.")
        return bank

    def _load_leaderboard(self) -> Dict[str, Dict[str, int]]:
        """Load leaderboard from JSON or initialize empty."""
        if os.path.exists(self.lb_path):
            try:
                with open(self.lb_path) as lf:
                    return json.load(lf)
            except Exception:
                return {}
        return {}

    def _save_leaderboard(self) -> None:
        """Persist leaderboard to JSON file."""
        os.makedirs(self.data_dir, exist_ok=True)
        with open(self.lb_path, "w") as lf:
            json.dump(self.leaderboard, lf)

    def _update_leaderboard(
        self, user_id: int, solved_inc: int, attempted_inc: int
    ) -> None:
        """Update a user's solved and attempted counts and save."""
        key = str(user_id)
        entry = self.leaderboard.get(key, {"solved": 0, "attempted": 0})
        entry["solved"] = entry.get("solved", 0) + solved_inc
        entry["attempted"] = entry.get("attempted", 0) + attempted_inc
        self.leaderboard[key] = entry
        self._save_leaderboard()

    @staticmethod
    def _clean_answer_latex(ans: str) -> str:
        """Strip \boxed and $$ delimiters."""
        cleaned = re.sub(r"\\boxed\s*\{([^}]*)\}", r"\1", ans)
        return cleaned.replace("$$", "$")

    def _render_text_image(self, text: str) -> io.BytesIO:
        """Render LaTeX into a PNG BytesIO."""
        doc = (
            "\\documentclass{article}\n"
            "\\usepackage[margin=10pt]{geometry}\n"
            "\\usepackage[active,tightpage]{preview}\n"
            "\\PreviewEnvironment{preview}\n"
            "\\setlength\\PreviewBorder{10pt}\n"
            "\\usepackage{xcolor,amsmath,amssymb}\n"
            "\\begin{document}\n"
            "\\begin{preview}\n"
            f"{text}\n"
            "\\end{preview}\n"
            "\\end{document}\n"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            tex = os.path.join(tmpdir, "out.tex")
            with open(tex, "w") as f:
                f.write(doc)
            subprocess.run(
                ["pdflatex", "-interaction=nonstopmode", "-halt-on-error", tex],
                cwd=tmpdir,
                stdout=PIPE,
                stderr=PIPE,
                check=True,
            )
            pdf = os.path.join(tmpdir, "out.pdf")
            subprocess.run(
                [
                    "pdftocairo",
                    "-png",
                    "-singlefile",
                    "-r",
                    "150",
                    pdf,
                    os.path.join(tmpdir, "out"),
                ],
                cwd=tmpdir,
                stdout=PIPE,
                stderr=PIPE,
                check=True,
            )
            buf = io.BytesIO()
            with open(os.path.join(tmpdir, "out.png"), "rb") as img:
                buf.write(img.read())
            buf.seek(0)
            return buf

    def _check_answer(
        self, user_ans: str, correct_expr: Any
    ) -> Tuple[bool, Optional[str]]:
        """Validate user's answer against the correct expression."""
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
        """Send LaTeX-rendered image in an embed."""
        try:
            buf = self._render_text_image(text)
            file = discord.File(buf, filename="image.png")
            embed = discord.Embed(title=title, color=color)
            embed.set_image(url="attachment://image.png")
            if footer:
                embed.set_footer(text=footer)
            await ctx.send(embed=embed, file=file)
        except RuntimeError as e:
            await ctx.send(f"{title}:\n{text}\nError: {e}")

    @commands.group(name="math", invoke_without_command=True)
    async def math(self, ctx: commands.Context) -> None:
        """Show math command list."""
        p = ctx.clean_prefix
        await ctx.send(
            "__**Math commands**__\n"
            f"`{p}math problem` → new problem\n"
            f"`{p}math submit <answer>` → submit answer\n"
            f"`{p}math giveup` → show solution\n"
            f"`{p}math current` → view current\n"
            f"`{p}math leaderboard [rate]` → show leaderboard"
        )

    @math.command(name="problem")
    async def math_problem(self, ctx: commands.Context) -> None:
        """Send a new math problem."""
        uid = ctx.author.id
        if uid in self.active:
            await ctx.send("You already have an active problem.")
            return
        idx = random.randrange(len(self.bank))
        self.active[uid] = idx
        await self._send_image_embed(
            ctx,
            self.bank[idx]["problem"],
            "📝 Problem",
            discord.Color.dark_blue(),
            f"Submit with {ctx.clean_prefix}math submit <answer>",
        )

    @math.command(name="submit", aliases=["answer"])
    async def math_submit(self, ctx: commands.Context, *, user_ans: str) -> None:
        """Submit an answer to the current problem."""
        uid = ctx.author.id
        if uid not in self.active:
            await ctx.send("No active problem. Use `math problem` to start.")
            return
        entry = self.bank[self.active[uid]]
        correct, err = self._check_answer(user_ans, entry["expr"])
        if not correct:
            msg = (
                "Invalid format."
                if err == "invalid"
                else "❌ Incorrect. Try again or use `math giveup`."
            )
            await ctx.send(msg)
            return
        self._update_leaderboard(uid, solved_inc=1, attempted_inc=1)
        del self.active[uid]
        await self._send_image_embed(
            ctx, entry["solution"], "✅ Correct! Solution", discord.Color.green()
        )

    @math.command(name="giveup")
    async def math_giveup(self, ctx: commands.Context) -> None:
        """Reveal the solution to the current problem."""
        uid = ctx.author.id
        if uid not in self.active:
            await ctx.send("No active problem. Use `math problem` to start.")
            return
        idx = self.active[uid]
        entry = self.bank[idx]
        self._update_leaderboard(uid, solved_inc=0, attempted_inc=1)
        del self.active[uid]
        await self._send_image_embed(
            ctx, entry["solution"], "ℹ️ Solution", discord.Color.orange()
        )

    @math.command(name="current")
    async def math_current(self, ctx: commands.Context) -> None:
        """Show the current problem."""
        uid = ctx.author.id
        if uid not in self.active:
            await ctx.send("No active problem. Use `math problem` to start.")
            return
        idx = self.active[uid]
        await self._send_image_embed(
            ctx,
            self.bank[idx]["problem"],
            "🔎 Current",
            discord.Color.dark_blue(),
            f"Submit with {ctx.clean_prefix}math submit <answer> or `math giveup`",
        )

    @math.command(name="leaderboard")
    async def math_leaderboard(
        self, ctx: commands.Context, sort_by: Optional[str] = "solved"
    ) -> None:
        """Display the leaderboard, optionally sorted by solve rate, without pings."""
        if not self.leaderboard:
            await ctx.send("Leaderboard is empty.")
            return
        if sort_by is None:
            sort_by = "solved"
        entries = []
        for uid_str, data in self.leaderboard.items():
            uid = int(uid_str)
            entries.append((uid, data.get("solved", 0), data.get("attempted", 0)))
        if sort_by.lower() in ("rate", "solve_rate"):
            entries.sort(key=lambda x: x[1] / x[2] if x[2] > 0 else 0, reverse=True)
            title = "📊 Leaderboard by solve rate"
        else:
            entries.sort(key=lambda x: x[1], reverse=True)
            title = "📊 Leaderboard by solved count"
        lines = []
        guild = ctx.guild
        for idx, (uid, solved, attempted) in enumerate(entries, start=1):
            user_label = str(uid)
            if guild:
                member = guild.get_member(uid)
                if member is None:
                    try:
                        member = await guild.fetch_member(uid)
                    except Exception:
                        member = None
                if member:
                    user_label = member.display_name
            else:
                user_obj = self.bot.get_user(uid)
                if user_obj:
                    user_label = user_obj.name
            rate = f"{(solved/attempted*100):.1f}%" if attempted > 0 else "N/A"
            lines.append(f"{idx}. {user_label} — {solved}/{attempted} ({rate})")
        await ctx.send(f"**{title}**\n" + "\n".join(lines))


async def setup(bot: commands.Bot) -> None:
    """Register the MathCog."""
    await bot.add_cog(MathCog(bot))
