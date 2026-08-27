from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sys
from typing import Any, Optional

from sympy import N
from sympy.parsing.latex import parse_latex

from cogs.safe_expr import MAX_INPUT_LENGTH, parse_user_expression

logger = logging.getLogger(__name__)

CHECK_TIMEOUT_SECONDS = 15.0
MAX_WORKER_IO_BYTES = 65536
_TOLERANCE = 1e-6
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def parse_latex_required(text: str) -> Any:
    expr = parse_latex(text)
    if expr is None:
        raise ValueError("LaTeX parser returned no expression")
    return expr


def clean_answer_latex(ans: str) -> str:
    cleaned = re.sub(r"\\boxed\s*\{([^}]*)\}", r"\1", ans)
    return cleaned.replace("$$", "$")


def _numeric_difference(user_expr: Any, correct_expr: Any) -> Optional[float]:
    if user_expr.free_symbols:
        return None
    return abs(float(N(user_expr, 15)) - float(N(correct_expr, 15)))


def check_answer(user_ans: str, correct_expr: Any) -> tuple[bool, Optional[str]]:
    if len(user_ans) > MAX_INPUT_LENGTH:
        return False, "invalid"
    ans = clean_answer_latex(user_ans).strip().replace("$", "")
    try:
        diff = _numeric_difference(parse_latex_required(ans), correct_expr)
    except Exception:
        try:
            diff = _numeric_difference(parse_user_expression(ans), correct_expr)
        except Exception:
            return False, "invalid"
    if diff is None:
        return False, "invalid"
    return (True, None) if diff < _TOLERANCE else (False, "wrong")


def check_answer_text(user_ans: str, answer_tex: str) -> tuple[bool, Optional[str]]:
    try:
        correct_expr = parse_latex_required(answer_tex)
    except Exception:
        return False, "invalid"
    return check_answer(user_ans, correct_expr)


async def check_answer_in_subprocess(
    user_ans: str, answer_tex: str, timeout: float = CHECK_TIMEOUT_SECONDS
) -> tuple[bool, Optional[str]]:
    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "cogs.answer_check",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=_REPO_ROOT,
    )
    payload = json.dumps({"user_ans": user_ans, "answer_tex": answer_tex}).encode()
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(payload), timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return False, "timeout"
    if proc.returncode != 0:
        logger.warning(
            "Answer worker exited with %s: %s",
            proc.returncode,
            stderr[:1024].decode(errors="replace"),
        )
        return False, "invalid"
    if len(stdout) > MAX_WORKER_IO_BYTES:
        return False, "invalid"
    try:
        result = json.loads(stdout)
        return bool(result["correct"]), result["error"]
    except (ValueError, KeyError):
        return False, "invalid"


def main() -> None:
    request = json.loads(sys.stdin.read(MAX_WORKER_IO_BYTES))
    correct, error = check_answer_text(request["user_ans"], request["answer_tex"])
    json.dump({"correct": correct, "error": error}, sys.stdout)


if __name__ == "__main__":
    main()
