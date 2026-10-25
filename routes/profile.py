import json
import os
import sqlite3
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr

from routes.auth import get_current_user

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "careerdna.db")

router = APIRouter(tags=["Profile"])


class EducationInput(BaseModel):
    degree: str
    institution: str
    field: Optional[str] = ""
    cgpa: Optional[float] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None


class ExperienceInput(BaseModel):
    company: str
    role: str
    domain: Optional[str] = ""
    start_date: Optional[str] = None
    end_date: Optional[str] = None


class SkillInput(BaseModel):
    name: str
    category: Optional[str] = "General"
    proficiency: str = "Intermediate"
    years: float = 0
    evidence_score: float = 0


class ProjectInput(BaseModel):
    title: str
    description: Optional[str] = ""
    complexity: str = "Medium"
    impact: str = "Medium"
    solo: bool = True
    github_url: Optional[str] = ""
    skills: list[str] = []


class CertificationInput(BaseModel):
    name: str
    issuer: Optional[str] = ""
    issue_date: Optional[str] = None


class ProfileSetupRequest(BaseModel):
    name: Optional[str] = None
    email: Optional[EmailStr] = None
    location: str = ""
    headline: str = ""
    goals: str = ""
    education: list[EducationInput] = []
    experience: list[ExperienceInput] = []
    skills: list[SkillInput] = []
    projects: list[ProjectInput] = []
    certifications: list[CertificationInput] = []


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_profile_table():
    conn = get_db()
    columns = {row[1] for row in conn.execute("PRAGMA table_info(candidate)").fetchall()}
    if "user_id" not in columns:
        conn.execute("ALTER TABLE candidate ADD COLUMN user_id INTEGER")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_candidate_user ON candidate(user_id) WHERE user_id IS NOT NULL")
    conn.commit()
    conn.close()


def get_or_create_skill(conn: sqlite3.Connection, skill_name: str, category: str = "General") -> int:
    cleaned_name = (skill_name or "").strip()
    if not cleaned_name:
        raise ValueError("Skill name is required")

    existing = conn.execute(
        "SELECT skill_id FROM skill WHERE LOWER(skill_name) = LOWER(?)",
        (cleaned_name,),
    ).fetchone()

    if existing:
        return existing["skill_id"]

    cursor = conn.execute(
        "INSERT INTO skill (skill_name, category) VALUES (?, ?)",
        (cleaned_name, category or "General"),
    )
    conn.commit()
    return int(cursor.lastrowid)


@router.get("/profile")
def get_profile(current_user=Depends(get_current_user)):
    conn = get_db()

    candidate = conn.execute(
        "SELECT * FROM candidate WHERE user_id = ? LIMIT 1",
        (current_user["user_id"],),
    ).fetchone()

    if not candidate:
        conn.close()
        raise HTTPException(
            status_code=404,
            detail="No CareerDNA profile is linked to this account. Please complete onboarding first.",
        )

    candidate_id = candidate["candidate_id"]

    education = conn.execute(
        "SELECT * FROM education WHERE candidate_id = ? ORDER BY end_date DESC, start_date DESC",
        (candidate_id,),
    ).fetchall()

    skills = conn.execute(
        """
        SELECT s.skill_name, cs.proficiency, cs.years, cs.evidence_score
        FROM candidate_skill cs
        JOIN skill s ON s.skill_id = cs.skill_id
        WHERE cs.candidate_id = ?
        ORDER BY cs.evidence_score DESC
        """,
        (candidate_id,),
    ).fetchall()

    projects = conn.execute(
        "SELECT * FROM project WHERE candidate_id = ? ORDER BY project_id DESC",
        (candidate_id,),
    ).fetchall()

    certifications = conn.execute(
        """
        SELECT c.name, c.issuer, cc.issue_date
        FROM candidate_certification cc
        JOIN certification c ON c.certification_id = cc.certification_id
        WHERE cc.candidate_id = ?
        ORDER BY cc.issue_date DESC
        """,
        (candidate_id,),
    ).fetchall()

    experience = conn.execute(
        "SELECT * FROM experience WHERE candidate_id = ? ORDER BY end_date DESC, start_date DESC",
        (candidate_id,),
    ).fetchall()

    version = conn.execute(
        "SELECT profile_snapshot FROM profile_version WHERE candidate_id = ? ORDER BY version_number DESC LIMIT 1",
        (candidate_id,),
    ).fetchone()

    conn.close()

    return {
        "candidate": dict(candidate),
        "profile_snapshot": json.loads(version["profile_snapshot"]) if version else {},
        "education": [dict(row) for row in education],
        "skills": [dict(row) for row in skills],
        "projects": [dict(row) for row in projects],
        "certifications": [dict(row) for row in certifications],
        "experience": [dict(row) for row in experience],
    }


