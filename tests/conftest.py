from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class FakeUser:
    id: int = 123
    name: str = "TestUser"
    display_name: str = "TestUser"


@dataclass
class FakeContext:
    author: FakeUser = field(default_factory=FakeUser)
    clean_prefix: str = "!"
    guild: Any = None
    sent: list[tuple[tuple[Any, ...], dict[str, Any]]] = field(default_factory=list)

    async def send(self, *args: Any, **kwargs: Any) -> None:
        self.sent.append((args, kwargs))

    @property
    def last_message(self) -> str:
        if not self.sent:
            return ""
        args, _kwargs = self.sent[-1]
        return str(args[0]) if args else ""


class FakeBot:
    async def fetch_user(self, user_id: int) -> FakeUser:
        return FakeUser(
            id=user_id, name=f"user-{user_id}", display_name=f"user-{user_id}"
        )
