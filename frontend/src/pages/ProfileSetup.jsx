import React, { useEffect, useMemo, useState } from "react";
import { getProfile, logout, saveProfile } from "../api";

const C = {
  page: "#F7F8FA",
  white: "#FFFFFF",
  border: "#E4E8EE",
  text: "#18263A",
  text2: "#44536A",
  muted: "#7A8798",
  blue: "#3868A3",
  blueDark: "#284D7A",
  blueSoft: "#EEF3F9",
  green: "#2F8F75",
  red: "#C56B6B",
};

const inputStyle = {
  width: "100%",
  boxSizing: "border-box",
  border: `1px solid ${C.border}`,
  borderRadius: 8,
  padding: "11px 12px",
  fontSize: 13,
  color: C.text,
  background: C.white,
  outline: "none",
};

const labelStyle = {
  display: "block",
  fontSize: 10,
  fontWeight: 700,
  color: C.muted,
  letterSpacing: "0.8px",
  textTransform: "uppercase",
  marginBottom: 8,
};

const emptyEducation = () => ({
  degree: "",
  institution: "",
  field: "",
  cgpa: "",
  start_date: "",
  end_date: "",
});

const emptyExperience = () => ({
  company: "",
  role: "",
  domain: "",
  start_date: "",
  end_date: "",
});

const emptySkill = () => ({
  name: "",
  category: "General",
  proficiency: "Intermediate",
  years: "",
  evidence_score: "",
});

const emptyProject = () => ({
  title: "",
  description: "",
  complexity: "Medium",
  impact: "Medium",
  solo: true,
  github_url: "",
  skills: "",
});

const emptyCert = () => ({
  name: "",
  issuer: "",
  issue_date: "",
});

