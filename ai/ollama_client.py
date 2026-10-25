"""Minimal Ollama client using only the Python standard library (no new dependencies).
Talks ONLY to the configured (local) Ollama server. Never falls back to any online service."""
import json
import socket
import urllib.error
import urllib.request

import math

from .config import AISettings, ConfigError, get_retrieval_settings, get_settings


class OllamaError(Exception):
    def __init__(self, code: str, message: str, instructions: str = ""):
        super().__init__(message)
        self.code = code
        self.message = message
        self.instructions = instructions

    def to_dict(self):
        return {"code": self.code, "message": self.message, "instructions": self.instructions}


START_HELP = (
    "Start Ollama: open the Ollama app from the Start menu, or run `ollama serve` in PowerShell. "
    "Then check it with `ollama list`."
)


def http_request(method: str, url: str, payload=None, timeout: float = 10.0):
    """Single network seam (monkeypatched in unit tests). Returns (status_code, parsed_json_or_text)."""
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "replace")
            status = resp.status
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        status = e.code
    try:
        return status, json.loads(raw)
    except ValueError:
        return status, raw


def _map_transport_error(exc: Exception, settings: AISettings) -> OllamaError:
    if isinstance(exc, (socket.timeout, TimeoutError)):
        return OllamaError("OLLAMA_TIMEOUT",
                           f"The local model did not answer within {settings.timeout:.0f}s.",
                           "A small laptop may need longer for the first answer (the model is loading). "
                           "Try again, raise CAREERDNA_LLM_TIMEOUT, or use a smaller model such as qwen2.5:1.5b.")
    reason = getattr(exc, "reason", exc)
    if isinstance(reason, (socket.timeout, TimeoutError)):
        return _map_transport_error(reason, settings)
    return OllamaError("OLLAMA_UNREACHABLE",
                       f"Cannot reach Ollama at {settings.base_url}.", START_HELP)


def _model_installed(wanted: str, names: list[str]) -> bool:
    wanted = wanted.lower()
    cand = {wanted, wanted if ":" in wanted else wanted + ":latest"}
    return any(n.lower() in cand for n in names)


def get_status(settings: AISettings | None = None) -> dict:
    """Reports reachability, whether the configured model is installed, and readiness."""
    try:
        settings = settings or get_settings()
    except ConfigError as e:
        return {"reachable": False, "model": None, "model_installed": False, "ready": False,
                "installed_models": [], "loaded": False,
                "error": {"code": "CONFIG_ERROR", "message": str(e), "instructions": ""}}
    out = {"base_url": settings.base_url, "model": settings.model, "reachable": False,
           "model_installed": False, "ready": False, "loaded": False, "installed_models": [],
           "model_size_bytes": None, "error": None}
    try:
        status, body = http_request("GET", f"{settings.base_url}/api/tags", timeout=min(settings.timeout, 5))
    except Exception as exc:  # noqa: BLE001 - mapped to a friendly error
        out["error"] = _map_transport_error(exc, settings).to_dict()
        return out
    if status != 200 or not isinstance(body, dict):
        out["error"] = OllamaError("OLLAMA_BAD_RESPONSE", f"Ollama answered HTTP {status} to /api/tags.",
                                   "Make sure the URL points at an Ollama server (default http://localhost:11434).").to_dict()
        return out
    out["reachable"] = True
    models = body.get("models") or []
    names = [m.get("name") or m.get("model") or "" for m in models]
    out["installed_models"] = names
    out["model_installed"] = _model_installed(settings.model, names)
    for m in models:
        if (m.get("name") or "").lower() in {settings.model.lower(), settings.model.lower() + ":latest"}:
            out["model_size_bytes"] = m.get("size")
            out["model_digest"] = m.get("digest")
    if not out["model_installed"]:
        out["error"] = OllamaError(
            "MODEL_MISSING", f"Model '{settings.model}' is not installed in Ollama.",
            f"Install it with: ollama pull {settings.model}   (then click Refresh).").to_dict()
        return out
    out["ready"] = True
    try:  # informational only: is the model currently loaded in memory?
        st, ps = http_request("GET", f"{settings.base_url}/api/ps", timeout=3)
        if st == 200 and isinstance(ps, dict):
            out["loaded"] = any(_model_installed(settings.model, [m.get("name", "")]) for m in ps.get("models", []))
    except Exception:  # noqa: BLE001
        pass
    return out


