const API_BASE =
  import.meta.env.VITE_API_BASE || "http://127.0.0.1:8000";

// ============================================================
// COMMON REQUEST
// ============================================================

async function request(endpoint, options = {}) {
  const token = localStorage.getItem("careerdna_token");

  const headers = {
    "Content-Type": "application/json",
    ...(options.headers || {}),
  };

  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }

  const response = await fetch(`${API_BASE}${endpoint}`, {
    ...options,
    headers,
  });

  if (response.status === 401) {
    localStorage.removeItem("careerdna_token");
    localStorage.removeItem("careerdna_user");

    throw new Error(
      "Your session has expired. Please sign in again."
    );
  }

  if (!response.ok) {
    let message = `Request failed: ${response.status}`;

    try {
      const error = await response.json();

      if (error.detail) {
        message = error.detail;
      }
    } catch {
      // Ignore invalid JSON
    }

    throw new Error(message);
  }

  return response.json();
}

// ============================================================
// AUTH
// ============================================================

export async function login(email, password) {
  return request("/auth/login", {
    method: "POST",
    body: JSON.stringify({
      email,
      password,
    }),
  });
}

export async function register(name, email, password) {
  return request("/auth/register", {
    method: "POST",
    body: JSON.stringify({
      name,
      email,
      password,
    }),
  });
}

export async function getCurrentUser() {
  return request("/auth/me");
}

export function logout() {
  localStorage.removeItem("careerdna_token");
  localStorage.removeItem("careerdna_user");
}

// ============================================================
// PROFILE
// ============================================================

export async function getProfile() {
  return request("/profile");
}

export async function saveProfile(profile) {
  return request("/profile/setup", {
    method: "POST",
    body: JSON.stringify(profile),
  });
}

// ============================================================
// SKILLS
// ============================================================

export async function getSkills() {
  return request("/skill-strength");
}

// ============================================================
// SALARY
// ============================================================

export async function getSalary() {
  return request("/salary");
}

// ============================================================
// CAREER GAP
// ============================================================

export async function getCareerGap(role) {
  const query = role
    ? `?role=${encodeURIComponent(role)}`
    : "";

  return request(`/career-gap${query}`);
}

// ============================================================
// JOB MATCH
// ============================================================

export async function getJobMatch() {
  return request("/job-match");
}

// ============================================================
// CAREER HISTORY
// ============================================================

export async function getCareerHistory() {
  return request("/career-history");
}

// ============================================================
// WHAT IF
// ============================================================

export async function runWhatIf(changes) {
  return request("/salary/what-if", {
    method: "POST",
    body: JSON.stringify(changes),
  });
}

// ============================================================
// LOCAL AI ASSISTANT (Ollama)  -  all calls go to /ai/* on the CareerDNA backend
// ============================================================

export async function getAIStatus() {
  return request("/ai/status");
}

export async function aiChat(message, context) {
  return request("/ai/chat", {
    method: "POST",
    body: JSON.stringify({ message, context: context || null }),
  });
}

export async function getAIOptions() {
  return request("/ai/options");
}

export async function getAIEvidence() {
  return request("/ai/evidence");
}

export async function aiWhatIf(body) {
  return request("/ai/what-if", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function getAIRoadmap({ role, hoursPerWeek, weeks, explain }) {
  const q = new URLSearchParams();
  if (role) q.set("role", role);
  q.set("hours_per_week", String(hoursPerWeek));
  q.set("weeks", String(weeks));
  if (explain) q.set("explain", "true");
  return request(`/ai/roadmap?${q.toString()}`);
}

// ============================================================
// API BASE
// ============================================================

export {
  API_BASE,
};