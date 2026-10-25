"""Deterministic synthetic database used by the automated tests and the evaluation harness.
It contains NO real personal data. Built from the project's own schema.sql plus a fixed catalog/jobs seed."""
import json
import os
import sqlite3

from .db import BASE_DIR

SKILLS = [(1, "Python", "Programming"), (2, "SQL", "Data"), (3, "FastAPI", "Backend"), (4, "React", "Frontend"),
          (5, "Machine Learning", "AI/ML"), (6, "Cybersecurity", "Security"), (7, "Docker", "DevOps"), (8, "AWS", "Cloud"),
          (9, "System Design", "Backend"), (10, "Deep Learning", "AI/ML"), (11, "PyTorch", "AI/ML"),
          (12, "Cloud Security", "Security"), (13, "SIEM tools", "Security")]
JOBS = [(1, "Acme AI", "ML Engineer", "Bengaluru", 10.0, 22.0), (2, "SecureNet", "Cybersecurity Analyst", "Pune", 8.0, 16.0),
        (3, "BuildStack", "Backend / SDE", "Hyderabad", 9.0, 20.0)]
JOB_SKILLS = [(1, 1, "Critical", 1.5), (1, 5, "Critical", 1.5), (1, 10, "Required", 1.2), (1, 11, "Required", 1.2), (1, 7, "Required", 1.0),
              (2, 6, "Critical", 1.5), (2, 1, "Required", 1.0), (2, 13, "Critical", 1.3), (2, 12, "Required", 1.0),
              (3, 1, "Critical", 1.4), (3, 2, "Required", 1.1), (3, 9, "Critical", 1.3), (3, 7, "Required", 1.0), (3, 3, "Nice-to-have", 0.6)]

ADA = 10   # candidate with a rich profile (user 1)
BOB = 11   # a different user's candidate (user 2) - used to prove data isolation
SECRET_PROJECT = "Bob Confidential Payroll Engine"


def build_fixture_db(path: str) -> str:
    if os.path.exists(path):
        os.remove(path)
    conn = sqlite3.connect(path)
    with open(os.path.join(BASE_DIR, "schema.sql"), encoding="utf-8") as f:
        conn.executescript(f.read())
    conn.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, email TEXT NOT NULL UNIQUE, "
                 "password_hash TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP)")
    conn.executemany("INSERT INTO skill VALUES (?,?,?)", SKILLS)
    conn.executemany("INSERT INTO job VALUES (?,?,?,?,?,?)", JOBS)
    conn.executemany("INSERT INTO job_skill VALUES (?,?,?,?)", JOB_SKILLS)
    conn.executemany("INSERT INTO users (id,name,email,password_hash) VALUES (?,?,?,?)",
                     [(1, "Ada Test", "ada@example.test", "x"), (2, "Bob Other", "bob@example.test", "x"), (3, "Cy Empty", "cy@example.test", "x")])
    conn.execute("INSERT INTO candidate (candidate_id,user_id,name,email,location) VALUES (?,?,?,?,?)", (ADA, 1, "Ada Test", "ada@example.test", "Pune"))
    conn.execute("INSERT INTO candidate (candidate_id,user_id,name,email,location) VALUES (?,?,?,?,?)", (BOB, 2, "Bob Other", "bob@example.test", "Delhi"))
    skills = [(1, "Advanced", 3.0, 91), (2, "Advanced", 2.0, 82), (3, "Advanced", 1.9, 78), (4, "Intermediate", 1.7, 68),
              (5, "Intermediate", 1.9, 74), (6, "Intermediate", 1.8, 71), (7, "Intermediate", 0.8, 33),
              (8, "Intermediate", 0.6, 24), (10, "Advanced", 3.0, 12)]   # Deep Learning: 'Advanced' but evidence 12/100 -> contradictory
    conn.executemany("INSERT INTO candidate_skill (candidate_id,skill_id,proficiency,years,evidence_score) VALUES (?,?,?,?,?)", [(ADA, *s) for s in skills])
    conn.execute("INSERT INTO project (project_id,candidate_id,title,description,complexity,impact,solo) VALUES (1,?,?,?,?,?,1)",
                 (ADA, "AI-SOC Platform", "Defensive security monitoring tool that classifies threats from synthetic logs using scikit-learn.", "High", "High"))
    conn.execute("INSERT INTO project (project_id,candidate_id,title,description,complexity,impact,solo) VALUES (2,?,?,?,?,?,1)",
                 (ADA, "AI Hiring Assistant", "Salary prediction and candidate shortlisting web app built with FastAPI and React.", "High", "High"))
    conn.executemany("INSERT INTO project_skill VALUES (?,?)", [(1, 1), (1, 3), (1, 5), (1, 6), (2, 1), (2, 3), (2, 4), (2, 5), (2, 2)])
    conn.execute("INSERT INTO certification (certification_id,name,issuer,domain,level) VALUES (1,'AWS Cloud Practitioner','Amazon','Cloud','Foundational')")
    conn.execute("INSERT INTO candidate_certification (candidate_id,certification_id,issue_date,verification_status) VALUES (?,1,'2025-11-01','unverified')", (ADA,))
    conn.execute("INSERT INTO experience (candidate_id,company,role,domain,start_date,end_date) VALUES (?,?,?,?,?,?)",
                 (ADA, "Acme Labs", "ML Intern", "AI/ML", "2025-05-01", "2025-07-01"))
    conn.execute("INSERT INTO education (candidate_id,degree,institution,field,cgpa) VALUES (?,?,?,?,?)", (ADA, "B.Tech", "Test Institute", "Computer Science", 8.4))
    snap = {"headline": "Final-year CS student | AI/ML and cybersecurity",
            "goals": "I want to become a machine learning engineer and also explore cybersecurity roles."}
    conn.execute("INSERT INTO profile_version (candidate_id,version_number,profile_snapshot) VALUES (?,1,?)", (ADA, json.dumps(snap)))
    # Bob: different data that must never appear in Ada's answers
    conn.executemany("INSERT INTO candidate_skill (candidate_id,skill_id,proficiency,years,evidence_score) VALUES (?,?,?,?,?)",
                     [(BOB, 1, "Advanced", 5.0, 95), (BOB, 9, "Advanced", 4.0, 90)])
    conn.execute("INSERT INTO project (project_id,candidate_id,title,description,complexity,impact,solo) VALUES (3,?,?,?,?,?,1)",
                 (BOB, SECRET_PROJECT, "Confidential payroll processing.", "High", "High"))
    conn.execute("INSERT INTO project_skill VALUES (3,1)")
    conn.commit()
    conn.close()
    return path
