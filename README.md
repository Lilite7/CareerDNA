# CareerDNA — Evidence-Based Career Intelligence Database

## What's here
- `schema.sql` — full relational schema (candidate, skill, project, certification, job,
  profile_version, salary_prediction, plus junction tables + indexes)
- `seed_data.py` — loads your real profile (VIT Vellore, AI-SOC, AI Hiring Assistant, JPL
  internship) plus 300 synthetic peer candidates and 3 sample job postings
- `train_model.py` — trains Linear Regression vs Random Forest on the seeded evidence
  scores, prints R²/MAE, saves the winning model
- `main.py` — FastAPI service: profile, skill-strength, career-gap, job-match, and
  salary what-if endpoints

## Run it
```bash
pip install fastapi uvicorn scikit-learn pandas joblib --break-system-packages
sqlite3 careerdna.db < schema.sql
python seed_data.py
python train_model.py          # optional — for the ML comparison section of your report
uvicorn main:app --reload
```
Then hit `http://localhost:8000/candidates/1/profile`, `/skill-strength`,
`/jobs/match`, etc. (candidate_id 1 is Nishita's real seeded profile).

## For the DBMS report
Report on schema normalization (3NF), the ER diagram (candidate as the hub entity,
skill/project/job as many-to-many via junction tables), and query performance
before/after the indexes in `schema.sql` — that's the actual DBMS contribution described
in the CareerDNA proposal. The ML piece is intentionally swappable/secondary.

## Live UI demo
`CareerDNA.jsx` (the artifact shared alongside this) is a standalone, already-populated
dashboard — Career DNA helix, skill-strength bars, salary forecast, what-if simulator,
career-gap radar, and a salary time machine — built with your real project data so you
can see the finished product without wiring up the API first. Point its fetch calls at
`main.py`'s endpoints when you're ready to make it live.


## Local AI assistant
See AI_README.md (Ollama + Qwen2.5, evidence-checked answers, What-If, roadmap).
