import asyncio
import csv
import logging
import os
from datetime import datetime, time
from zoneinfo import ZoneInfo
from typing import Dict, List

import aiohttp
import discord
from discord.ext import commands, tasks

from .math import MathCog

logger = logging.getLogger(__name__)


class PotdCog(commands.Cog):
    """AMC Problem of the Day"""

    SHEET_URL = os.getenv(
        "SHEET_URL",
        "https://docs.google.com/spreadsheets/d/1jKxvqeLvx2UEHGbZkylZe-SCEogfisfjXCzZUSOoSVc/export?format=csv",
    )

    GUILD_ID = int(os.getenv("GUILD_ID", "0"))
    CHANNEL_ID = int(os.getenv("CHANNEL_ID", "0"))

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        if not self.GUILD_ID or not self.CHANNEL_ID:
            logger.warning("GUILD_ID or CHANNEL_ID not set. POTD will be disabled.")
        self.current_date: str | None = None
        self.current_problem: str | None = None
        self.current_answer: str | None = None
        self.current_diff: str | None = None
        self.current_source: str | None = None
        self.attempts: Dict[int, int] = {}
        self.solved: Dict[int, int] = {}
        self.solve_order: List[int] = []
        self.daily_post.start()

    def cog_unload(self) -> None:
        self.daily_post.cancel()

    async def fetch_sheet(self) -> List[Dict[str, str]]:
        async with aiohttp.ClientSession() as session:
            async with session.get(self.SHEET_URL) as resp:
                text = await resp.text()
        rows = list(csv.reader(text.splitlines()))
        header = [h.strip() for h in rows[0]]
        data = []
        for row in rows[1:]:
            if len(row) < len(header):
                continue
            data.append({h: row[i].strip() for i, h in enumerate(header)})
        return data

    @staticmethod
    def _parse_date(s: str) -> datetime | None:
        for fmt in ("%m/%d/%Y", "%m/%d/%y"):
            try:
                return datetime.strptime(s, fmt)
            except ValueError:
                continue
        return None

    async def get_problem_for_date(self, d: datetime) -> Dict[str, str] | None:
        data = await self.fetch_sheet()
        for row in data:
            ds = row.get("Date") or row.get("date")
            if not ds:
                continue
            rd = self._parse_date(ds)
            if not rd:
                continue
            if rd.date() == d.date():
                return row
        return None

    async def send_image_embed(
        self,
        channel: discord.abc.Messageable,
        text: str,
        title: str,
        footer: str | None = None,
        color: discord.Color = discord.Color.blurple(),
    ) -> None:
        buf = MathCog._render_text_image(text)
        file = discord.File(buf, filename="image.png")
        embed = discord.Embed(title=title, color=color)
        embed.set_image(url="attachment://image.png")
        if footer:
            embed.set_footer(text=footer)
        await channel.send(file=file, embed=embed)

    async def post_rankings(self) -> None:
        if not self.current_date:
            return
        guild = self.bot.get_guild(self.GUILD_ID)
        if not guild:
            return
        channel = guild.get_channel(self.CHANNEL_ID)
        if not channel or not isinstance(channel, discord.abc.Messageable):
            return

        total_attempts = sum(self.attempts.values())
        total_correct = len(self.solved)
        embed = discord.Embed(
            title=f"Results for {self.current_date}",
            color=discord.Color.orange(),
        )

        if self.solve_order:
            first_user = guild.get_member(self.solve_order[0]) or await self.bot.fetch_user(
                self.solve_order[0]
            )
            embed.add_field(name="First solver", value=first_user.display_name, inline=False)
        else:
            embed.add_field(name="First solver", value="N/A", inline=False)
        embed.add_field(
            name="Total correct / attempts",
            value=f"{total_correct} / {total_attempts}",
            inline=False,
        )
        attempts_map: Dict[int, List[str]] = {}
        for uid, tries in self.solved.items():
            user = guild.get_member(uid) or await self.bot.fetch_user(uid)
            attempts_map.setdefault(tries, []).append(user.display_name)
        for t in sorted(attempts_map):
            names = ", ".join(attempts_map[t])
            label = "try" if t == 1 else "tries"
            embed.add_field(name=f"{t} {label}", value=names, inline=False)
        if not self.attempts:
            embed.add_field(name="Info", value="No attempts recorded.", inline=False)

        if self.current_answer and self.current_source:
            footer = f"Answer: {self.current_answer} | Source: {self.current_source}"
            embed.set_footer(text=footer)

        await channel.send(embed=embed)

    @tasks.loop(time=time(5, tzinfo=ZoneInfo("America/Chicago")))
    async def daily_post(self) -> None:
        guild = self.bot.get_guild(self.GUILD_ID)
        if not guild:
            return
        channel = guild.get_channel(self.CHANNEL_ID)
        if not channel or not isinstance(channel, discord.abc.Messageable):
            return
        # show yesterday rankings before posting today's problem
        if self.current_date:
            await self.post_rankings()
        today = datetime.now(ZoneInfo("America/Chicago"))
        row = await self.get_problem_for_date(today)
        if not row:
            logger.warning("POTD for %s not found", today.date())
            await channel.send(
                f"No POTD found for {today.strftime('%m/%d/%Y')}. Please check the sheet."
            )
            return
        self.current_date = today.strftime("%m/%d/%Y")
        self.current_problem = row.get("Problem") or row.get("problem") or ""
        self.current_answer = (row.get("Answer") or row.get("answer") or "").strip().upper()
        self.current_diff = row.get("Difficulty") or row.get("difficulty") or ""
        self.current_source = row.get("Source") or row.get("source") or ""
        self.attempts.clear()
        self.solved.clear()
        self.solve_order.clear()
        footer = f"Difficulty: {self.current_diff} | Submit in DMs with `!potd submit <choice>`"
        await self.send_image_embed(
            channel,
            self.current_problem,
            title=f"AMC Problem of the Day — {self.current_date}",
            footer=footer,
        )

    @daily_post.before_loop
    async def before_daily_post(self) -> None:
        await self.bot.wait_until_ready()

    @commands.group(name="potd", invoke_without_command=True)
    async def potd(self, ctx: commands.Context) -> None:
        if self.current_problem:
            await ctx.send(
                f"Current POTD posted in <#{self.CHANNEL_ID}>. Submit answer in DMs with `potd submit <choice>`."
            )
        else:
            await ctx.send("No POTD available.")

    @potd.command(name="post")
    @commands.is_owner()
    async def potd_post(self, ctx: commands.Context) -> None:
        await self.daily_post()
        await ctx.send("Posted POTD.")

    @potd.command(name="submit")
    async def potd_submit(self, ctx: commands.Context, *, answer: str) -> None:
        if not self.current_problem or not self.current_answer:
            await ctx.send("No active POTD.")
            return
        if ctx.guild is not None:
            try:
                await ctx.message.delete()
            except discord.HTTPException:
                pass
            await ctx.author.send(
                "Please submit your POTD answer in DMs with the bot using `potd submit <choice>`."
            )
            return
        user_id = ctx.author.id
        ans = answer.strip().upper()
        if ans not in ["A", "B", "C", "D", "E"]:
            await ctx.send("Please submit one of A/B/C/D/E.")
            return
        if user_id in self.solved:
            await ctx.send("You have already solved today's problem.")
            return
        self.attempts[user_id] = self.attempts.get(user_id, 0) + 1
        if ans == self.current_answer.upper():
            tries = self.attempts[user_id]
            self.solved[user_id] = tries
            self.solve_order.append(user_id)
            rank = len(self.solve_order)
            ordinal = self._ordinal(rank)
            await ctx.send(
                f"✅ Correct! You are the {ordinal} solver with {tries} {'try' if tries==1 else 'tries'}.\n"
                f"Answer: {self.current_answer} | Source: {self.current_source}"
            )
        else:
            await ctx.send("❌ Incorrect. Try again.")

    @staticmethod
    def _ordinal(n: int) -> str:
        if 10 <= n % 100 <= 20:
            suffix = "th"
        else:
            suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
        return f"{n}{suffix}"


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(PotdCog(bot))
