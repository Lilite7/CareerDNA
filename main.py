"""
CareerDNA FastAPI Backend

Run:

    uvicorn main:app --reload

Backend:
    http://127.0.0.1:8000

Swagger:
    http://127.0.0.1:8000/docs
"""

import os
import sqlite3
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from routes.auth import (
    get_current_user,
    init_auth_table,
    router as auth_router,
)
from routes.profile import init_profile_table, router as profile_router
from ai import scoring
from ai.api import router as ai_router, init_ai


# ============================================================
# PATHS
# ============================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DB_PATH = os.path.join(
    BASE_DIR,
    "careerdna.db",
)


# ============================================================
# APP
# ============================================================

app = FastAPI(
    title="CareerDNA API",
    version="1.0.0",
)


# ============================================================
# CORS
# ============================================================

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# AUTH ROUTES
# ============================================================

app.include_router(auth_router)
app.include_router(profile_router)
app.include_router(ai_router)  # local-LLM career assistant (/ai/*)


# ============================================================
# DATABASE
# ============================================================

def db():

    conn = sqlite3.connect(DB_PATH)

    conn.row_factory = sqlite3.Row

    return conn


def init_database_schema():
    conn = db()
    candidate_table = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'candidate'"
    ).fetchone()
    if not candidate_table:
        schema_path = os.path.join(BASE_DIR, "schema.sql")
        with open(schema_path, "r", encoding="utf-8") as schema_file:
            conn.executescript(schema_file.read())
    conn.commit()
    conn.close()


# ============================================================
# STARTUP
# ============================================================

@app.on_event("startup")
def startup():

    init_database_schema()
    init_auth_table()
    init_profile_table()
    init_ai()


# ============================================================
# HEALTH
# ============================================================

@app.get("/")
def root():

    return {
        "name": "CareerDNA API",
        "status": "running",
    }


@app.get("/health")
def health():

    return {
        "status": "healthy",
        "database": os.path.exists(DB_PATH),
    }


# ============================================================
# HELPER:
# FIND CANDIDATE FOR LOGGED-IN USER
# ============================================================

def get_candidate_for_user(
    current_user
):

    conn = db()
    try:

        candidate = conn.execute(
            """
            SELECT *
            FROM candidate
            WHERE user_id = ?
            LIMIT 1
            """,
            (current_user["user_id"],),
        ).fetchone()

    except sqlite3.OperationalError:

        candidate = None

    conn.close()

    if not candidate:

        raise HTTPException(
            status_code=404,
            detail=(
                "No CareerDNA profile is linked to this account. "
                "Complete your CareerDNA profile to continue."
            ),
        )

    return candidate


# ============================================================
# PROFILE
# ============================================================

@app.get("/profile")
def get_profile(
    current_user=Depends(get_current_user),
):

    candidate = get_candidate_for_user(
        current_user
    )

    candidate_id = candidate["candidate_id"]

    conn = db()

    education = conn.execute(
        """
        SELECT *
        FROM education
        WHERE candidate_id = ?
        """,
        (candidate_id,),
    ).fetchall()

    skills = conn.execute(
        """
        SELECT
            s.skill_name,
            cs.proficiency,
            cs.years,
            cs.evidence_score
        FROM candidate_skill cs
        JOIN skill s
            ON s.skill_id = cs.skill_id
        WHERE cs.candidate_id = ?
        ORDER BY cs.evidence_score DESC
        """,
        (candidate_id,),
    ).fetchall()

    projects = conn.execute(
        """
        SELECT *
        FROM project
        WHERE candidate_id = ?
        """,
        (candidate_id,),
    ).fetchall()

    certifications = conn.execute(
        """
        SELECT
            c.name,
            c.issuer,
            cc.issue_date
        FROM candidate_certification cc
        JOIN certification c
            ON c.certification_id = cc.certification_id
        WHERE cc.candidate_id = ?
        """,
        (candidate_id,),
    ).fetchall()

    conn.close()

    return {
        "candidate": dict(candidate),
        "education": [
            dict(row)
            for row in education
        ],
        "skills": [
            dict(row)
            for row in skills
        ],
        "projects": [
            dict(row)
            for row in projects
        ],
        "certifications": [
            dict(row)
            for row in certifications
        ],
    }


# ============================================================
# SKILL STRENGTH
# ============================================================

@app.get("/skill-strength")
def skill_strength(
    current_user=Depends(get_current_user),
):

    candidate = get_candidate_for_user(
        current_user
    )

    candidate_id = candidate["candidate_id"]

    conn = db()

    rows = conn.execute(
        """
        SELECT
            s.skill_name,
            cs.proficiency,
            cs.years,
            cs.evidence_score,

            COUNT(
                DISTINCT ps.project_id
            ) AS project_count

        FROM candidate_skill cs

        JOIN skill s
            ON s.skill_id = cs.skill_id

        LEFT JOIN project_skill ps
            ON ps.skill_id = cs.skill_id

        LEFT JOIN project p
            ON p.project_id = ps.project_id
            AND p.candidate_id = cs.candidate_id

        WHERE cs.candidate_id = ?

        GROUP BY
            s.skill_name,
            cs.proficiency,
            cs.years,
            cs.evidence_score

        ORDER BY
            cs.evidence_score DESC
        """,
        (candidate_id,),
    ).fetchall()

    conn.close()

    result = []

    for row in rows:

        result.append(
            {
                "name": row["skill_name"],
                "score": round(
                    float(row["evidence_score"] or 0)
                ),
                "years": row["years"],
                "proficiency": row["proficiency"],
                "project_count": row["project_count"],
            }
        )

    return {
        "skills": result
    }


