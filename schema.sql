-- CareerDNA: Evidence-Based Career Intelligence Database
-- Run with: sqlite3 careerdna.db < schema.sql   (or adapt types for PostgreSQL)

CREATE TABLE candidate (
    candidate_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id          INTEGER UNIQUE,
    name             TEXT NOT NULL,
    email            TEXT UNIQUE,
    location          TEXT,
    created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE education (
    education_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    candidate_id     INTEGER NOT NULL REFERENCES candidate(candidate_id),
    degree           TEXT NOT NULL,
    institution      TEXT NOT NULL,
    field            TEXT,
    cgpa             REAL,
    start_date       DATE,
    end_date         DATE
);

CREATE TABLE skill (
    skill_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    skill_name       TEXT UNIQUE NOT NULL,
    category         TEXT
);

CREATE TABLE candidate_skill (
    candidate_id     INTEGER NOT NULL REFERENCES candidate(candidate_id),
    skill_id         INTEGER NOT NULL REFERENCES skill(skill_id),
    proficiency      TEXT CHECK(proficiency IN ('Beginner','Intermediate','Advanced')),
    years            REAL DEFAULT 0,
    evidence_score   REAL DEFAULT 0,   -- 0-100, computed from projects/exp/certs
    last_used        DATE,
    PRIMARY KEY (candidate_id, skill_id)
);

CREATE TABLE project (
    project_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    candidate_id     INTEGER NOT NULL REFERENCES candidate(candidate_id),
    title            TEXT NOT NULL,
    description      TEXT,
    complexity       TEXT CHECK(complexity IN ('Low','Medium','High')),
    impact           TEXT CHECK(impact IN ('Low','Medium','High')),
    solo             BOOLEAN DEFAULT 0,
    github_url       TEXT
);

CREATE TABLE project_skill (
    project_id       INTEGER NOT NULL REFERENCES project(project_id),
    skill_id         INTEGER NOT NULL REFERENCES skill(skill_id),
    PRIMARY KEY (project_id, skill_id)
);

CREATE TABLE certification (
    certification_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name             TEXT NOT NULL,
    issuer           TEXT,
    domain           TEXT,
    level            TEXT
);

CREATE TABLE candidate_certification (
    candidate_id     INTEGER NOT NULL REFERENCES candidate(candidate_id),
    certification_id INTEGER NOT NULL REFERENCES certification(certification_id),
    issue_date       DATE,
    expiry_date      DATE,
    verification_status TEXT DEFAULT 'unverified',
    PRIMARY KEY (candidate_id, certification_id)
);

CREATE TABLE language (
    language_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    name             TEXT UNIQUE NOT NULL
);

CREATE TABLE candidate_language (
    candidate_id     INTEGER NOT NULL REFERENCES candidate(candidate_id),
    language_id      INTEGER NOT NULL REFERENCES language(language_id),
    proficiency      TEXT,
    PRIMARY KEY (candidate_id, language_id)
);

CREATE TABLE experience (
    experience_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    candidate_id     INTEGER NOT NULL REFERENCES candidate(candidate_id),
    company          TEXT NOT NULL,
    role             TEXT,
    domain           TEXT,
    start_date       DATE,
    end_date         DATE
);

CREATE TABLE job (
    job_id           INTEGER PRIMARY KEY AUTOINCREMENT,
    company          TEXT,
    role             TEXT NOT NULL,
    location         TEXT,
    min_salary       REAL,
    max_salary       REAL
);

CREATE TABLE job_skill (
    job_id           INTEGER NOT NULL REFERENCES job(job_id),
    skill_id         INTEGER NOT NULL REFERENCES skill(skill_id),
    required_level   TEXT CHECK(required_level IN ('Nice-to-have','Required','Critical')),
    importance       REAL DEFAULT 1.0,
    PRIMARY KEY (job_id, skill_id)
);

CREATE TABLE profile_version (
    version_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    candidate_id     INTEGER NOT NULL REFERENCES candidate(candidate_id),
    version_number   INTEGER NOT NULL,
    created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    profile_snapshot TEXT  -- JSON blob of profile state at this point in time
);

CREATE TABLE salary_prediction (
    prediction_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    candidate_id     INTEGER NOT NULL REFERENCES candidate(candidate_id),
    version_id       INTEGER REFERENCES profile_version(version_id),
    model_version    TEXT,
    predicted_salary REAL,
    lower_bound      REAL,
    upper_bound      REAL,
    confidence       REAL,
    timestamp        TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for the query-performance section of the report
CREATE INDEX idx_candidate_skill_candidate ON candidate_skill(candidate_id);
CREATE INDEX idx_project_candidate ON project(candidate_id);
CREATE INDEX idx_job_skill_skill ON job_skill(skill_id);
CREATE INDEX idx_salary_prediction_candidate ON salary_prediction(candidate_id);