def chat(messages: list[dict], settings: AISettings | None = None, json_mode: bool = False) -> dict:
    """Calls Ollama /api/chat (non-streaming). Raises OllamaError with an actionable message."""
    settings = settings or get_settings()
    payload = {
        "model": settings.model,
        "messages": messages,
        "stream": False,
        "keep_alive": settings.keep_alive,
        "options": {"temperature": settings.temperature, "num_ctx": settings.num_ctx,
                    "num_predict": settings.num_predict},
    }
    if json_mode:
        payload["format"] = "json"
    try:
        status, body = http_request("POST", f"{settings.base_url}/api/chat", payload, timeout=settings.timeout)
    except Exception as exc:  # noqa: BLE001
        raise _map_transport_error(exc, settings) from exc
    if status == 404 or (isinstance(body, dict) and "not found" in str(body.get("error", "")).lower()):
        raise OllamaError("MODEL_MISSING", f"Model '{settings.model}' is not installed in Ollama.",
                          f"Install it with: ollama pull {settings.model}")
    if status != 200 or not isinstance(body, dict):
        detail = body.get("error") if isinstance(body, dict) else str(body)[:200]
        raise OllamaError("OLLAMA_ERROR", f"Ollama returned HTTP {status}: {detail}",
                          "Check the Ollama window/logs. Low memory is the most common cause.")
    content = ((body.get("message") or {}).get("content") or "").strip()
    if not content:
        raise OllamaError("EMPTY_RESPONSE", "The model returned an empty answer.", "Try asking again.")
    return {"content": content, "model": body.get("model", settings.model),
            "eval_count": body.get("eval_count"), "total_duration_ns": body.get("total_duration")}


# ----------------------------------------------------------------------------------------------
# Embeddings (Hybrid RAG). Local Ollama only, same host guard as chat().
def embed(texts: list[str], model: str | None = None, timeout: float | None = None, settings: AISettings | None = None) -> list[list[float]]:
    """Returns one vector per input text via Ollama /api/embed. Raises OllamaError with an EMBED_* code on any problem."""
    settings = settings or get_settings()
    rs = get_retrieval_settings()
    model = model or rs.embed_model
    timeout = timeout or rs.embed_timeout
    if not texts:
        return []
    payload = {"model": model, "input": list(texts), "truncate": True, "keep_alive": settings.keep_alive}
    try:
        status, body = http_request("POST", f"{settings.base_url}/api/embed", payload, timeout=timeout)
    except Exception as exc:  # noqa: BLE001
        err = _map_transport_error(exc, settings)
        raise OllamaError("EMBED_TIMEOUT" if err.code == "OLLAMA_TIMEOUT" else "EMBED_UNREACHABLE", err.message, err.instructions) from exc
    text = (body.get("error") if isinstance(body, dict) else str(body)) or ""
    if status == 404 and "model" in text.lower() and "not found" in text.lower():
        raise OllamaError("EMBED_MODEL_MISSING", f"Embedding model '{model}' is not installed in Ollama.", f"Install it with: ollama pull {model}")
    if status == 404:
        raise OllamaError("EMBED_UNSUPPORTED", "This Ollama version does not provide /api/embed.", "Update Ollama to a recent version.")
    if status != 200 or not isinstance(body, dict):
        raise OllamaError("EMBED_ERROR", f"Ollama returned HTTP {status} for embeddings: {text[:160]}", "Check the Ollama window/logs.")
    vecs = body.get("embeddings")
    ok = isinstance(vecs, list) and len(vecs) == len(texts)
    dim = None
    if ok:
        for v in vecs:
            good = (isinstance(v, list) and v and all(isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) for x in v)
                    and any(x != 0 for x in v))
            dim = dim or (len(v) if isinstance(v, list) else None)
            if not good or len(v) != dim:
                ok = False
                break
    if not ok:
        raise OllamaError("EMBED_BAD_RESPONSE", "Ollama returned malformed embeddings.", "Try again, or use a different embedding model.")
    return [[float(x) for x in v] for v in vecs]


def embed_model_status(status: dict, model: str | None = None) -> dict:
    """Derives embedding readiness from an existing get_status() result (no extra network call)."""
    model = model or get_retrieval_settings().embed_model
    if not status.get("reachable"):
        return {"model": model, "installed": False, "ready": False,
                "error": {"code": "EMBED_UNREACHABLE", "message": "Ollama is not reachable, so embeddings are unavailable.", "instructions": START_HELP}}
    installed = _model_installed(model, status.get("installed_models", []))
    return {"model": model, "installed": installed, "ready": installed,
            "error": None if installed else {"code": "EMBED_MODEL_MISSING", "message": f"Embedding model '{model}' is not installed.",
                                             "instructions": f"Install it with: ollama pull {model}"}}
