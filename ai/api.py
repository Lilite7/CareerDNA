"""FastAPI routes for the local AI assistant. All routes require the normal CareerDNA login token and only ever
touch the signed-in user's own records. Existing (non-AI) endpoints are unaffected if Ollama is not running."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from routes.auth import get_current_user

from . import ollama_client
from .agent import CareerAgent
from .config import ConfigError, get_retrieval_settings, get_settings
from .db import connect, ensure_ai_tables
from .tools import NoProfileError, ToolContext, call_tool

router = APIRouter(prefix="/ai", tags=["AI Assistant"])


def init_ai():
    try:
        ensure_ai_tables()
    except Exception:  # never block the app from starting
        pass


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=800)
    context: Optional[dict] = None


class ProjectChange(BaseModel):
    title: str = Field(default="hypothetical project", max_length=120)
    skills: list[str] = Field(default_factory=list, max_length=8)


class CertChange(BaseModel):
    name: str = Field(default="hypothetical certification", max_length=120)
    skills: list[str] = Field(default_factory=list, max_length=8)


class WhatIfAIRequest(BaseModel):
    add_skills: list[str] = Field(default_factory=list, max_length=8)
    add_projects: list[ProjectChange] = Field(default_factory=list, max_length=4)
    add_certifications: list[CertChange] = Field(default_factory=list, max_length=4)
    add_experience_months: int = Field(default=0, ge=0, le=120)
    roles: list[str] = Field(default_factory=list, max_length=4)
    explain: bool = False


def _ctx(conn, user):
    try:
        return ToolContext(conn, user["user_id"])
    except NoProfileError as e:
        raise HTTPException(status_code=404, detail=str(e))


def _explain(conn, user, ctx, question, calls):
    """Optionally asks the local LLM to explain deterministic results. Never blocks the deterministic part."""
    agent = CareerAgent(conn, user["user_id"])
    plan = {"intent": calls[0]["name"], "calls": calls, "roles": [], "skills": [], "premise_percents": [], "notes": [], "clarification": None}
    out = agent.run_plan(ctx, question, plan)
    return {k: out.get(k) for k in ("ok", "answer", "error", "fallback_summary", "verification", "latency_ms", "model")}


@router.get("/status")
def ai_status(user=Depends(get_current_user)):
    """Is Ollama reachable, is the configured model installed, and is it ready to answer?"""
    st = ollama_client.get_status()
    rs = get_retrieval_settings()
    st["retrieval"] = {"mode": rs.mode, "wiring": rs.wiring, "embed_model": rs.embed_model, "calibrated": rs.calibrated,
                       "min_similarity": rs.min_similarity, "warnings": list(rs.warnings)}
    st["embedding"] = ollama_client.embed_model_status(st, rs.embed_model)     # only matters when mode == 'hybrid'
    return st


@router.post("/chat")
def ai_chat(req: ChatRequest, user=Depends(get_current_user)):
    conn = connect()
    try:
        out = CareerAgent(conn, user["user_id"]).run(req.message, req.context)
    finally:
        conn.close()
    if not out.get("ok") and out.get("error", {}).get("code") == "NO_PROFILE":
        raise HTTPException(status_code=404, detail=out["error"]["message"])
    return out


@router.get("/options")
def ai_options(user=Depends(get_current_user)):
    conn = connect()
    try:
        ctx = _ctx(conn, user)
        return {"roles": [j["role"] for j in ctx.jobs], "skills": sorted(v["skill_name"] for v in ctx.catalog["by_id"].values()),
                "default_role": ctx.default_role()[0]["role"]}
    finally:
        conn.close()


@router.get("/evidence")
def ai_evidence(user=Depends(get_current_user)):
    conn = connect()
    try:
        ctx = _ctx(conn, user)
        ev = ctx.evidence()
        mine = {s["skill_id"] for s in ctx.profile["skills"]}
        rows = [e for e in ev.values() if e["in_profile"] or e["status"] != "no_record"]
        required = [e for sid, e in ev.items() if sid not in mine and e["status"] == "no_record"]
        return {"skills": sorted(rows, key=lambda e: e["skill_name"]), "required_by_roles_without_record": sorted(required, key=lambda e: e["skill_name"]),
                "assessment_data_available": False,
                "legend": {"documented": "supported by a project or certification record", "self_reported_only": "listed, but no project/certification linked",
                           "contradictory": "your own records disagree", "no_record": "nothing recorded - proficiency cannot be established (not proof of inability)"}}
    finally:
        conn.close()


@router.post("/what-if")
def ai_what_if(req: WhatIfAIRequest, user=Depends(get_current_user)):
    conn = connect()
    try:
        ctx = _ctx(conn, user)
        res = call_tool(ctx, "simulate_profile_change", {
            "add_skills": req.add_skills, "add_projects": [p.model_dump() for p in req.add_projects],
            "add_certifications": [c.model_dump() for c in req.add_certifications],
            "add_experience_months": req.add_experience_months, "roles": req.roles or None})
        if not res["ok"]:
            raise HTTPException(status_code=422, detail=res["error"])
        out = {"scenario": res["data"], "facts": res["lines"], "hypothetical": True}
        if req.explain:
            out["explanation"] = _explain(conn, user, ctx, "Explain these simulated results.", [{"name": "simulate_profile_change", "args": res["args"]}])
        return out
    finally:
        conn.close()


@router.get("/roadmap")
def ai_roadmap(role: Optional[str] = None, hours_per_week: float = Query(5, ge=1, le=80), weeks: int = Query(12, ge=1, le=104),
               explain: bool = False, user=Depends(get_current_user)):
    conn = connect()
    try:
        ctx = _ctx(conn, user)
        args = {"hours_per_week": hours_per_week, "weeks": weeks, **({"role": role} if role else {})}
        res = call_tool(ctx, "get_learning_roadmap", args)
        if not res["ok"]:
            raise HTTPException(status_code=422, detail=res["error"])
        out = {"roadmap": res["data"], "facts": res["lines"], "assumptions": res["assumptions"]}
        if explain:
            out["explanation"] = _explain(conn, user, ctx, "Explain this roadmap in plain language.", [{"name": "get_learning_roadmap", "args": res["args"]}])
        return out
    finally:
        conn.close()
