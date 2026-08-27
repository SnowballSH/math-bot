import os

import discord
from discord.ext import commands
from dotenv import load_dotenv

BASE_EXTENSIONS = ("cogs.prac", "cogs.math")


def jishaku_enabled() -> bool:
    value = os.getenv("MATHBOT_ENABLE_JISHAKU", "")
    return value.strip().lower() in {"1", "true", "yes", "on"}


def enabled_extensions() -> tuple[str, ...]:
    if jishaku_enabled():
        return ("jishaku", *BASE_EXTENSIONS)
    return BASE_EXTENSIONS


intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)


async def load_extensions():
    for extension in enabled_extensions():
        try:
            await bot.load_extension(extension)
            print(f"Loaded {extension}")
        except Exception as e:
            print(f"Could not load {extension}: {e}")


@bot.event
async def setup_hook():
    await load_extensions()


@bot.event
async def on_ready():
    if not bot.user:
        raise RuntimeError("Bot user is not set. Check your token.")
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")
    print("------")


if __name__ == "__main__":
    load_dotenv()
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise RuntimeError("DISCORD_TOKEN is not set in the environment")

    bot.run(token)
