"""TEST DOUBLES ONLY. ConceptEmbedder is a tiny synonym-lexicon 'embedding' used to exercise the hybrid pipeline
deterministically. It is NOT a semantic model and says nothing about the quality of nomic-embed-text."""
import re

GROUPS = [
    "money salary salaries pay wage wages earn earning compensation spending spent cost bills budget",
    "predict forecast estimate projection prediction anticipate predicts forecasts",
    "security attack attacks intrusion threat threats hackers hacker malicious fraud fraudulent phishing scam suspicious breach",
    "network traffic connections firewall packets",
    "machine learning neural model classifier classify classification classifies",
    "image images xray scan scans camera vision recognition recognise recognizes",
    "hiring candidate candidates applicant applicants resume vacancy shortlisting recruit",
    "web app application website",
    "cloud aws infrastructure hosted servers",
    "intern internship trainee",
    "teach teaching assistant tutor",
    "credential credentials certification certificate qualification",
    "defensive monitoring monitor watch",
]
_AXIS = {}
for i, g in enumerate(GROUPS):
    for w in g.split():
        _AXIS[w] = i
N_AXES = len(GROUPS) + 1          # last axis = tiny constant so a text with no known concept is never an all-zero vector (real models never return one)


def toks(text):
    out = []
    for t in re.findall(r"[a-z0-9]+", text.lower()):
        out.append(t)
        if t.endswith("s") and len(t) > 3:
            out.append(t[:-1])
    return out


def concept_vec(text, dim=None):
    dim = dim or N_AXES
    v = [0.0] * dim
    v[N_AXES - 1] = 0.05
    for t in toks(text):
        if t in _AXIS:
            v[_AXIS[t]] += 1.0
    return v


class Recorder:
    """Wraps an embed function and remembers every call."""

    def __init__(self, fn=None, dim=None):
        self.fn = fn or (lambda texts: [concept_vec(t, dim) for t in texts])
        self.calls = []

    def __call__(self, texts):
        self.calls.append(list(texts))
        return self.fn(texts)

    @property
    def texts(self):
        return [t for c in self.calls for t in c]
