"""SYNTHETIC evaluation corpus (richer than ai/eval_fixture.py). Every person, project and description below is invented
for testing retrieval. It contains no real data and is kept separate from the small fixture and from your real database.
Contains one evaluated candidate (Rhea, user 4) plus distractor candidates whose records overlap in topic, to stress isolation."""
import json
import os
import sqlite3

from .db import BASE_DIR
from .eval_fixture import JOB_SKILLS, JOBS, SKILLS

RICH_USER, RICH_CANDIDATE = 4, 20
SKILL_ID = {name: sid for sid, name, _ in SKILLS}

PROJECTS = [  # (project_id, title, description, [skills])
    (100, "Crop Yield Forecaster", "Predicts harvest quantities for small farms from rainfall, soil and satellite imagery using gradient boosting; deployed as a REST service.", ["Python", "Machine Learning", "FastAPI"]),
    (101, "Campus Chatbot", "A conversational assistant that answers student questions about timetables and hostels by looking things up in university documents.", ["Python", "Machine Learning"]),
    (102, "Phishing Email Detector", "Classifier that flags fraudulent emails and malicious links by analysing headers, URLs and message wording.", ["Python", "Machine Learning", "Cybersecurity"]),
    (103, "Intrusion Alert Dashboard", "Streams firewall and network traffic logs, highlights suspicious connections and ranks alerts by severity for analysts.", ["Python", "Cybersecurity", "React", "SQL"]),
    (104, "Expense Splitter App", "Mobile-friendly web app where roommates record shared spending and settle who owes whom.", ["React", "FastAPI", "SQL"]),
    (105, "Medical Image Triage", "Convolutional neural network that sorts chest X-ray scans by urgency to help radiologists prioritise their work.", ["Python", "Deep Learning", "PyTorch"]),
    (106, "Container Deploy Pipeline", "Automates building, testing and shipping services into isolated containers with a continuous integration workflow.", ["Docker", "Python"]),
    (107, "Library Database Redesign", "Normalised relational schema and optimised queries for a college library's lending records.", ["SQL"]),
    (108, "Traffic Sign Recognizer", "Deep learning model that identifies road signs from dashcam frames in real time.", ["Deep Learning", "PyTorch", "Python"]),
    (109, "Resume Screener", "Ranks job applicants against a vacancy by matching their experience to required abilities and explains the ranking.", ["Python", "Machine Learning", "FastAPI"]),
    (110, "Cloud Cost Monitor", "Tracks spending across hosted infrastructure accounts and warns when budgets are about to be exceeded.", ["AWS", "Python"]),
    (111, "Password Vault Audit", "Reviews stored credentials for reuse and weakness, and checks them against known breach lists.", ["Cybersecurity", "Python"]),
]
EXPERIENCE = [(100, "Synthetic Analytics", "ML Intern", "AI/ML", "2025-05-01", "2025-07-15"), (101, "Synthetic CyberWorks", "Security Intern", "Cybersecurity", "2025-08-01", "2025-09-30"),
              (102, "Freelance", "Web Developer", "Web development", "2024-01-01", "2024-12-31"), (103, "Synthetic University", "Teaching Assistant", "Data structures", "2024-08-01", "2025-04-30")]
CERTS = [(100, "AWS Cloud Practitioner", "Amazon", "Cloud"), (101, "CompTIA Security+", "CompTIA", "Cybersecurity"),
         (102, "Deep Learning Specialization", "Synthetic Academy", "AI/ML"), (103, "Docker Certified Associate", "Docker", "DevOps")]
DISTRACTORS = [  # other candidates whose records overlap in topic with Rhea's; none of this may ever appear in Rhea's results
    (21, 5, "Synthetic Distractor One", [(120, "Network Intrusion Detection System", "Detects anomalous traffic and attacks in enterprise networks.", ["Cybersecurity", "Python"]),
                                         (121, "Wage Predictor", "Forecasts salaries for job seekers from market data.", ["Python", "Machine Learning"])]),
    (22, 6, "Synthetic Distractor Two", [(122, "Hospital Billing Engine", "Confidential invoice processing for clinics and medical image archives.", ["SQL", "Deep Learning"])]),
]


def build_rich_fixture_db(path: str) -> str:
    if os.path.exists(path):
        os.remove(path)
    conn = sqlite3.connect(path)
    with open(os.path.join(BASE_DIR, "schema.sql"), encoding="utf-8") as f:
        conn.executescript(f.read())
    conn.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, email TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP)")
    conn.executemany("INSERT INTO skill VALUES (?,?,?)", SKILLS)
    conn.executemany("INSERT INTO job VALUES (?,?,?,?,?,?)", JOBS)
    conn.executemany("INSERT INTO job_skill VALUES (?,?,?,?)", JOB_SKILLS)

    def person(cid, uid, name, projects):
        conn.execute("INSERT INTO users (id,name,email,password_hash) VALUES (?,?,?,'x')", (uid, name, f"u{uid}@example.test"))
        conn.execute("INSERT INTO candidate (candidate_id,user_id,name,email,location) VALUES (?,?,?,?,'Synthetic City')", (cid, uid, name, f"u{uid}@example.test"))
        for pid, title, desc, skills in projects:
            conn.execute("INSERT INTO project (project_id,candidate_id,title,description,complexity,impact,solo) VALUES (?,?,?,?,'Medium','Medium',1)", (pid, cid, title, desc))
            conn.executemany("INSERT INTO project_skill VALUES (?,?)", [(pid, SKILL_ID[s]) for s in skills])
        for s in {s for *_, sk in projects for s in sk}:
            conn.execute("INSERT INTO candidate_skill (candidate_id,skill_id,proficiency,years,evidence_score) VALUES (?,?,'Intermediate',1,60)", (cid, SKILL_ID[s]))

    person(RICH_CANDIDATE, RICH_USER, "SYNTHETIC Rhea Rich", PROJECTS)
    for e in EXPERIENCE:
        conn.execute("INSERT INTO experience (experience_id,candidate_id,company,role,domain,start_date,end_date) VALUES (?,?,?,?,?,?,?)", (e[0], RICH_CANDIDATE, *e[1:]))
    for cid_, name, issuer, domain in CERTS:
        conn.execute("INSERT INTO certification (certification_id,name,issuer,domain,level) VALUES (?,?,?,?,'Foundational')", (cid_, name, issuer, domain))
        conn.execute("INSERT INTO candidate_certification (candidate_id,certification_id,issue_date,verification_status) VALUES (?,?,'2025-10-01','unverified')", (RICH_CANDIDATE, cid_))
    conn.execute("INSERT INTO profile_version (candidate_id,version_number,profile_snapshot) VALUES (?,1,?)",
                 (RICH_CANDIDATE, json.dumps({"headline": "Aspiring machine learning and security engineer", "goals": "Looking for roles that combine applied AI with defending systems."})))
    for cid, uid, name, projects in DISTRACTORS:
        person(cid, uid, name, projects)
    conn.commit()
    conn.close()
    return path