@router.post("/profile/setup")
def setup_profile(data: ProfileSetupRequest, current_user=Depends(get_current_user)):
    name = (data.name or current_user.get("name") or "").strip()
    email = (data.email or current_user["email"]).lower().strip()
    location = (data.location or "").strip()

    if not name:
        raise HTTPException(status_code=400, detail="Name is required")

    conn = get_db()

    candidate = conn.execute(
        "SELECT * FROM candidate WHERE user_id = ? LIMIT 1",
        (current_user["user_id"],),
    ).fetchone()

    if candidate:
        candidate_id = candidate["candidate_id"]
        conn.execute(
            "UPDATE candidate SET name = ?, email = ?, location = ?, user_id = ? WHERE candidate_id = ?",
            (name, email, location, current_user["user_id"], candidate_id),
        )
    else:
        cursor = conn.execute(
            "INSERT INTO candidate (name, email, location, user_id) VALUES (?, ?, ?, ?)",
            (name, email, location, current_user["user_id"]),
        )
        candidate_id = int(cursor.lastrowid)

    conn.execute("DELETE FROM education WHERE candidate_id = ?", (candidate_id,))
    conn.execute("DELETE FROM experience WHERE candidate_id = ?", (candidate_id,))
    conn.execute("DELETE FROM project_skill WHERE project_id IN (SELECT project_id FROM project WHERE candidate_id = ?)", (candidate_id,))
    conn.execute("DELETE FROM project WHERE candidate_id = ?", (candidate_id,))
    conn.execute("DELETE FROM candidate_certification WHERE candidate_id = ?", (candidate_id,))
    conn.execute("DELETE FROM candidate_skill WHERE candidate_id = ?", (candidate_id,))

    for education in data.education:
        if not education.degree or not education.institution:
            continue
        conn.execute(
            """
            INSERT INTO education (candidate_id, degree, institution, field, cgpa, start_date, end_date)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                candidate_id,
                education.degree,
                education.institution,
                education.field or "",
                education.cgpa,
                education.start_date,
                education.end_date,
            ),
        )

    for experience in data.experience:
        if not experience.company or not experience.role:
            continue
        conn.execute(
            """
            INSERT INTO experience (candidate_id, company, role, domain, start_date, end_date)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                candidate_id,
                experience.company,
                experience.role,
                experience.domain or "",
                experience.start_date,
                experience.end_date,
            ),
        )

    for skill in data.skills:
        if not skill.name:
            continue
        skill_id = get_or_create_skill(conn, skill.name, skill.category or "General")
        conn.execute(
            """
            INSERT INTO candidate_skill (candidate_id, skill_id, proficiency, years, evidence_score, last_used)
            VALUES (?, ?, ?, ?, ?, date('now'))
            """,
            (
                candidate_id,
                skill_id,
                skill.proficiency or "Intermediate",
                float(skill.years or 0),
                float(skill.evidence_score or 0),
            ),
        )

    for project in data.projects:
        if not project.title:
            continue
        cursor = conn.execute(
            """
            INSERT INTO project (candidate_id, title, description, complexity, impact, solo, github_url)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                candidate_id,
                project.title,
                project.description or "",
                project.complexity or "Medium",
                project.impact or "Medium",
                int(bool(project.solo)),
                project.github_url or "",
            ),
        )
        project_id = int(cursor.lastrowid)

        for skill_name in project.skills:
            skill_id = get_or_create_skill(conn, skill_name, "Project")
            conn.execute(
                "INSERT OR IGNORE INTO project_skill (project_id, skill_id) VALUES (?, ?)",
                (project_id, skill_id),
            )

    for cert in data.certifications:
        if not cert.name:
            continue
        cert_row = conn.execute(
            "SELECT certification_id FROM certification WHERE LOWER(name) = LOWER(?) LIMIT 1",
            (cert.name,),
        ).fetchone()

        if cert_row:
            certification_id = cert_row["certification_id"]
        else:
            cursor = conn.execute(
                "INSERT INTO certification (name, issuer, domain, level) VALUES (?, ?, ?, ?)",
                (cert.name, cert.issuer or "", "General", "General"),
            )
            certification_id = int(cursor.lastrowid)

        conn.execute(
            "INSERT INTO candidate_certification (candidate_id, certification_id, issue_date, verification_status) VALUES (?, ?, ?, 'unverified')",
            (candidate_id, certification_id, cert.issue_date or None),
        )

    snapshot = {
        "name": name,
        "email": email,
        "location": location,
        "headline": data.headline or "",
        "goals": data.goals or "",
        "education": [education.model_dump() for education in data.education],
        "experience": [experience.model_dump() for experience in data.experience],
        "skills": [skill.model_dump() for skill in data.skills],
        "projects": [project.model_dump() for project in data.projects],
        "certifications": [cert.model_dump() for cert in data.certifications],
    }

    version_number = int(
        conn.execute(
            "SELECT COALESCE(MAX(version_number), 0) + 1 FROM profile_version WHERE candidate_id = ?",
            (candidate_id,),
        ).fetchone()[0]
    )

    conn.execute(
        "INSERT INTO profile_version (candidate_id, version_number, profile_snapshot) VALUES (?, ?, ?)",
        (candidate_id, version_number, json.dumps(snapshot)),
    )

    conn.commit()
    conn.close()

    return {
        "success": True,
        "candidate_id": candidate_id,
        "message": "Profile setup completed successfully.",
        "profile": {
            "id": candidate_id,
            "name": name,
            "email": email,
            "location": location,
        },
    }
