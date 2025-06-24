import os
import discord
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()  # loads .env
TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN not set in environment")

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)


async def load_extensions():
    try:
        await bot.load_extension("jishaku")
        print("Loaded Jishaku")
    except Exception as e:
        print(f"Could not load Jishaku: {e}")
    try:
        await bot.load_extension("cogs.prac")
        print("Loaded prac cog")
    except Exception as e:
        print(f"Could not load prac cog: {e}")
    try:
        await bot.load_extension("cogs.math")
        print("Loaded math cog")
    except Exception as e:
        print(f"Could not load math cog: {e}")
    try:
        await bot.load_extension("cogs.potd")
        print("Loaded potd cog")
    except Exception as e:
        print(f"Could not load potd cog: {e}")


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
    bot.run(TOKEN)
