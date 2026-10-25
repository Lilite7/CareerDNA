"""Seed careerdna.db with a real profile (Nishita) + synthetic candidates/jobs for training data."""
import sqlite3, random, json
from datetime import date
import sqlite3

DB_NAME = "careerdna.db"

conn = sqlite3.connect(DB_NAME)

conn = sqlite3.connect("careerdna.db")
c = conn.cursor()
random.seed(42)

def get_or_create_skill(name, category):
    c.execute("INSERT OR IGNORE INTO skill (skill_name, category) VALUES (?,?)", (name, category))
    return c.execute("SELECT skill_id FROM skill WHERE skill_name=?", (name,)).fetchone()[0]

SKILLS = [
    ("Python", "Programming"), ("SQL", "Data"), ("FastAPI", "Backend"),
    ("React", "Frontend"), ("Machine Learning", "AI/ML"), ("Cybersecurity", "Security"),
    ("Docker", "DevOps"), ("AWS", "Cloud"), ("System Design", "Backend"),
    ("Deep Learning", "AI/ML"), ("PyTorch", "AI/ML"), ("Cloud Security", "Security"),
    ("SIEM tools", "Security"),
]
skill_ids = {name: get_or_create_skill(name, cat) for name, cat in SKILLS}

# --- Real candidate: Nishita ---
c.execute("INSERT INTO candidate (name, email, location) VALUES (?,?,?)",
          ("Nishita", "nishita@example.com", "Mumbai, India"))
cand_id = c.lastrowid

c.execute("""INSERT INTO education (candidate_id, degree, institution, field, cgpa, start_date)
             VALUES (?,?,?,?,?,?)""",
          (cand_id, "B.Tech", "VIT Vellore", "Computer Science", 8.7, "2023-07-01"))

c.execute("""INSERT INTO experience (candidate_id, company, role, domain, start_date, end_date)
             VALUES (?,?,?,?,?,?)""",
          (cand_id, "Reliance Jio Platforms Limited", "Intern", "AI/ML & Cybersecurity",
           "2026-05-01", "2026-06-01"))

projects = [
    ("AI-SOC Platform", "Defensive cybersecurity monitoring tool", "High", "High", 1,
     "github.com/nishitakunta/SOC", ["Python", "FastAPI", "Machine Learning", "Cybersecurity"]),
    ("AI Hiring Assistant", "Salary prediction & candidate shortlisting", "High", "High", 1,
     "github.com/nishitakunta/ai-hiring-assistant", ["Python", "FastAPI", "React", "Machine Learning", "SQL"]),
    ("Hospital Navigation System", "Pathfinding for hospital wayfinding", "Medium", "Medium", 0, "", ["Python"]),
    ("BloodBank", "Blood donation management system", "Low", "Low", 0, "", ["SQL"]),
]
for title, desc, complexity, impact, solo, url, skills in projects:
    c.execute("""INSERT INTO project (candidate_id, title, description, complexity, impact, solo, github_url)
                 VALUES (?,?,?,?,?,?,?)""", (cand_id, title, desc, complexity, impact, solo, url))
    pid = c.lastrowid
    for s in skills:
        c.execute("INSERT OR IGNORE INTO project_skill (project_id, skill_id) VALUES (?,?)",
                   (pid, skill_ids[s]))

# candidate_skill with computed-ish evidence scores
evidence = {"Python": 91, "SQL": 82, "FastAPI": 78, "React": 68, "Machine Learning": 74,
            "Cybersecurity": 71, "Docker": 33, "AWS": 24}
for name, score in evidence.items():
    c.execute("""INSERT INTO candidate_skill (candidate_id, skill_id, proficiency, years, evidence_score, last_used)
                 VALUES (?,?,?,?,?,?)""",
              (cand_id, skill_ids[name], "Advanced" if score > 75 else "Intermediate",
               round(score / 40, 1), score, "2026-07-01"))

# --- Jobs ---
JOBS = [
    ("Acme AI", "ML Engineer", "Bengaluru", 10, 22,
     [("Python", "Critical", 1.5), ("Machine Learning", "Critical", 1.5), ("Deep Learning", "Required", 1.2),
      ("PyTorch", "Required", 1.2), ("Docker", "Required", 1.0)]),
    ("SecureNet", "Cybersecurity Analyst", "Pune", 8, 16,
     [("Cybersecurity", "Critical", 1.5), ("Python", "Required", 1.0),
      ("SIEM tools", "Critical", 1.3), ("Cloud Security", "Required", 1.0)]),
    ("BuildStack", "Backend / SDE", "Hyderabad", 9, 20,
     [("Python", "Critical", 1.4), ("SQL", "Required", 1.1), ("System Design", "Critical", 1.3),
      ("Docker", "Required", 1.0), ("FastAPI", "Nice-to-have", 0.6)]),
]
for company, role, loc, lo, hi, reqs in JOBS:
    c.execute("INSERT INTO job (company, role, location, min_salary, max_salary) VALUES (?,?,?,?,?)",
              (company, role, loc, lo, hi))
    jid = c.lastrowid
    for sname, level, importance in reqs:
        c.execute("INSERT INTO job_skill (job_id, skill_id, required_level, importance) VALUES (?,?,?,?)",
                  (jid, skill_ids[sname], level, importance))

# --- Synthetic peer candidates for model training (kept separate from real profile) ---
for i in range(300):
    name = f"synthetic_{i}"
    c.execute("INSERT INTO candidate (name, email) VALUES (?,?)", (name, f"{name}@synthetic.local"))
    sid = c.lastrowid
    n_skills = random.randint(2, 8)
    for s in random.sample(list(skill_ids.values()), n_skills):
        c.execute("""INSERT INTO candidate_skill (candidate_id, skill_id, proficiency, years, evidence_score)
                     VALUES (?,?,?,?,?)""",
                  (sid, s, random.choice(["Beginner", "Intermediate", "Advanced"]),
                   round(random.uniform(0, 4), 1), round(random.uniform(10, 95), 1)))

conn.commit()
conn.close()
print("Seeded careerdna.db")
