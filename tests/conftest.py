import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from ai.eval_fixture import ADA, BOB, SECRET_PROJECT, build_fixture_db  # noqa: E402


class FakeOllama:
    """A real HTTP server that mimics the parts of Ollama's API that CareerDNA uses."""

    def __init__(self):
        self.models = [{"name": "qwen2.5:3b", "size": 1_900_000_000, "digest": "abc123"}]
        self.loaded = []
        self.chat_handler = lambda payload: (200, {"model": payload["model"], "message": {"role": "assistant", "content": "ok"}, "eval_count": 5})
        self.delay = 0.0
        from tests.helpers import concept_vec
        self.embed_handler = lambda payload: (200, {"model": payload["model"], "embeddings": [concept_vec(t) for t in payload["input"]]})
        self.requests = []
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, body):
                raw = json.dumps(body).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self):
                outer.requests.append(("GET", self.path, None))
                if self.path == "/api/tags":
                    self._send(200, {"models": outer.models})
                elif self.path == "/api/ps":
                    self._send(200, {"models": outer.loaded})
                else:
                    self._send(404, {"error": "not found"})

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
                outer.requests.append(("POST", self.path, body))
                if outer.delay:
                    time.sleep(outer.delay)
                if self.path == "/api/chat":
                    code, resp = outer.chat_handler(body)
                    try:
                        self._send(code, resp)
                    except (BrokenPipeError, ConnectionResetError):
                        pass
                elif self.path == "/api/embed":
                    code, resp = outer.embed_handler(body)
                    self._send(code, resp)
                else:
                    self._send(404, {"error": "not found"})

        self.server = HTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def stop(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture(autouse=True)
def _isolate_retrieval_env(monkeypatch, tmp_path):
    """Every test starts from the documented defaults (bm25 + legacy wiring) and never reads the repo's tuning file."""
    for k in ("CAREERDNA_RETRIEVAL_MODE", "CAREERDNA_RETRIEVAL_WIRING", "CAREERDNA_EMBED_MODEL", "CAREERDNA_SEM_MIN_SIM",
              "CAREERDNA_RRF_K", "CAREERDNA_RRF_W_BM25", "CAREERDNA_RRF_W_SEM", "CAREERDNA_EMBED_TIMEOUT"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("CAREERDNA_RETRIEVAL_TUNING", str(tmp_path / "no_tuning.json"))


@pytest.fixture
def hybrid_env(monkeypatch):
    monkeypatch.setenv("CAREERDNA_RETRIEVAL_MODE", "hybrid")
    monkeypatch.setenv("CAREERDNA_SEM_MIN_SIM", "0.3")


@pytest.fixture
def fake_ollama(monkeypatch):
    srv = FakeOllama()
    monkeypatch.setenv("CAREERDNA_OLLAMA_URL", srv.url)
    monkeypatch.setenv("CAREERDNA_LLM_MODEL", "qwen2.5:3b")
    yield srv
    srv.stop()


@pytest.fixture
def no_ollama(monkeypatch):
    """Points the app at a port where nothing is listening."""
    monkeypatch.setenv("CAREERDNA_OLLAMA_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("CAREERDNA_LLM_TIMEOUT", "3")


@pytest.fixture
def fx_db(tmp_path, monkeypatch):
    path = str(tmp_path / "fixture.db")
    build_fixture_db(path)
    monkeypatch.setenv("CAREERDNA_DB", path)
    import main
    import routes.auth as auth
    import routes.profile as prof
    monkeypatch.setattr(main, "DB_PATH", path)
    monkeypatch.setattr(auth, "DB_PATH", path)
    monkeypatch.setattr(prof, "DB_PATH", path)
    return path


@pytest.fixture
def conn(fx_db):
    from ai.db import connect
    c = connect()
    yield c
    c.close()


@pytest.fixture
def client(fx_db):
    from fastapi.testclient import TestClient
    import main
    with TestClient(main.app) as c:
        yield c


def auth_header(user_id: int, email: str = "x@example.test"):
    from routes.auth import create_token
    tok = create_token(user_id, email)
    if isinstance(tok, dict):
        tok = tok.get("access_token")
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture
def ada_h():
    return auth_header(1, "ada@example.test")


@pytest.fixture
def bob_h():
    return auth_header(2, "bob@example.test")


@pytest.fixture
def ctx(conn):
    from ai.tools import ToolContext
    return ToolContext(conn, 1)


class ScriptedLLM:
    """Test double for ollama_client.chat that returns scripted answers and records every prompt it receives."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls = []

    def __call__(self, messages, settings=None, json_mode=False):
        self.calls.append(messages)
        a = self.answers[min(len(self.calls) - 1, len(self.answers) - 1)]
        if isinstance(a, Exception):
            raise a
        return {"content": a, "model": "scripted", "eval_count": 1}


@pytest.fixture
def scripted():
    return ScriptedLLM
