import socket
from collections.abc import Callable
from typing import NoReturn

import pytest

_NETWORK_DISABLED_MESSAGE = "Real network access is disabled in automated tests"


@pytest.fixture(autouse=True)
def _disable_real_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def blocked_network_call(*args: object, **kwargs: object) -> NoReturn:
        raise RuntimeError(_NETWORK_DISABLED_MESSAGE)

    socket_methods: tuple[tuple[object, str, Callable[..., object]], ...] = (
        (socket, "create_connection", blocked_network_call),
        (socket.socket, "connect", blocked_network_call),
        (socket.socket, "connect_ex", blocked_network_call),
    )
    for target, name, replacement in socket_methods:
        monkeypatch.setattr(target, name, replacement)
