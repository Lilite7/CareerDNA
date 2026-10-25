"""
Train the salary prediction model from careerdna.db candidate_skill evidence data.
pip install scikit-learn pandas joblib --break-system-packages
"""
import sqlite3
import pandas as pd
from sklearn.linear_model import LinearRegression
from sklearn.ensemble import RandomForestRegressor
from sklearn.model_selection import train_test_split
from sklearn.metrics import r2_score, mean_absolute_error
import joblib

conn = sqlite3.connect("careerdna.db")

df = pd.read_sql_query("""
    SELECT cs.candidate_id,
           COUNT(DISTINCT cs.skill_id)                AS n_skills,
           AVG(cs.evidence_score)                      AS avg_evidence,
           SUM(cs.years)                                AS total_years
    FROM candidate_skill cs
    JOIN candidate c ON c.candidate_id = cs.candidate_id
    WHERE c.name LIKE 'synthetic_%'
    GROUP BY cs.candidate_id
""", conn)

# Synthetic target: salary correlated with evidence + skill breadth + noise (stand-in for
# real market data — swap in a licensed salary dataset for the coursework submission).
import numpy as np
rng = np.random.default_rng(42)
df["salary_lpa"] = (
    6 + df["avg_evidence"] * 0.09 + df["n_skills"] * 0.35 + df["total_years"] * 0.4
    + rng.normal(0, 1.2, len(df))
).clip(lower=4)

X = df[["n_skills", "avg_evidence", "total_years"]]
y = df["salary_lpa"]
X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

models = {
    "LinearRegression": LinearRegression(),
    "RandomForest": RandomForestRegressor(n_estimators=200, random_state=42),
}

best_name, best_model, best_r2 = None, None, -1e9
for name, model in models.items():
    model.fit(X_train, y_train)
    preds = model.predict(X_test)
    r2 = r2_score(y_test, preds)
    mae = mean_absolute_error(y_test, preds)
    print(f"{name:18s} R2={r2:.3f}  MAE={mae:.2f} LPA")
    if r2 > best_r2:
        best_name, best_model, best_r2 = name, model, r2

print(f"\nSelected model: {best_name} (R2={best_r2:.3f})")
joblib.dump(best_model, "salary_model.joblib")
print("Saved to salary_model.joblib — load this in main.py to replace the rule-based simulator.")