export default function ProfileSetup({ user, mode = "setup", onComplete, onCancel, onBackToLogin }) {
  const [step, setStep] = useState(1);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [profile, setProfile] = useState({
    name: user?.name || "",
    email: user?.email || "",
    location: "",
    headline: "",
    goals: "",
  });
  const [education, setEducation] = useState([emptyEducation()]);
  const [experience, setExperience] = useState([emptyExperience()]);
  const [skills, setSkills] = useState([emptySkill()]);
  const [projects, setProjects] = useState([emptyProject()]);
  const [certifications, setCertifications] = useState([emptyCert()]);

  const totalSteps = 4;

  const progress = useMemo(() => Math.round((step / totalSteps) * 100), [step]);

  useEffect(() => {
    let cancelled = false;

    async function loadSavedProfile() {
      try {
        const saved = await getProfile();
        if (cancelled) return;
        const candidate = saved.candidate || {};
        const snapshot = saved.profile_snapshot || {};
        setProfile({
          name: candidate.name || user?.name || "",
          email: candidate.email || user?.email || "",
          location: candidate.location || "",
          headline: snapshot.headline || "",
          goals: snapshot.goals || "",
        });
        setEducation(saved.education?.length ? saved.education : [emptyEducation()]);
        setExperience(saved.experience?.length ? saved.experience : [emptyExperience()]);
        setSkills(saved.skills?.length ? saved.skills.map((item) => ({
          ...item,
          name: item.name || item.skill_name || "",
          years: item.years ?? "",
          evidence_score: item.evidence_score ?? "",
        })) : [emptySkill()]);
        setProjects(saved.projects?.length ? saved.projects.map((item) => ({
          ...item,
          skills: Array.isArray(item.skills) ? item.skills.join(", ") : item.skills || "",
          solo: Boolean(item.solo),
        })) : [emptyProject()]);
        setCertifications(saved.certifications?.length ? saved.certifications : [emptyCert()]);
      } catch (loadError) {
        if (!loadError.message.includes("No CareerDNA profile") && !loadError.message.includes("404")) {
          setError(loadError.message || "Unable to load your saved profile.");
        }
      }
    }

    loadSavedProfile();
    return () => { cancelled = true; };
  }, [user]);

  function updateField(section, index, key, value) {
    if (section === "education") {
      setEducation((prev) => prev.map((item, idx) => (idx === index ? { ...item, [key]: value } : item)));
    }
    if (section === "experience") {
      setExperience((prev) => prev.map((item, idx) => (idx === index ? { ...item, [key]: value } : item)));
    }
    if (section === "skills") {
      setSkills((prev) => prev.map((item, idx) => (idx === index ? { ...item, [key]: value } : item)));
    }
    if (section === "projects") {
      setProjects((prev) => prev.map((item, idx) => (idx === index ? { ...item, [key]: value } : item)));
    }
    if (section === "certifications") {
      setCertifications((prev) => prev.map((item, idx) => (idx === index ? { ...item, [key]: value } : item)));
    }
  }

  function addItem(section) {
    if (section === "education") setEducation((prev) => [...prev, emptyEducation()]);
    if (section === "experience") setExperience((prev) => [...prev, emptyExperience()]);
    if (section === "skills") setSkills((prev) => [...prev, emptySkill()]);
    if (section === "projects") setProjects((prev) => [...prev, emptyProject()]);
    if (section === "certifications") setCertifications((prev) => [...prev, emptyCert()]);
  }

  function removeItem(section, index) {
    if (section === "education") setEducation((prev) => prev.filter((_, idx) => idx !== index));
    if (section === "experience") setExperience((prev) => prev.filter((_, idx) => idx !== index));
    if (section === "skills") setSkills((prev) => prev.filter((_, idx) => idx !== index));
    if (section === "projects") setProjects((prev) => prev.filter((_, idx) => idx !== index));
    if (section === "certifications") setCertifications((prev) => prev.filter((_, idx) => idx !== index));
  }

  function buildPayload() {
    return {
      name: profile.name,
      email: profile.email,
      location: profile.location,
      headline: profile.headline,
      goals: profile.goals,
      education: education.filter((item) => item.degree || item.institution),
      experience: experience.filter((item) => item.company || item.role),
      skills: skills.filter((item) => item.name).map((item) => ({ ...item, years: Number(item.years || 0), evidence_score: Number(item.evidence_score || 0) })),
      projects: projects.filter((item) => item.title).map((item) => ({ ...item, skills: (item.skills || "").split(",").map((skill) => skill.trim()).filter(Boolean), solo: Boolean(item.solo) })),
      certifications: certifications.filter((item) => item.name),
    };
  }

  async function saveCurrentStep() {
    setError("");
    setLoading(true);

    try {
      await saveProfile(buildPayload());
      return true;
    } catch (err) {
      console.error(err);
      setError(err.message || "Unable to save your profile.");
      return false;
    } finally {
      setLoading(false);
    }
  }

  async function nextStep() {
    const saved = await saveCurrentStep();
    if (saved) setStep((current) => Math.min(current + 1, totalSteps));
  }

  const prevStep = () => setStep((current) => Math.max(current - 1, 1));

  async function handleSubmit() {
    const saved = await saveCurrentStep();
    if (saved && onComplete) onComplete();
  }

  async function handleExit() {
    if (onBackToLogin) {
      await onBackToLogin();
    } else {
      logout();
    }
  }

  return (
    <div style={{ minHeight: "100vh", background: C.page, display: "flex", alignItems: "center", justifyContent: "center", padding: 24, fontFamily: "Inter, Arial, sans-serif" }}>
      <div style={{ width: "100%", maxWidth: 980, background: C.white, border: `1px solid ${C.border}`, borderRadius: 16, boxShadow: "0 10px 30px rgba(31,50,75,.07)" }}>
        <div style={{ padding: "24px 28px 0" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 16 }}>
            <div>
              <div style={{ fontSize: 26, fontWeight: 800, color: C.blueDark }}>CareerDNA</div>
              <div style={{ fontSize: 12, color: C.muted, marginTop: 4 }}>Complete your profile to unlock analysis</div>
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 18 }}>
              {mode === "edit" ? (
                <button type="button" onClick={onCancel} style={{ border: 0, background: "transparent", color: C.text2, fontWeight: 700, cursor: "pointer" }}>Cancel</button>
              ) : (
                <button type="button" onClick={handleExit} style={{ border: 0, background: "transparent", color: C.blueDark, fontWeight: 700, cursor: "pointer" }}>← Back to Login</button>
              )}
              <div style={{ fontSize: 12, color: C.muted, fontWeight: 700 }}>{step}/{totalSteps}</div>
            </div>
          </div>
          <div style={{ marginTop: 18, height: 8, background: "#EDF1F6", borderRadius: 999, overflow: "hidden" }}>
            <div style={{ height: "100%", width: `${progress}%`, background: C.blueDark, borderRadius: 999 }} />
          </div>
        </div>

        <div style={{ padding: "28px" }}>
          {error && (
            <div style={{ background: "#FFF4F4", border: `1px solid ${C.red}`, color: C.red, borderRadius: 8, padding: "10px 12px", fontSize: 12, marginBottom: 18 }}>
              {error}
            </div>
          )}

          {step === 1 && (
            <div>
              <h2 style={{ margin: "0 0 14px", color: C.text, fontSize: 30 }}>{mode === "edit" ? "Update your profile" : "Let’s build your profile"}</h2>
              <p style={{ margin: "0 0 24px", color: C.muted, fontSize: 14 }}>{mode === "edit" ? "Keep your CareerDNA evidence current so your analysis stays useful." : "Tell us about yourself so CareerDNA can compare your story against market-fit roles."}</p>

              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: 18 }}>
                <div>
                  <label style={labelStyle}>Full name</label>
                  <input value={profile.name} onChange={(e) => setProfile({ ...profile, name: e.target.value })} style={inputStyle} />
                </div>
                <div>
                  <label style={labelStyle}>Email</label>
                  <input value={profile.email} onChange={(e) => setProfile({ ...profile, email: e.target.value })} style={inputStyle} />
                </div>
                <div>
                  <label style={labelStyle}>Location</label>
                  <input value={profile.location} onChange={(e) => setProfile({ ...profile, location: e.target.value })} style={inputStyle} placeholder="e.g. Bengaluru, India" />
                </div>
                <div style={{ gridColumn: "1 / -1" }}>
                  <label style={labelStyle}>Headline</label>
                  <input value={profile.headline} onChange={(e) => setProfile({ ...profile, headline: e.target.value })} style={inputStyle} placeholder="AI engineer with data & product thinking" />
                </div>
                <div style={{ gridColumn: "1 / -1" }}>
                  <label style={labelStyle}>Career goals</label>
                  <textarea value={profile.goals} onChange={(e) => setProfile({ ...profile, goals: e.target.value })} style={{ ...inputStyle, minHeight: 100, resize: "vertical" }} placeholder="What roles do you want to target next?" />
                </div>
              </div>
            </div>
          )}

          {step === 2 && (
            <div>
              <h2 style={{ margin: "0 0 20px", color: C.text, fontSize: 26 }}>Education</h2>
              {education.map((item, index) => (
                <div key={`education-${index}`} style={{ border: `1px solid ${C.border}`, borderRadius: 12, padding: 16, marginBottom: 16, background: "#FBFCFE" }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
                    <div style={{ fontWeight: 700, color: C.text2 }}>Education #{index + 1}</div>
                    {education.length > 1 && (
                      <button type="button" onClick={() => removeItem("education", index)} style={{ border: 0, background: "transparent", color: C.red, fontWeight: 700, cursor: "pointer" }}>Remove</button>
                    )}
                  </div>
                  <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: 12 }}>
                    <div><label style={labelStyle}>Degree</label><input value={item.degree} onChange={(e) => updateField("education", index, "degree", e.target.value)} style={inputStyle} /></div>
                    <div><label style={labelStyle}>Institution</label><input value={item.institution} onChange={(e) => updateField("education", index, "institution", e.target.value)} style={inputStyle} /></div>
                    <div><label style={labelStyle}>Field</label><input value={item.field} onChange={(e) => updateField("education", index, "field", e.target.value)} style={inputStyle} /></div>
                    <div><label style={labelStyle}>CGPA</label><input value={item.cgpa} onChange={(e) => updateField("education", index, "cgpa", e.target.value)} style={inputStyle} /></div>
                    <div><label style={labelStyle}>Start</label><input type="date" value={item.start_date} onChange={(e) => updateField("education", index, "start_date", e.target.value)} style={inputStyle} /></div>
                    <div><label style={labelStyle}>End</label><input type="date" value={item.end_date} onChange={(e) => updateField("education", index, "end_date", e.target.value)} style={inputStyle} /></div>
                  </div>
                </div>
              ))}
              <button type="button" onClick={() => addItem("education")} style={{ marginTop: 8, border: `1px dashed ${C.border}`, background: "#F9FAFC", color: C.blueDark, padding: "10px 14px", borderRadius: 8, fontWeight: 700, cursor: "pointer" }}>+ Add education</button>
            </div>
          )}

          {step === 3 && (
            <div>
              <h2 style={{ margin: "0 0 20px", color: C.text, fontSize: 26 }}>Experience & skills</h2>

              <div style={{ marginBottom: 22 }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
                  <div style={{ fontWeight: 700, color: C.text2 }}>Experience</div>
                  <button type="button" onClick={() => addItem("experience")} style={{ border: `1px dashed ${C.border}`, background: "#F9FAFC", color: C.blueDark, padding: "8px 12px", borderRadius: 8, fontWeight: 700, cursor: "pointer" }}>+ Add experience</button>
                </div>
                {experience.map((item, index) => (
                  <div key={`experience-${index}`} style={{ border: `1px solid ${C.border}`, borderRadius: 12, padding: 14, marginBottom: 12 }}>
                    <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 10 }}>
                      <div style={{ fontWeight: 700 }}>Role #{index + 1}</div>
                      {experience.length > 1 && <button type="button" onClick={() => removeItem("experience", index)} style={{ border: 0, background: "transparent", color: C.red, fontWeight: 700, cursor: "pointer" }}>Remove</button>}
                    </div>
                    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 12 }}>
                      <div><label style={labelStyle}>Company</label><input value={item.company} onChange={(e) => updateField("experience", index, "company", e.target.value)} style={inputStyle} /></div>
                      <div><label style={labelStyle}>Role</label><input value={item.role} onChange={(e) => updateField("experience", index, "role", e.target.value)} style={inputStyle} /></div>
                      <div><label style={labelStyle}>Domain</label><input value={item.domain} onChange={(e) => updateField("experience", index, "domain", e.target.value)} style={inputStyle} /></div>
                      <div><label style={labelStyle}>Start</label><input type="date" value={item.start_date} onChange={(e) => updateField("experience", index, "start_date", e.target.value)} style={inputStyle} /></div>
                      <div><label style={labelStyle}>End</label><input type="date" value={item.end_date} onChange={(e) => updateField("experience", index, "end_date", e.target.value)} style={inputStyle} /></div>
                    </div>
                  </div>
                ))}
              </div>

              <div>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
                  <div style={{ fontWeight: 700, color: C.text2 }}>Skills</div>
                  <button type="button" onClick={() => addItem("skills")} style={{ border: `1px dashed ${C.border}`, background: "#F9FAFC", color: C.blueDark, padding: "8px 12px", borderRadius: 8, fontWeight: 700, cursor: "pointer" }}>+ Add skill</button>
                </div>
                {skills.map((item, index) => (
                  <div key={`skill-${index}`} style={{ border: `1px solid ${C.border}`, borderRadius: 12, padding: 14, marginBottom: 12 }}>
                    <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 10 }}>
                      <div style={{ fontWeight: 700 }}>Skill #{index + 1}</div>
                      {skills.length > 1 && <button type="button" onClick={() => removeItem("skills", index)} style={{ border: 0, background: "transparent", color: C.red, fontWeight: 700, cursor: "pointer" }}>Remove</button>}
                    </div>
                    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))", gap: 12 }}>
                      <div><label style={labelStyle}>Skill</label><input value={item.name} onChange={(e) => updateField("skills", index, "name", e.target.value)} style={inputStyle} /></div>
                      <div><label style={labelStyle}>Category</label><input value={item.category} onChange={(e) => updateField("skills", index, "category", e.target.value)} style={inputStyle} /></div>
                      <div><label style={labelStyle}>Proficiency</label><select value={item.proficiency} onChange={(e) => updateField("skills", index, "proficiency", e.target.value)} style={inputStyle}><option>Beginner</option><option>Intermediate</option><option>Advanced</option></select></div>
                      <div><label style={labelStyle}>Years</label><input type="number" step="0.1" value={item.years} onChange={(e) => updateField("skills", index, "years", e.target.value)} style={inputStyle} /></div>
                      <div><label style={labelStyle}>Evidence</label><input type="number" step="1" value={item.evidence_score} onChange={(e) => updateField("skills", index, "evidence_score", e.target.value)} style={inputStyle} /></div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {step === 4 && (
            <div>
              <h2 style={{ margin: "0 0 20px", color: C.text, fontSize: 26 }}>Projects & certifications</h2>

              <div style={{ marginBottom: 22 }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
                  <div style={{ fontWeight: 700, color: C.text2 }}>Projects</div>
                  <button type="button" onClick={() => addItem("projects")} style={{ border: `1px dashed ${C.border}`, background: "#F9FAFC", color: C.blueDark, padding: "8px 12px", borderRadius: 8, fontWeight: 700, cursor: "pointer" }}>+ Add project</button>
                </div>
                {projects.map((item, index) => (
                  <div key={`project-${index}`} style={{ border: `1px solid ${C.border}`, borderRadius: 12, padding: 14, marginBottom: 12 }}>
                    <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 10 }}>
                      <div style={{ fontWeight: 700 }}>Project #{index + 1}</div>
                      {projects.length > 1 && <button type="button" onClick={() => removeItem("projects", index)} style={{ border: 0, background: "transparent", color: C.red, fontWeight: 700, cursor: "pointer" }}>Remove</button>}
                    </div>
                    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 12 }}>
                      <div style={{ gridColumn: "1 / -1" }}><label style={labelStyle}>Title</label><input value={item.title} onChange={(e) => updateField("projects", index, "title", e.target.value)} style={inputStyle} /></div>
                      <div style={{ gridColumn: "1 / -1" }}><label style={labelStyle}>Description</label><textarea value={item.description} onChange={(e) => updateField("projects", index, "description", e.target.value)} style={{ ...inputStyle, minHeight: 80, resize: "vertical" }} /></div>
                      <div><label style={labelStyle}>Complexity</label><select value={item.complexity} onChange={(e) => updateField("projects", index, "complexity", e.target.value)} style={inputStyle}><option>Low</option><option>Medium</option><option>High</option></select></div>
                      <div><label style={labelStyle}>Impact</label><select value={item.impact} onChange={(e) => updateField("projects", index, "impact", e.target.value)} style={inputStyle}><option>Low</option><option>Medium</option><option>High</option></select></div>
                      <div><label style={labelStyle}>Solo</label><select value={item.solo ? "Yes" : "No"} onChange={(e) => updateField("projects", index, "solo", e.target.value === "Yes")} style={inputStyle}><option value="Yes">Yes</option><option value="No">No</option></select></div>
                      <div style={{ gridColumn: "1 / -1" }}><label style={labelStyle}>GitHub URL</label><input value={item.github_url} onChange={(e) => updateField("projects", index, "github_url", e.target.value)} style={inputStyle} /></div>
                      <div style={{ gridColumn: "1 / -1" }}><label style={labelStyle}>Skills used (comma-separated)</label><input value={item.skills} onChange={(e) => updateField("projects", index, "skills", e.target.value)} style={inputStyle} placeholder="Python, FastAPI, SQL" /></div>
                    </div>
                  </div>
                ))}
              </div>

              <div>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
                  <div style={{ fontWeight: 700, color: C.text2 }}>Certifications</div>
                  <button type="button" onClick={() => addItem("certifications")} style={{ border: `1px dashed ${C.border}`, background: "#F9FAFC", color: C.blueDark, padding: "8px 12px", borderRadius: 8, fontWeight: 700, cursor: "pointer" }}>+ Add certification</button>
                </div>
                {certifications.map((item, index) => (
                  <div key={`cert-${index}`} style={{ border: `1px solid ${C.border}`, borderRadius: 12, padding: 14, marginBottom: 12 }}>
                    <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 10 }}>
                      <div style={{ fontWeight: 700 }}>Certification #{index + 1}</div>
                      {certifications.length > 1 && <button type="button" onClick={() => removeItem("certifications", index)} style={{ border: 0, background: "transparent", color: C.red, fontWeight: 700, cursor: "pointer" }}>Remove</button>}
                    </div>
                    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 12 }}>
                      <div><label style={labelStyle}>Name</label><input value={item.name} onChange={(e) => updateField("certifications", index, "name", e.target.value)} style={inputStyle} /></div>
                      <div><label style={labelStyle}>Issuer</label><input value={item.issuer} onChange={(e) => updateField("certifications", index, "issuer", e.target.value)} style={inputStyle} /></div>
                      <div><label style={labelStyle}>Issue date</label><input type="date" value={item.issue_date} onChange={(e) => updateField("certifications", index, "issue_date", e.target.value)} style={inputStyle} /></div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: 24, gap: 12 }}>
            <button type="button" onClick={prevStep} disabled={step === 1} style={{ padding: "12px 18px", border: `1px solid ${C.border}`, borderRadius: 8, background: C.white, color: C.text, fontWeight: 700, cursor: step === 1 ? "not-allowed" : "pointer", opacity: step === 1 ? 0.6 : 1 }}>Back</button>
            {step < totalSteps ? (
              <button type="button" onClick={nextStep} style={{ padding: "12px 18px", border: 0, borderRadius: 8, background: C.blueDark, color: "#fff", fontWeight: 700, cursor: "pointer" }}>Continue</button>
            ) : (
              <button type="button" onClick={handleSubmit} disabled={loading} style={{ padding: "12px 18px", border: 0, borderRadius: 8, background: C.green, color: "#fff", fontWeight: 700, cursor: loading ? "default" : "pointer", opacity: loading ? 0.7 : 1 }}>
                {loading ? "Saving profile..." : mode === "edit" ? "Save profile changes" : "Finish onboarding"}
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
