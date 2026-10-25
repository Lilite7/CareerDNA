"""Deterministic personalised roadmap. Rules pick WHAT to work on and in what order; the LLM only explains it."""
from .knowledge import DEFAULT_EFFORT, EFFORT_HOURS, PREREQUISITES

LEVEL_RANK = {"Critical": 0, "Required": 1, "Nice-to-have": 2}
DOC_EFFORT = (10, 30)  # curated planning range for documenting an already-listed skill in a project


def build_roadmap(profile: dict, job: dict, evid: dict, hours_per_week: float, weeks: int) -> dict:
    have = {s["skill_name"].lower() for s in profile["skills"]}
    ACTION_RANK = {"learn": 0, "review": 1, "document": 2}   # tie-break: closing a missing skill moves the official match most
    todo = []
    for r in job["requirements"]:
        e = evid.get(r["skill_id"], {})
        if r["skill_name"].lower() not in have:
            todo.append((r, "learn"))
        elif e.get("status") == "contradictory":
            todo.append((r, "review"))
        elif e.get("status") == "self_reported_only":
            todo.append((r, "document"))
    todo.sort(key=lambda t: (LEVEL_RANK.get(t[0]["required_level"], 3), -float(t[0]["importance"] or 1), ACTION_RANK[t[1]], t[0]["skill_name"]))
    items, planned = [], set()

    def add(item):
        items.append(item); planned.add(item["skill"].lower())

    def schedule_missing(name, level, importance, source, reason):
        for pre in PREREQUISITES.get(name, []):
            if pre.lower() not in have and pre.lower() not in planned:
                schedule_missing(pre, None, None, "curated prerequisite rule", f"usually learned before {name}")
        if name.lower() in planned:
            return
        lo, hi = EFFORT_HOURS.get(name, DEFAULT_EFFORT)
        add({"action": "learn", "skill": name, "required_level": level, "importance": importance, "source": source,
             "reason": reason, "hours_low": lo, "hours_high": hi})

    for r, act in todo:
        if act == "learn":
            schedule_missing(r["skill_name"], r["required_level"], float(r["importance"] or 1), "job requirement (database)",
                             f"{r['required_level']} requirement for {job['role']} that is not in your profile")
        else:
            reason = ("your records disagree about this skill" if act == "review"
                      else f"listed but no project/certification evidence is linked yet ({job['role']} requirement)")
            lo, hi = (5, 10) if act == "review" else DOC_EFFORT
            add({"action": act, "skill": r["skill_name"], "required_level": r["required_level"], "importance": float(r["importance"] or 1),
                 "source": "job requirement (database)", "reason": reason, "hours_low": lo, "hours_high": hi})

    budget = hours_per_week * weeks
    cum_lo = cum_hi = 0.0
    for n, it in enumerate(items, 1):
        cum_lo += it["hours_low"]; cum_hi += it["hours_high"]
        it["step"] = n
        it["cumulative_hours"] = [round(cum_lo), round(cum_hi)]
        it["fits_window"] = "yes" if cum_hi <= budget else ("maybe" if cum_lo <= budget else "no")
        it["estimated_weeks"] = [round(cum_lo / hours_per_week, 1), round(cum_hi / hours_per_week, 1)]
    return {"role": job["role"], "hours_per_week": hours_per_week, "weeks": weeks, "budget_hours": round(budget),
            "items": items, "total_hours": [round(cum_lo), round(cum_hi)],
            "nothing_to_do": not items,
            "disclaimer": "Hour figures are rough planning estimates from a curated table in the code, not promises. "
                          "Individual pace varies. Prerequisite order is a planning aid, not a job requirement."}
