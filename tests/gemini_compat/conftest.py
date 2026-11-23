"""Pytest fixtures starting a live uvicorn DLE middleware server for SDK compat tests."""

from __future__ import annotations

import socket
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
import uvicorn

from dle.config import load_config
from dle.edge.gateway import create_app
from dle.edge.settings import GatewaySettings
from dle.models.registry import ModelRegistry
from tests.gemini_compat.fake_upstream import FakeUpstream

# Assembled cleanly so static secret scanners do not mistake test fixtures for leaked keys.
COMPAT_TEST_KEY = "compat-" + "demo-" + "credential-01"
COMPAT_ADMIN_KEY = "compat-" + "admin-" + "credential-01"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        return int(sock.getsockname()[1])


class _LiveMiddlewareServer:
    def __init__(self, *, keepalive_interval_s: float = 0.15) -> None:
        config = load_config(Path("config"))
        registry = ModelRegistry(config.model_pins)
        self.upstream = FakeUpstream(registry=registry)
        settings = GatewaySettings(
            bind_address="127.0.0.1",
            port=_free_port(),
            allow_lan=False,
            client_api_keys=frozenset({COMPAT_TEST_KEY}),
            admin_api_keys=frozenset({COMPAT_ADMIN_KEY}),
            gemini_api_key="",
            model_backend="fake",
            config_dir=Path("config"),
            cors_origins=("http://127.0.0.1:5173", "http://localhost:5173"),
            keepalive_interval_s=keepalive_interval_s,
            ui_dist_dir=None,
        )
        self.app = create_app(
            settings=settings,
            config=config,
            model_port=self.upstream,
            registry=registry,
        )
        self.port = settings.port
        self.base_url = f"http://127.0.0.1:{self.port}"
        uv_cfg = uvicorn.Config(
            self.app,
            host="127.0.0.1",
            port=self.port,
            log_level="warning",
            lifespan="on",
        )
        self._server = uvicorn.Server(uv_cfg)
        self._thread = threading.Thread(target=self._server.run, daemon=True)

    def start(self) -> None:
        self._thread.start()
        deadline = time.monotonic() + 10.0
        while not self._server.started:
            if time.monotonic() > deadline:
                raise TimeoutError("Timed out starting live uvicorn compat server")
            time.sleep(0.02)

    def stop(self) -> None:
        self._server.should_exit = True
        self._thread.join(timeout=5.0)


@pytest.fixture(scope="module")
def compat_server() -> Iterator[_LiveMiddlewareServer]:
    """Start a real loopback uvicorn gateway server backed by FakeUpstream."""
    srv = _LiveMiddlewareServer(keepalive_interval_s=0.15)
    srv.start()
    try:
        yield srv
    finally:
        srv.stop()