# ============================================================
# SALARY
# ============================================================

@app.get("/salary")
def salary(
    current_user=Depends(get_current_user),
):

    candidate = get_candidate_for_user(
        current_user
    )

    conn = db()
    try:
        return scoring.estimate_salary(
            conn,
            candidate["candidate_id"],
        )
    finally:
        conn.close()


# ============================================================
# CAREER GAP
# ============================================================

@app.get("/career-gap")
def career_gap(
    role: Optional[str] = None,
    current_user=Depends(get_current_user),
):

    candidate = get_candidate_for_user(
        current_user
    )

    conn = db()
    try:
        return scoring.career_gap(
            conn,
            candidate["candidate_id"],
            role,
        )
    finally:
        conn.close()


# ============================================================
# JOB MATCH
# ============================================================

@app.get("/job-match")
def job_match(
    current_user=Depends(get_current_user),
):

    candidate = get_candidate_for_user(
        current_user
    )

    conn = db()
    try:
        results = scoring.job_match_all(
            conn,
            candidate["candidate_id"],
        )
    finally:
        conn.close()

    return {
        "jobs": results[:10]
    }


# ============================================================
# CAREER HISTORY
# ============================================================

@app.get("/career-history")
def career_history(
    current_user=Depends(get_current_user),
):

    candidate = get_candidate_for_user(
        current_user
    )

    candidate_id = candidate["candidate_id"]

    conn = db()

    try:

        rows = conn.execute(
            """
            SELECT *
            FROM salary_prediction
            WHERE candidate_id = ?
            ORDER BY timestamp ASC
            """,
            (candidate_id,),
        ).fetchall()

        history = []

        for row in rows:

            data = dict(row)

            salary_value = (
                data.get("predicted_salary")
                or data.get("salary")
                or data.get(
                    "predicted_salary_lpa"
                )
            )

            date_value = (
                data.get("timestamp")
                or data.get("created_at")
                or data.get("date")
            )

            if salary_value is not None:

                history.append(
                    {
                        "month": str(
                            date_value
                            or ""
                        ),
                        "salary": float(
                            salary_value
                        ),
                    }
                )

        conn.close()

        return {
            "history": history
        }

    except sqlite3.OperationalError:

        conn.close()

        return {
            "history": []
        }


# ============================================================
# WHAT-IF
# ============================================================

class WhatIfRequest(BaseModel):

    added_skill_ids: list[int] = []

    added_experience_months: int = 0

    added_certifications: int = 0


@app.post("/salary/what-if")
def salary_what_if(
    data: WhatIfRequest,
    current_user=Depends(get_current_user),
):

    candidate = get_candidate_for_user(
        current_user
    )

    conn = db()
    try:
        return scoring.salary_what_if(
            conn,
            candidate["candidate_id"],
            data.added_skill_ids,
            data.added_experience_months,
            data.added_certifications,
        )
    finally:
        conn.close()


# ============================================================
# ORIGINAL CANDIDATE ROUTES
# ============================================================
# These are kept so your old API URLs continue to work.


@app.get("/candidates/{candidate_id}/profile")
def candidate_profile(
    candidate_id: int,
):

    conn = db()

    candidate = conn.execute(
        """
        SELECT *
        FROM candidate
        WHERE candidate_id = ?
        """,
        (candidate_id,),
    ).fetchone()

    if not candidate:

        conn.close()

        raise HTTPException(
            status_code=404,
            detail="Candidate not found",
        )

    education = conn.execute(
        """
        SELECT *
        FROM education
        WHERE candidate_id = ?
        """,
        (candidate_id,),
    ).fetchall()

    skills = conn.execute(
        """
        SELECT
            s.skill_name,
            cs.proficiency,
            cs.years,
            cs.evidence_score

        FROM candidate_skill cs

        JOIN skill s
            ON s.skill_id = cs.skill_id

        WHERE cs.candidate_id = ?

        ORDER BY cs.evidence_score DESC
        """,
        (candidate_id,),
    ).fetchall()

    projects = conn.execute(
        """
        SELECT *
        FROM project
        WHERE candidate_id = ?
        """,
        (candidate_id,),
    ).fetchall()

    certifications = conn.execute(
        """
        SELECT
            c.name,
            c.issuer,
            cc.issue_date

        FROM candidate_certification cc

        JOIN certification c
            ON c.certification_id =
               cc.certification_id

        WHERE cc.candidate_id = ?
        """,
        (candidate_id,),
    ).fetchall()

    conn.close()

    return {
        "candidate": dict(candidate),
        "education": [
            dict(row)
            for row in education
        ],
        "skills": [
            dict(row)
            for row in skills
        ],
        "projects": [
            dict(row)
            for row in projects
        ],
        "certifications": [
            dict(row)
            for row in certifications
        ],
    }