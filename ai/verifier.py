"""Deterministic explanation verification. Checks the LLM's answer against records and numbers produced by the backend.
No second LLM is used to judge the first - these are plain rules, so results are repeatable and testable."""
import re
from dataclasses import dataclass, field

NUM_RE = re.compile(r"(?<![\w.])\+?(-?\d+(?:\.\d+)?)\s*(%|percentage points?|percent|pp\b|lpa\b|lakhs?\b)", re.I)
REF_RE = re.compile(r"\[([a-z_]+:[A-Za-z0-9_:\-]+)\]")
SENT_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")
POSSESSION = re.compile(r"\byou (?:already )?(?:have|know|use|used|possess|are (?:proficient|skilled|experienced|strong|an expert)|"
                        r"(?:'ve|have) (?:built|used|worked|mastered))\b|\byour (?:strong|solid|advanced|proven|expert|extensive)\b|"
                        r"\b(?:proficient|experienced|skilled|expert|advanced) (?:in|with)\b|\byou(?:'re| are) (?:good|great|strong) (?:at|with|in)\b", re.I)
GAP_CUE = re.compile(r"\b(lack|lacks|lacking|missing|not (?:yet )?(?:listed|documented|in your|recorded|established|a skill)|no (?:record|evidence|data)|"
                     r"don't|do not|doesn't|does not|gap|need|should|learn|if you|would|could|hypothetical|scenario|simulat|requires?|required|"
                     r"haven't|have not|cannot be|can't be|insufficient|not enough|add(?:ing)?|after|once|assum)\b", re.I)
HEDGE = re.compile(r"cannot be (?:established|confirmed|determined|assessed)|can't be (?:established|confirmed)|no (?:record|evidence|data)|"
                   r"not (?:documented|recorded|listed|in your)|insufficient|available (?:data|records)|from your records|not enough", re.I)
INABILITY = re.compile(r"\byou (?:cannot|can't|are unable to|lack the ability|are not capable|are incapable|are incompetent|don't know|do not know|"
                       r"aren't (?:proficient|skilled|qualified)|are not (?:proficient|skilled|qualified|competent))\b|"
                       r"\bproves? (?:that )?you (?:lack|can't|cannot|don't)\b|\byou(?:'re| are) (?:unskilled|not good)\b", re.I)
GUARANTEE = re.compile(r"\bguarantee[sd]?\b|\bdefinitely (?:get|land|receive|secure)\b|\byou will (?:certainly |surely )?(?:get|land|receive|secure) (?:the|a) (?:job|offer|role|position|salary|raise)\b|\bassured (?:of )?(?:a |the )?(?:job|offer|salary)\b", re.I)
NEGATION_BEFORE = re.compile(r"(?:\bnot\b|\bno\b|\bnever\b|n't|\bwithout\b|\bnor\b|\bcannot\b)[^.]{0,30}$", re.I)
LEVELS = ("advanced", "intermediate", "beginner")
HYP_WORDS = re.compile(r"hypothetical|simulat|scenario|what-if|what if", re.I)


@dataclass
class Facts:
    profile_skills: dict            # lower name -> proficiency
    documented_skills: set          # lower names with project/cert records
    known_skills: list              # catalogue names
    project_titles: list
    certification_count: int
    refs: set
    numbers: dict                   # kind -> list[float]
    hypothetical: bool
    hypothetical_skills: set = field(default_factory=set)
    user_numbers: list = field(default_factory=list)  # numbers the user typed in the question
    cert_supported_skills: set = field(default_factory=set)  # lower names of skills a certification record supports


@dataclass
class Issue:
    code: str
    sentence: str
    detail: str

    def to_dict(self):
        return {"code": self.code, "sentence": self.sentence[:240], "detail": self.detail}


def _wb(name):
    return re.compile(r"(?<![A-Za-z0-9])" + re.escape(name.lower()) + r"(?![A-Za-z0-9])")


def _number_ok(x, allowed):
    ax = abs(x)
    return any(abs(ax - a) <= 0.051 or (float(ax).is_integer() and abs(a - ax) <= 0.5) for a in allowed)


