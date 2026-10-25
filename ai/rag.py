"""Lightweight LOCAL retrieval (BM25, pure Python, no downloads) over the user's unstructured text:
project descriptions, experience, goals/headline, certifications, and job requirement summaries.
Structured numbers (scores, salaries) never come from retrieval - they come from backend functions.
Embeddings/pgvector are deliberately NOT used: this project runs on SQLite and BM25 is enough for a handful of records."""
import math
import re
from collections import Counter

STOP = set("a an the and or of to in on for with is are was were be by at as from that this it you your my i me what why how which do does can".split())


def tokenize(text: str) -> list[str]:
    toks = re.findall(r"[a-z0-9\+\#\.]+", (text or "").lower())
    out = []
    for t in toks:
        t = t.strip(".")
        if len(t) > 3 and t.endswith("s") and not t.endswith("ss"):
            t = t[:-1]
        if t and t not in STOP:
            out.append(t)
    return out


def build_documents(profile: dict, jobs: list[dict], catalog: dict) -> list[dict]:
    docs = []
    names = lambda ids: ", ".join(catalog["by_id"][i]["skill_name"] for i in ids if i in catalog["by_id"])
    for p in profile["projects"]:
        docs.append({"ref": f"project:{p['project_id']}", "type": "project", "title": p["title"],
                     "text": f"{p['title']}. {p.get('description') or ''} Skills used: {names(p.get('skill_ids', []))}. Complexity {p.get('complexity')}, impact {p.get('impact')}."})
    for e in profile["experience"]:
        docs.append({"ref": f"experience:{e['experience_id']}", "type": "experience", "title": f"{e.get('role')} at {e.get('company')}",
                     "text": f"{e.get('role')} at {e.get('company')}, domain {e.get('domain')}, {e.get('start_date')} to {e.get('end_date')}."})
    for c in profile["certifications"]:
        docs.append({"ref": f"certification:{c['certification_id']}", "type": "certification", "title": c["name"],
                     "text": f"{c['name']} issued by {c.get('issuer')}, domain {c.get('domain')}, status {c.get('verification_status')}."})
    if profile.get("goals") or profile.get("headline"):
        docs.append({"ref": "profile:goals", "type": "profile", "title": "Headline and career goals",
                     "text": f"{profile.get('headline')}. {profile.get('goals')}"})
    for j in jobs:
        docs.append({"ref": f"job:{j['job_id']}", "type": "job", "title": f"{j['role']} ({j.get('company')})",
                     "text": f"{j['role']} at {j.get('company')} in {j.get('location')}. Requires: " +
                             ", ".join(f"{r['skill_name']} ({r['required_level']})" for r in j["requirements"])})
    return docs


def retrieve(query: str, docs: list[dict], k: int = 4, types: set[str] | None = None) -> list[dict]:
    pool = [d for d in docs if not types or d["type"] in types]
    q = tokenize(query)
    if not q or not pool:
        return []
    toks = [tokenize(d["title"] + " " + d["text"]) for d in pool]
    n = len(pool)
    avgdl = sum(len(t) for t in toks) / n or 1
    df = Counter(w for t in toks for w in set(t))
    scored = []
    for d, t in zip(pool, toks):
        tf = Counter(t)
        s = 0.0
        for w in set(q):
            if w in tf:
                idf = math.log(1 + (n - df[w] + 0.5) / (df[w] + 0.5))
                s += idf * tf[w] * 2.5 / (tf[w] + 1.5 * (0.25 + 0.75 * len(t) / avgdl))
        if s > 0:
            scored.append({**d, "score": round(s, 3)})
    scored.sort(key=lambda x: -x["score"])
    return scored[:k]
