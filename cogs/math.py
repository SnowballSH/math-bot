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
from datasets import load_dataset
from sympy import N
from sympy.parsing.latex import parse_latex


class MathCog(commands.Cog):
    """Cog for practicing math problems from the MATH-500 dataset."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.bank: List[Dict[str, Any]] = self._load_bank()
        self.active: Dict[int, int] = {}

    def _load_bank(self) -> List[Dict[str, Any]]:
        """Load or preprocess problems from ./math500 jsonl files, using a cache if available."""
        data_dir = os.path.join(os.path.dirname(__file__), "math500")
        cache_path = os.path.join(data_dir, "math500_bank.json")

        # Use cached bank if it exists
        if os.path.exists(cache_path):
            with open(cache_path, "r") as cf:
                raw: List[Dict[str, Any]] = json.load(cf)
        else:
            raw = []
            for fname in ("train.jsonl", "test.jsonl"):
                path = os.path.join(data_dir, fname)
                if not os.path.exists(path):
                    continue
                with open(path, "r") as f:
                    for line in f:
                        try:
                            ex = json.loads(line)
                            ans = self._clean_answer_latex(ex.get("answer", ""))
                            expr = parse_latex(ans)
                            if expr.free_symbols:
                                continue
                            raw.append({
                                "problem": ex.get("problem", ""),
                                "solution": ex.get("solution", ""),
                                "answer_tex": ans,
                            })
                        except Exception:
                            continue
            # Cache the processed bank
            if raw:
                os.makedirs(data_dir, exist_ok=True)
                with open(cache_path, "w") as cf:
                    json.dump(raw, cf)

        # Build final bank with parsed expressions
        bank: List[Dict[str, Any]] = []
        for entry in raw:
            try:
                expr = parse_latex(entry["answer_tex"])
                if expr.free_symbols:
                    continue
                bank.append({**entry, "expr": expr})
            except Exception:
                continue
        if not bank:
            raise RuntimeError("No valid numeric examples found in local dataset.")
        return bank

    @staticmethod
    def _clean_answer_latex(ans: str) -> str:
        """Remove box commands and extra delimiters from LaTeX answer."""
        cleaned = re.sub(r"\\boxed\s*\{([^}]*)\}", r"\1", ans)
        return cleaned.replace("$$", "$")

    def _render_text_image(self, text: str) -> io.BytesIO:
        """Render LaTeX text to a PNG and return as BytesIO."""
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
            tex_path = os.path.join(tmpdir, "out.tex")
            with open(tex_path, "w") as f:
                f.write(doc)
            subprocess.run(
                ["pdflatex", "-interaction=nonstopmode", "-halt-on-error", tex_path],
                cwd=tmpdir,
                stdout=PIPE,
                stderr=PIPE,
                check=True,
            )
            pdf_path = os.path.join(tmpdir, "out.pdf")
            subprocess.run(
                ["pdftocairo", "-png", "-singlefile", "-r", "150", pdf_path, os.path.join(tmpdir, "out")],
                cwd=tmpdir,
                stdout=PIPE,
                stderr=PIPE,
                check=True,
            )
            png_path = os.path.join(tmpdir, "out.png")
            buf = io.BytesIO()
            with open(png_path, "rb") as img:
                buf.write(img.read())
            buf.seek(0)
            return buf

    def _check_answer(self, user_ans: str, correct_expr: Any) -> Tuple[bool, Optional[str]]:
        """Check user's answer against the correct expression."""
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
        """Render text and send it as an embedded image."""
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
        """Show available math commands."""
        p = ctx.clean_prefix
        await ctx.send(
            "__**Math commands**__\n"
            f"`{p}math problem` → new problem\n"
            f"`{p}math submit <answer>` → submit answer\n"
            f"`{p}math giveup` → show solution\n"
            f"`{p}math current` → view current"
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
            msg = "Invalid format." if err == "invalid" else "❌ Incorrect. Try again or use `math giveup`."
            await ctx.send(msg)
            return
        del self.active[uid]
        await self._send_image_embed(ctx, entry["solution"], "✅ Correct! Solution", discord.Color.green())

    @math.command(name="giveup")
    async def math_giveup(self, ctx: commands.Context) -> None:
        """Reveal the solution to the current problem."""
        uid = ctx.author.id
        if uid not in self.active:
            await ctx.send("No active problem. Use `math problem` to start.")
            return
        idx = self.active[uid]
        entry = self.bank[idx]
        del self.active[uid]
        await self._send_image_embed(ctx, entry["solution"], "ℹ️ Solution", discord.Color.orange())

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


async def setup(bot: commands.Bot) -> None:
    """Register the MathCog."""
    await bot.add_cog(MathCog(bot))
