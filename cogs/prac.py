# cogs/prac.py
import random
import math

import discord
from discord.ext import commands


class PracticeCog(commands.Cog):
    """A cog providing practice problems."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Map user ID to current problem info
        # Each value is a dict with keys: "type", params..., "answer"
        self.problems: dict[int, dict] = {}

    @commands.group(
        name="prac",
        aliases=["practice", "p"],
        invoke_without_command=True,
        help="Practice problems.",
    )
    async def prac(self, ctx: commands.Context):
        # If invoked without subcommand, show help/usage.
        prefix = ctx.clean_prefix
        lines = [
            "**Practice commands:**",
            f"`{prefix}prac square` → start a squaring problem",
            f"`{prefix}prac modinv` → start a modular inverse problem",
            f"`{prefix}prac submit <your_answer>` → submit answer",
            f"`{prefix}prac giveup` → give up current problem (shows answer)",
            f"`{prefix}prac current` → view your current problem (without answer)",
        ]
        await ctx.send("\n".join(lines))

    def _has_active(self, user_id: int) -> bool:
        return user_id in self.problems

    @prac.command(name="square", help="Generate a squaring problem.")
    async def prac_square(self, ctx: commands.Context):
        user_id = ctx.author.id
        prefix = ctx.clean_prefix
        if self._has_active(user_id):
            await ctx.send(
                "You already have an active problem. "
                f"Finish it with `{prefix}prac submit <answer>` or give up with `{prefix}prac giveup`."
            )
            return

        n = random.randint(10, 120)
        answer = n * n
        # Store problem
        self.problems[user_id] = {"type": "square", "n": n, "answer": answer}
        await ctx.send(
            f"**Square problem:** What is **{n}** squared? "
            f"Submit with `{prefix}prac submit <answer>`."
        )

    @prac.command(name="modinv", help="Generate a modular inverse problem.")
    async def prac_modinv(self, ctx: commands.Context):
        user_id = ctx.author.id
        prefix = ctx.clean_prefix
        if self._has_active(user_id):
            await ctx.send(
                "You already have an active problem. "
                f"Finish it with `{prefix}prac submit <answer>` or give up with `{prefix}prac giveup`."
            )
            return

        while True:
            m = random.randint(3, 50)
            a = random.randint(2, m - 1)
            if math.gcd(a, m) == 1:
                try:
                    inv = pow(a, -1, m)
                except ValueError:
                    continue
                break

        self.problems[user_id] = {"type": "modinv", "a": a, "m": m, "answer": inv}
        await ctx.send(
            f"**Modular inverse problem:** Find the inverse of **{a}** modulo **{m}**. "
            f"Submit with `{prefix}prac submit <answer>`."
        )

    @prac.command(
        name="submit",
        help="Submit your answer to the current problem.",
        aliases=["answer"],
    )
    async def prac_submit(self, ctx: commands.Context, user_answer: str):
        user_id = ctx.author.id
        prefix = ctx.clean_prefix
        if not self._has_active(user_id):
            await ctx.send(
                f"You don't have an active problem. Start one with `{prefix}prac square` or `{prefix}prac modinv`."
            )
            return

        problem = self.problems[user_id]
        correct = False
        # Attempt to parse integer answer
        try:
            ans_int = int(user_answer.strip())
        except ValueError:
            await ctx.send(
                f"Please submit an integer answer, e.g. `{prefix}prac submit 42`."
            )
            return

        if ans_int == problem["answer"]:
            correct = True

        if correct:
            # Clear the problem
            del self.problems[user_id]
            await ctx.send(
                f"✅ Correct! Well done. You can start a new problem with `{prefix}prac square` or `{prefix}prac modinv`."
            )
        else:
            await ctx.send(
                f"❌ That's not correct. Try again, or give up with `{prefix}prac giveup`."
            )

    @prac.command(
        name="giveup", help="Give up on the current problem; shows the answer."
    )
    async def prac_giveup(self, ctx: commands.Context):
        user_id = ctx.author.id
        prefix = ctx.clean_prefix
        if not self._has_active(user_id):
            await ctx.send(
                f"You don't have an active problem to give up. Start one with one of the `{prefix}prac` commands."
            )
            return

        problem = self.problems[user_id]
        if problem["type"] == "square":
            n = problem["n"]
            ans = problem["answer"]
            desc = f"What is {n} squared?"
        elif problem["type"] == "modinv":
            a = problem["a"]
            m = problem["m"]
            ans = problem["answer"]
            desc = f"Find the inverse of {a} modulo {m}."
        else:
            desc = "Unknown problem"
            ans = problem.get("answer", "<no answer stored>")

        # Clear
        del self.problems[user_id]
        await ctx.send(
            f"ℹ️ You gave up. The problem was: **{desc}**\nThe answer was: **{ans}**. "
            f"You can start a new one with `{prefix}prac square` or `{prefix}prac modinv`."
        )

    @prac.command(
        name="current", help="View your current problem (without revealing the answer)."
    )
    async def prac_current(self, ctx: commands.Context):
        user_id = ctx.author.id
        prefix = ctx.clean_prefix
        if not self._has_active(user_id):
            await ctx.send(
                f"You don't have an active problem. Start one with `{prefix}prac square` or `{prefix}prac modinv`."
            )
            return

        problem = self.problems[user_id]
        if problem["type"] == "square":
            n = problem["n"]
            desc = f"What is {n} squared?"
        elif problem["type"] == "modinv":
            a = problem["a"]
            m = problem["m"]
            desc = f"Find the inverse of {a} modulo {m}."
        else:
            desc = "Unknown problem type."

        await ctx.send(
            f"🔎 Your current problem: **{desc}**\n"
            f"Submit answer with `{prefix}prac submit <answer>` or give up with `{prefix}prac giveup`."
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(PracticeCog(bot))
