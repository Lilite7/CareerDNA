"""Deterministic entity extraction: which roles / skills does a piece of text mention?"""
import re

from .knowledge import GENERIC_ROLE_WORDS, ROLE_EXTRA_ALIASES, SKILL_ALIASES


def _pat(alias: str):
    return re.compile(r"(?<![A-Za-z0-9])" + re.escape(alias.lower()) + r"(?![A-Za-z0-9])")


def role_aliases(role: str) -> list[str]:
    low = role.lower()
    aliases = {low}
    for p in re.split(r"[^a-z0-9+#]+", low):
        if len(p) >= 3 and p not in GENERIC_ROLE_WORDS:
            aliases.add(p)
    aliases.update(ROLE_EXTRA_ALIASES.get(low, []))
    return sorted(aliases, key=len, reverse=True)  # longest first so we mask the most specific phrase


def find_roles_in_text(jobs: list[dict], text: str) -> tuple[list[str], str]:
    """Returns (roles in order of first mention, text with the matched role phrases blanked out)."""
    low = (text or "").lower()
    hits = []  # (start, end, role)
    for j in jobs:
        for a in role_aliases(j["role"]):
            for m in _pat(a).finditer(low):
                hits.append((m.start(), m.end(), j["role"]))
    hits.sort(key=lambda h: (h[0], -(h[1] - h[0])))
    roles, masked, taken = [], list(low), []
    for s, e, role in hits:
        if any(not (e <= ts or s >= te) for ts, te in taken):
            continue
        taken.append((s, e))
        if role not in roles:
            roles.append(role)
        for i in range(s, e):
            masked[i] = " "
    return roles, "".join(masked)


def find_skills_in_text(catalog: dict, text: str) -> list[str]:
    low = (text or "").lower()
    cands = {sk["skill_name"].lower(): sk["skill_name"] for sk in catalog["by_id"].values()}
    for alias, name in SKILL_ALIASES.items():
        if name.lower() in cands:
            cands[alias] = cands[name.lower()]
    hits = []
    for alias, canon in cands.items():
        for m in _pat(alias).finditer(low):
            hits.append((m.start(), m.end(), canon))
    hits.sort(key=lambda h: (h[0], -(h[1] - h[0])))
    out, taken = [], []
    for s, e, canon in hits:
        if any(not (e <= ts or s >= te) for ts, te in taken):
            continue
        taken.append((s, e))
        if canon not in out:
            out.append(canon)
    return out


def resolve_role(jobs: list[dict], text: str):
    """Maps free text like 'ml engineer' to one job row, or None."""
    if not text:
        return None
    for j in jobs:
        if j["role"].lower() == text.strip().lower():
            return j
    roles, _ = find_roles_in_text(jobs, text)
    if len(roles) == 1:
        return next(j for j in jobs if j["role"] == roles[0])
    return None