def verify(answer: str, facts: Facts) -> list[Issue]:
    issues: list[Issue] = []
    sentences = [s.strip() for s in SENT_SPLIT.split(answer) if s.strip()]
    kind_map = {"%": "percent", "percentage point": "percent", "percentage points": "percent", "percent": "percent", "pp": "percent",
                "lpa": "lpa", "lakh": "lpa", "lakhs": "lpa"}
    for s in sentences:
        for m in NUM_RE.finditer(s):
            kind = kind_map.get(m.group(2).lower(), "percent")
            val = float(m.group(1))
            echo = abs(val) in [abs(u) for u in facts.user_numbers] and re.search(r"\b(mention|said|asked|stated|wrote|quoted|your question)", s.lower())
            if not _number_ok(val, facts.numbers.get(kind, [])) and not echo:
                issues.append(Issue("unsupported_number", s, f"{m.group(0)} does not match any backend-computed {kind} value"))
        for ref in REF_RE.findall(s):
            if ref not in facts.refs:
                issues.append(Issue("invalid_citation", s, f"[{ref}] is not a record supplied for this question"))
        low = s.lower()
        hypo_sentence = bool(GAP_CUE.search(s)) or (facts.hypothetical and HYP_WORDS.search(s) is not None)
        pm = POSSESSION.search(s)
        negated = bool(pm) and re.search(r"(?:\bnot|n't|\bnever|\bno longer)\s+(?:\w+\s+)?$", s[max(0, pm.start() - 14):pm.start()].lower() + " ") is not None
        if pm and not negated and not GAP_CUE.search(s):
            for name in facts.known_skills:
                n = name.lower()
                if _wb(n).search(low) and n not in facts.profile_skills and n not in facts.documented_skills and n not in facts.hypothetical_skills:
                    issues.append(Issue("claimed_skill_not_in_profile", s, f"'{name}' is not in your profile records"))
        for name, level in facts.profile_skills.items():
            if level and _wb(name).search(low) and not GAP_CUE.search(s):
                said = [l for l in LEVELS if re.search(r"\b" + l + r"\b", low)]
                if said and level.lower() not in said and len(said) == 1:
                    issues.append(Issue("proficiency_mismatch", s, f"records say {name} is {level}, not {said[0]}"))
        if re.search(r"certif", low) and re.search(r"\byou (?:have|hold|earned|completed|possess|are certified)\b|\byour certif", low) and not hypo_sentence:
            named = [n for n in facts.known_skills if _wb(n.lower()).search(low)]
            if facts.certification_count == 0:
                issues.append(Issue("claimed_certification_not_in_records", s, "no certification is recorded in your profile"))
            elif named and not any(n.lower() in facts.cert_supported_skills for n in named):
                issues.append(Issue("claimed_certification_not_in_records", s, f"no certification record supports {', '.join(named)}"))
        for q in re.findall(r"[\"“']([^\"”']{4,80})[\"”']", s):
            if re.search(r"project", low) and not any(q.lower() in t.lower() or t.lower() in q.lower() for t in facts.project_titles) and not facts.hypothetical:
                issues.append(Issue("unknown_project_reference", s, f"'{q}' is not one of your project titles"))
        if INABILITY.search(s) and not HEDGE.search(s):
            issues.append(Issue("missing_evidence_as_inability", s, "absence of records was stated as inability"))
        for gm in GUARANTEE.finditer(s):
            if not NEGATION_BEFORE.search(s[max(0, gm.start() - 40):gm.start()]):
                issues.append(Issue("guarantee_claim", s, "outcomes cannot be guaranteed"))
                break
    if facts.hypothetical and not HYP_WORDS.search(answer):
        issues.append(Issue("unlabelled_hypothetical", answer[:120], "scenario results were not labelled as hypothetical"))
    return issues


FIXABLE = {"unlabelled_hypothetical"}


def qualify(answer: str, issues: list[Issue]) -> tuple[str, int]:
    """Removes sentences that failed verification and adds a plain notice. Label problems are fixed by prefixing.
    Returns (text, number_of_verified_characters_kept) so callers can fall back when little survives."""
    bad = {i.sentence for i in issues if i.code not in FIXABLE}
    kept = [s for s in SENT_SPLIT.split(answer) if s.strip() and s.strip() not in bad]
    text = " ".join(kept).strip()
    kept_chars = len(text)
    if any(i.code == "unlabelled_hypothetical" for i in issues):
        text = "Hypothetical scenario (not your real profile): " + text
    if bad:
        text += f"\n\nNote: {len(bad)} statement(s) in the draft answer could not be verified against your data and were removed."
    return text, kept_chars


def numbers_from_tools(results: list[dict]) -> dict:
    out: dict = {"percent": [], "lpa": []}
    for r in results:
        for n in r.get("numbers", []):
            if n["kind"] in out:
                out[n["kind"]].append(abs(float(n["value"])))
    return out
