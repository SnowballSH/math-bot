from __future__ import annotations

import pytest

import main as bot_main


def test_jishaku_disabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MATHBOT_ENABLE_JISHAKU", raising=False)
    assert bot_main.enabled_extensions() == bot_main.BASE_EXTENSIONS
    assert "jishaku" not in bot_main.enabled_extensions()


@pytest.mark.parametrize("value", ["0", "false", "no", "off", "", "nonsense"])
def test_jishaku_stays_off_for_non_truthy_values(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("MATHBOT_ENABLE_JISHAKU", value)
    assert "jishaku" not in bot_main.enabled_extensions()


@pytest.mark.parametrize("value", ["1", "true", "YES", " on "])
def test_jishaku_enabled_via_env(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("MATHBOT_ENABLE_JISHAKU", value)
    extensions = bot_main.enabled_extensions()
    assert extensions[0] == "jishaku"
    assert extensions[1:] == bot_main.BASE_EXTENSIONS
