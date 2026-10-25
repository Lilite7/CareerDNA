"""Small curated tables used by the roadmap and the router.
IMPORTANT: these are rules written in code, NOT database facts. They are labelled as such wherever shown."""

# skill -> skills that normally come first (planning aid only; never presented as a job requirement)
PREREQUISITES = {
    "PyTorch": ["Python", "Machine Learning"],
    "Deep Learning": ["Python", "Machine Learning"],
    "Machine Learning": ["Python"],
    "SIEM tools": ["Cybersecurity"],
    "Cloud Security": ["Cybersecurity"],
    "System Design": ["Python"],
    "FastAPI": ["Python"],
    "Docker": [],
}

# rough planning ranges in hours (low, high). Estimates, not promises.
EFFORT_HOURS = {
    "PyTorch": (30, 60), "Deep Learning": (60, 120), "Machine Learning": (60, 120),
    "Docker": (10, 25), "SIEM tools": (30, 60), "Cloud Security": (30, 70),
    "Cybersecurity": (80, 160), "System Design": (50, 100), "SQL": (20, 50),
    "Python": (40, 100), "FastAPI": (15, 35), "React": (40, 90), "AWS": (30, 70),
}
DEFAULT_EFFORT = (30, 80)

# words that do not identify a role on their own
GENERIC_ROLE_WORDS = {"engineer", "analyst", "developer", "the", "and", "of", "for"}
ROLE_EXTRA_ALIASES = {"backend / sde": ["backend", "sde", "software engineer", "software development", "software developer"],
                      "ml engineer": ["ml", "machine learning engineer", "ai/ml", "ai engineer"],
                      "cybersecurity analyst": ["cybersecurity", "cyber security", "security analyst", "infosec", "information security"]}
SKILL_ALIASES = {"ml": "Machine Learning", "dl": "Deep Learning", "scikit learn": "scikit-learn",
                 "sklearn": "scikit-learn", "cyber security": "Cybersecurity", "siem": "SIEM tools",
                 "pytorch": "PyTorch", "torch": "PyTorch"}
