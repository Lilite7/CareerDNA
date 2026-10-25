"""Configuration for the local AI assistant. Everything is read from environment variables
(re-read on every call so tests and users can change them without code edits)."""
import os
from dataclasses import dataclass
from urllib.parse import urlparse

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "[::1]"}


@dataclass(frozen=True)
class AISettings:
    base_url: str
    model: str
    timeout: float
    temperature: float
    num_ctx: int
    num_predict: int
    keep_alive: str
    max_regenerations: int


class ConfigError(ValueError):
    pass


def _f(name, default):
    try:
        return float(os.getenv(name, default))
    except ValueError:
        raise ConfigError(f"{name} must be a number")


def get_settings() -> AISettings:
    base = os.getenv("CAREERDNA_OLLAMA_URL", "http://localhost:11434").rstrip("/")
    host = (urlparse(base).hostname or "").lower()
    # Privacy guard: profile data must never leave this machine unless the user explicitly opts in.
    if host not in LOCAL_HOSTS and os.getenv("CAREERDNA_ALLOW_REMOTE_OLLAMA") != "1":
        raise ConfigError(
            f"CAREERDNA_OLLAMA_URL points to '{host}', which is not this computer. "
            "CareerDNA only sends profile data to a local Ollama. "
            "(Set CAREERDNA_ALLOW_REMOTE_OLLAMA=1 only if you fully trust that server.)"
        )
    return AISettings(
        base_url=base,
        model=os.getenv("CAREERDNA_LLM_MODEL", "qwen2.5:3b").strip(),
        timeout=_f("CAREERDNA_LLM_TIMEOUT", "180"),
        temperature=_f("CAREERDNA_LLM_TEMPERATURE", "0.2"),
        num_ctx=int(_f("CAREERDNA_LLM_NUM_CTX", "4096")),
        num_predict=int(_f("CAREERDNA_LLM_NUM_PREDICT", "500")),
        keep_alive=os.getenv("CAREERDNA_LLM_KEEP_ALIVE", "10m"),
        max_regenerations=int(_f("CAREERDNA_LLM_MAX_REGEN", "1")),
    )


# ----------------------------------------------------------------------------------------------
# Retrieval settings (Hybrid RAG). Defaults reproduce the previous behaviour exactly:
#   mode=bm25, wiring=legacy.  Invalid values never crash the app; they fall back and are reported in `warnings`.
import json as _json
import os as _os
from dataclasses import field as _field

MODES = ("bm25", "hybrid")
WIRINGS = ("legacy", "improved")
DEFAULT_EMBED_MODEL = "nomic-embed-text"
SUPPORTED_EMBED_MODELS = ("nomic-embed-text", "all-minilm")
UNCALIBRATED_MIN_SIM = 0.55   # placeholder GUESS until `python -m ai.retrieval_eval tune` writes eval/retrieval_tuning.json


@dataclass(frozen=True)
class RetrievalSettings:
    mode: str
    wiring: str
    embed_model: str
    embed_timeout: float
    rrf_k: int
    w_bm25: float
    w_sem: float
    min_similarity: float
    calibrated: bool
    pool: int
    warnings: tuple = ()


def _norm_model(name: str) -> str:
    name = (name or "").strip()
    return name[:-7] if name.endswith(":latest") else name


def tuning_path() -> str:
    from .db import BASE_DIR
    return _os.getenv("CAREERDNA_RETRIEVAL_TUNING") or _os.path.join(BASE_DIR, "eval", "retrieval_tuning.json")


def _num(name, default, cast, warnings):
    raw = _os.getenv(name)
    if raw in (None, ""):
        return default, False
    try:
        return cast(raw), True
    except ValueError:
        warnings.append(f"{name}={raw!r} is not a valid number; using {default}")
        return default, False


def get_retrieval_settings() -> RetrievalSettings:
    warnings = []
    mode = (_os.getenv("CAREERDNA_RETRIEVAL_MODE") or "bm25").strip().lower()
    if mode not in MODES:
        warnings.append(f"CAREERDNA_RETRIEVAL_MODE={mode!r} is not one of {MODES}; using 'bm25'")
        mode = "bm25"
    wiring = (_os.getenv("CAREERDNA_RETRIEVAL_WIRING") or "legacy").strip().lower()
    if wiring not in WIRINGS:
        warnings.append(f"CAREERDNA_RETRIEVAL_WIRING={wiring!r} is not one of {WIRINGS}; using 'legacy'")
        wiring = "legacy"
    model = _norm_model(_os.getenv("CAREERDNA_EMBED_MODEL") or DEFAULT_EMBED_MODEL)
    timeout, _ = _num("CAREERDNA_EMBED_TIMEOUT", 20.0, float, warnings)
    rrf_k, _ = _num("CAREERDNA_RRF_K", 60, int, warnings)
    w_b, b_env = _num("CAREERDNA_RRF_W_BM25", 1.0, float, warnings)
    w_s, s_env = _num("CAREERDNA_RRF_W_SEM", 1.0, float, warnings)
    min_sim, m_env = _num("CAREERDNA_SEM_MIN_SIM", UNCALIBRATED_MIN_SIM, float, warnings)
    calibrated = m_env
    try:   # values tuned on the DEV split only (see ai/retrieval_eval.py tune); env vars still override
        with open(tuning_path(), encoding="utf-8") as f:
            t = _json.load(f).get("models", {}).get(model)
        if t:
            if not m_env:
                min_sim, calibrated = float(t["min_similarity"]), True
            if not b_env:
                w_b = float(t.get("w_bm25", w_b))
            if not s_env:
                w_s = float(t.get("w_sem", w_s))
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return RetrievalSettings(mode=mode, wiring=wiring, embed_model=model, embed_timeout=max(1.0, timeout), rrf_k=max(1, rrf_k),
                             w_bm25=max(0.0, w_b), w_sem=max(0.0, w_s), min_similarity=min_sim, calibrated=calibrated,
                             pool=20, warnings=tuple(warnings))
