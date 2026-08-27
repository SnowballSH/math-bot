# Math Bot

![fireballsh](https://github.com/user-attachments/assets/b48650c4-253d-4475-a478-fad462a78d83)

A Discord bot for math practice problems, rendered LaTeX/Asymptote prompts, and a persistent SQLite leaderboard.

## Setup

Install Python dependencies with `uv`:

```sh
uv sync
```

Install the system rendering tools used by the `math` cog:

- `pdftex` / `pdflatex`
- `pdftocairo`
- `asymptote`

Copy `.env.example` to `.env` and set `DISCORD_TOKEN`.

The `jishaku` debug extension (owner-only in-process eval) is disabled by default; set `MATHBOT_ENABLE_JISHAKU=1` to load it in a trusted environment.

The ignored `cogs/math500/train.jsonl` and `cogs/math500/test.jsonl` files should come from the `math_splits` data in the [prm800k repository](https://github.com/openai/prm800k/tree/main/prm800k/math_splits).
On first startup, the `math` cog creates the ignored `cogs/math500/math500.db` SQLite database from those JSONL files.

## Run

```sh
uv run python main.py
```

## Test

```sh
uv run ruff check .
uv run ruff format --check .
uv run basedpyright
uv run pytest --cov
```
