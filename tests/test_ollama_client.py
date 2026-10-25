import pytest

from ai import ollama_client
from ai.config import ConfigError, get_settings
from ai.ollama_client import OllamaError


def test_unreachable_reports_actionable_error(no_ollama):
    st = ollama_client.get_status()
    assert st["reachable"] is False and st["ready"] is False
    assert st["error"]["code"] == "OLLAMA_UNREACHABLE"
    assert "ollama serve" in st["error"]["instructions"]
    with pytest.raises(OllamaError) as e:
        ollama_client.chat([{"role": "user", "content": "hi"}])
    assert e.value.code == "OLLAMA_UNREACHABLE"


def test_model_missing_in_status(fake_ollama, monkeypatch):
    fake_ollama.models = [{"name": "llama3:8b"}]
    st = ollama_client.get_status()
    assert st["reachable"] is True and st["model_installed"] is False and st["ready"] is False
    assert st["error"]["code"] == "MODEL_MISSING"
    assert "ollama pull qwen2.5:3b" in st["error"]["instructions"]


def test_model_missing_on_chat_404(fake_ollama):
    fake_ollama.chat_handler = lambda p: (404, {"error": "model 'qwen2.5:3b' not found, try pulling it first"})
    with pytest.raises(OllamaError) as e:
        ollama_client.chat([{"role": "user", "content": "hi"}])
    assert e.value.code == "MODEL_MISSING"


def test_ready_and_successful_chat_use_local_api(fake_ollama, monkeypatch):
    monkeypatch.setenv("CAREERDNA_LLM_TEMPERATURE", "0.1")
    fake_ollama.loaded = [{"name": "qwen2.5:3b"}]
    st = ollama_client.get_status()
    assert st["ready"] is True and st["loaded"] is True and st["error"] is None
    fake_ollama.chat_handler = lambda p: (200, {"model": p["model"], "message": {"role": "assistant", "content": "Hello from the model"}, "eval_count": 7})
    out = ollama_client.chat([{"role": "user", "content": "hi"}])
    assert out["content"] == "Hello from the model"
    sent = [r for r in fake_ollama.requests if r[1] == "/api/chat"][0][2]
    assert sent["model"] == "qwen2.5:3b" and sent["stream"] is False
    assert sent["options"]["temperature"] == 0.1 and "num_ctx" in sent["options"]


def test_model_name_without_tag_matches_latest(fake_ollama, monkeypatch):
    fake_ollama.models = [{"name": "qwen2.5:latest"}]
    monkeypatch.setenv("CAREERDNA_LLM_MODEL", "qwen2.5")
    assert ollama_client.get_status()["model_installed"] is True


def test_timeout_is_reported(fake_ollama, monkeypatch):
    monkeypatch.setenv("CAREERDNA_LLM_TIMEOUT", "0.3")
    fake_ollama.delay = 1.0
    with pytest.raises(OllamaError) as e:
        ollama_client.chat([{"role": "user", "content": "hi"}])
    assert e.value.code == "OLLAMA_TIMEOUT"


def test_empty_answer_is_an_error(fake_ollama):
    fake_ollama.chat_handler = lambda p: (200, {"model": "m", "message": {"content": "  "}})
    with pytest.raises(OllamaError) as e:
        ollama_client.chat([{"role": "user", "content": "hi"}])
    assert e.value.code == "EMPTY_RESPONSE"


def test_remote_endpoint_is_refused_by_default(monkeypatch):
    monkeypatch.setenv("CAREERDNA_OLLAMA_URL", "https://api.some-cloud-llm.example")
    with pytest.raises(ConfigError):
        get_settings()
    st = ollama_client.get_status()
    assert st["ready"] is False and st["error"]["code"] == "CONFIG_ERROR"


def test_remote_endpoint_requires_explicit_opt_in(monkeypatch):
    monkeypatch.setenv("CAREERDNA_OLLAMA_URL", "http://192.168.1.50:11434")
    monkeypatch.setenv("CAREERDNA_ALLOW_REMOTE_OLLAMA", "1")
    assert get_settings().base_url == "http://192.168.1.50:11434"


def test_settings_defaults(monkeypatch):
    for k in ("CAREERDNA_OLLAMA_URL", "CAREERDNA_LLM_MODEL", "CAREERDNA_LLM_TIMEOUT"):
        monkeypatch.delenv(k, raising=False)
    s = get_settings()
    assert s.base_url == "http://localhost:11434" and s.model == "qwen2.5:3b"
