import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  aiChat,
  aiWhatIf,
  getAIEvidence,
  getAIOptions,
  getAIRoadmap,
  getAIStatus,
} from "../api";

/* =========================================================
   CareerDNA - Local AI Assistant (Ollama)
   Tabs: Chat | What-If | Roadmap | Evidence
   Everything here talks to the CareerDNA backend (/ai/*);
   the backend talks to the LOCAL Ollama server. No cloud AI.
   ========================================================= */

const EXAMPLES = [
  "Why am I a 68% match for ML Engineer?",
  "Which skills are holding me back?",
  "What evidence supports my Python proficiency?",
  "Compare ML Engineer and Cybersecurity Analyst for my profile.",
  "What should I learn next for my target career?",
  "What if I learn PyTorch and complete a machine learning project?",
  "What information is missing before you can assess my readiness?",
];

const STATUS_STYLE = {
  documented: { tone: "green", label: "Documented" },
  self_reported_only: { tone: "amber", label: "Self-reported only" },
  contradictory: { tone: "red", label: "Records disagree" },
  no_record: { tone: "gray", label: "No record" },
};

const VERIFY_TEXT = {
  passed: ["green", "Checked against your data"],
  regenerated: ["green", "Checked (corrected once)"],
  qualified: ["amber", "Partly removed - see note"],
  fallback: ["amber", "Showing backend results only"],
  no_llm_needed: ["gray", "No AI text needed"],
  skipped: ["gray", "Not generated"],
};

function errText(e) {
  const m = e && e.message ? e.message : e;
  if (typeof m === "string") return m;
  try {
    return JSON.stringify(m);
  } catch {
    return "Something went wrong.";
  }
}

/* ---------------------------------------------------------
   Small UI helpers (styled with the dashboard theme `C`)
   --------------------------------------------------------- */
const ThemeContext = React.createContext(null);

function tonesFor(C) {
  return {
    green: { bg: "#E9F4EF", fg: C.green, bd: "#CFE6DC" },
    amber: { bg: "#FBF3E3", fg: "#9A6F1B", bd: "#F0DFB9" },
    red: { bg: "#FBEEEE", fg: C.red, bd: "#F0D0D0" },
    blue: { bg: C.blueSoft, fg: C.blueDark, bd: "#D5E1EF" },
    gray: { bg: C.soft, fg: C.text2, bd: C.border },
  };
}

function Pill({ tone = "gray", children, title }) {
  const C = React.useContext(ThemeContext);
  const t = tonesFor(C)[tone];
  return (
    <span
      title={title}
      style={{
        display: "inline-block",
        background: t.bg,
        color: t.fg,
        border: `1px solid ${t.bd}`,
        borderRadius: 999,
        padding: "2px 9px",
        fontSize: 10,
        fontWeight: 700,
        whiteSpace: "nowrap",
      }}
    >
      {children}
    </span>
  );
}

function Box({ children, style }) {
  const C = React.useContext(ThemeContext);
  return (
    <div
      style={{
        background: C.white,
        border: `1px solid ${C.border}`,
        borderRadius: 10,
        padding: 14,
        ...style,
      }}
    >
      {children}
    </div>
  );
}

function Btn({ children, onClick, disabled, kind = "primary", style, title }) {
  const C = React.useContext(ThemeContext);
  return (
    <button
      title={title}
      onClick={onClick}
      disabled={disabled}
      style={{
        border: kind === "primary" ? "none" : `1px solid ${C.border}`,
        background: kind === "primary" ? (disabled ? "#9DB3CC" : C.blueDark) : C.white,
        color: kind === "primary" ? "#fff" : C.text2,
        borderRadius: 7,
        padding: "8px 14px",
        fontSize: 11,
        fontWeight: 700,
        cursor: disabled ? "not-allowed" : "pointer",
        ...style,
      }}
    >
      {children}
    </button>
  );
}

function Details({ summary, children, open }) {
  const C = React.useContext(ThemeContext);
  return (
    <details open={open} style={{ marginTop: 8 }}>
      <summary style={{ cursor: "pointer", color: C.blue, fontSize: 10.5, fontWeight: 700 }}>{summary}</summary>
      <div style={{ marginTop: 6 }}>{children}</div>
    </details>
  );
}

function makeField(C) {
  return {
    border: `1px solid ${C.border}`,
    borderRadius: 7,
    padding: "7px 9px",
    fontSize: 11.5,
    color: C.text,
    background: C.white,
    fontFamily: "inherit",
  };
}

function useUI(C) {
  return useMemo(() => ({ field: makeField(C) }), [C]);
}

/* ---------------------------------------------------------
   Status bar: is Ollama running and is the model installed?
   --------------------------------------------------------- */
function StatusBar({ C, status, loading, onRefresh }) {
  const ready = status && status.ready;
  const color = loading ? C.muted : ready ? C.green : status && status.reachable ? C.amber : C.red;
  const text = loading
    ? "Checking local AI..."
    : ready
    ? `Local model ready: ${status.model}${status.loaded ? " (loaded)" : " (loads on first question)"}`
    : status && status.reachable
    ? "Ollama is running, but the model is not installed"
    : "Local AI is not running";
  return (
    <div style={{ marginBottom: 12 }}>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 10,
          flexWrap: "wrap",
          background: C.white,
          border: `1px solid ${C.border}`,
          borderRadius: 10,
          padding: "9px 12px",
        }}
      >
        <span style={{ width: 9, height: 9, borderRadius: 99, background: color, display: "inline-block" }} />
        <span style={{ fontSize: 11.5, fontWeight: 700, color: C.text }}>{text}</span>
        <Pill tone="blue" title="All AI processing happens on this computer through Ollama. Nothing is sent to a cloud AI service.">
          100% local - no cloud AI
        </Pill>
        {status && status.model_size_bytes ? (
          <span style={{ fontSize: 10, color: C.muted }}>
            model size {(status.model_size_bytes / 1e9).toFixed(1)} GB
          </span>
        ) : null}
        <div style={{ marginLeft: "auto" }}>
          <Btn kind="ghost" onClick={onRefresh} disabled={loading}>
            Refresh
          </Btn>
        </div>
      </div>
      {!loading && status && !ready && status.error ? (
        <div
          style={{
            marginTop: 8,
            background: "#FBF3E3",
            border: "1px solid #F0DFB9",
            borderRadius: 8,
            padding: "9px 12px",
            fontSize: 11,
            color: "#7A5A17",
            lineHeight: 1.5,
          }}
        >
          <b>{status.error.message}</b>
          <div>{status.error.instructions}</div>
          <div style={{ marginTop: 4 }}>
            The rest of CareerDNA (skills, salary, matching, simulator) keeps working without the AI.
            What-If and Roadmap below still show their calculated results; only the AI explanation needs Ollama.
          </div>
        </div>
      ) : null}
    </div>
  );
}

/* ---------------------------------------------------------
   Chat
   --------------------------------------------------------- */
const CITE = /\[([a-z_]+:[A-Za-z0-9_:-]+)\]/g;

function AnswerText({ C, text, evidence }) {
  const [open, setOpen] = useState(null);
  const labels = useMemo(() => {
    const m = {};
    (evidence || []).forEach((e) => (m[e.ref] = e));
    return m;
  }, [evidence]);
  return (
    <div style={{ fontSize: 12.5, color: C.text, lineHeight: 1.6 }}>
      {String(text || "")
        .split(/\n{2,}/)
        .map((para, i) => (
          <p key={i} style={{ margin: "0 0 8px", whiteSpace: "pre-wrap" }}>
            {para.split(CITE).map((part, j) =>
              j % 2 === 1 ? (
                <button
                  key={j}
                  onClick={() => setOpen(open === part ? null : part)}
                  title="Show the record behind this statement"
                  style={{
                    border: `1px solid ${C.border}`,
                    background: C.blueSoft,
                    color: C.blueDark,
                    borderRadius: 5,
                    fontSize: 10,
                    fontWeight: 700,
                    padding: "0 5px",
                    margin: "0 2px",
                    cursor: "pointer",
                  }}
                >
                  {part}
                </button>
              ) : (
                <span key={j}>{part}</span>
              )
            )}
          </p>
        ))}
      {open ? (
        <div style={{ background: C.soft, borderRadius: 7, padding: "6px 9px", fontSize: 11, color: C.text2 }}>
          <b>{open}</b>
          {labels[open] ? (
            <>
              {" "}
              - {labels[open].label} <Pill>{labels[open].type}</Pill>
            </>
          ) : (
            " - record reference"
          )}
        </div>
      ) : null}
    </div>
  );
}

function RetrievalPill({ retrieval }) {
  const d = retrieval && retrieval.length ? retrieval[0] : null;
  if (!d) return null;
  if (d.fallback) {
    return (
      <Pill tone="amber" title={d.fallback_message || "The semantic search failed, so keyword search was used."}>
        Hybrid unavailable - keyword search used ({d.fallback_reason})
      </Pill>
    );
  }
  if (d.effective_mode === "hybrid") {
    return <Pill tone="green" title="Related records were found with keyword search plus local semantic search.">Retrieval: hybrid (keyword + semantic)</Pill>;
  }
  return <Pill tone="gray" title="Related records were found with keyword search only.">Retrieval: keyword (BM25)</Pill>;
}

function AssistantCard({ C, m }) {
  const v = m.verification || {};
  const [vt, vl] = VERIFY_TEXT[v.status] || ["gray", v.status || ""];
  return (
    <div style={{ background: C.white, border: `1px solid ${C.border}`, borderRadius: 10, padding: 14 }}>
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 8 }}>
        {m.hypothetical ? <Pill tone="amber">HYPOTHETICAL - not your real profile</Pill> : <Pill tone="green">Based on your real records</Pill>}
        {m.answer ? <Pill tone={vt}>{vl}</Pill> : null}
        <Pill tone="gray">intent: {String(m.intent || "").replace("_", " ")}</Pill>
        <RetrievalPill retrieval={m.retrieval} />
        {m.model ? <Pill tone="gray">{m.model}</Pill> : null}
        {m.latency_ms != null ? <Pill tone="gray">{(m.latency_ms / 1000).toFixed(1)}s</Pill> : null}
      </div>

      {m.ok === false ? (
        <div style={{ background: "#FBEEEE", border: "1px solid #F0D0D0", borderRadius: 8, padding: "9px 12px", fontSize: 11.5, color: "#8A3F3F", lineHeight: 1.5 }}>
          <b>{m.error && m.error.message}</b>
          <div>{m.error && m.error.instructions}</div>
        </div>
      ) : null}

      {m.answer ? <AnswerText C={C} text={m.answer} evidence={m.evidence} /> : null}

      {m.ok === false && m.fallback_summary ? (
        <div style={{ marginTop: 10 }}>
          <div style={{ fontSize: 10, fontWeight: 700, color: C.muted, textTransform: "uppercase", letterSpacing: ".6px" }}>
            Calculated results (no AI explanation available)
          </div>
          <pre style={{ whiteSpace: "pre-wrap", fontFamily: "inherit", fontSize: 11.5, color: C.text2, margin: "4px 0 0", lineHeight: 1.55 }}>
            {m.fallback_summary}
          </pre>
        </div>
      ) : null}

      {v.issues && v.issues.length ? (
        <div style={{ marginTop: 8, background: "#FBF3E3", border: "1px solid #F0DFB9", borderRadius: 8, padding: "7px 10px", fontSize: 10.5, color: "#7A5A17" }}>
          The AI draft contained {v.issues.length} statement(s) that could not be verified against your data
          {v.status === "qualified" ? " and were removed." : "."}
          <Details summary="What was flagged">
            <ul style={{ margin: 0, paddingLeft: 16 }}>
              {v.issues.map((i, k) => (
                <li key={k}>{i.detail}</li>
              ))}
            </ul>
          </Details>
        </div>
      ) : null}

      {m.notes && m.notes.length ? (
        <div style={{ marginTop: 8, fontSize: 10.5, color: C.muted }}>
          {m.notes.map((n, i) => (
            <div key={i}>Note: {n}</div>
          ))}
        </div>
      ) : null}

      {m.facts && m.facts.length ? (
        <Details summary={`Verified facts used (${m.facts.reduce((a, f) => a + f.lines.length, 0)} lines from CareerDNA's own calculations)`}>
          <div style={{ background: C.page, border: `1px solid ${C.border}`, borderRadius: 7, padding: "8px 10px", fontSize: 11, color: C.text2, lineHeight: 1.55 }}>
            {m.facts.map((f, i) => (
              <div key={i} style={{ marginBottom: 6 }}>
                <b style={{ color: C.text }}>{f.tool.replace(/_/g, " ")}</b>
                {f.lines.map((l, k) => (
                  <div key={k} style={{ whiteSpace: "pre-wrap" }}>{l}</div>
                ))}
              </div>
            ))}
          </div>
        </Details>
      ) : null}

      {m.evidence && m.evidence.length ? (
        <Details summary={`Evidence records (${m.evidence.length})`}>
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
            {m.evidence.map((e) => (
              <span key={e.ref} title={e.ref} style={{ fontSize: 10.5, color: C.text2, border: `1px solid ${C.border}`, borderRadius: 6, padding: "2px 7px" }}>
                <b>[{e.ref}]</b> {e.label}
              </span>
            ))}
          </div>
        </Details>
      ) : null}

      {m.tools && m.tools.length ? (
        <Details summary="Backend functions called">
          <div style={{ fontSize: 10.5, color: C.text2 }}>
            {m.tools.map((t, i) => (
              <div key={i}>
                {t.ok ? "OK" : "FAILED"} - {t.name}({Object.keys(t.args || {}).length ? JSON.stringify(t.args) : ""}){t.error ? ` - ${t.error}` : ""}
              </div>
            ))}
          </div>
        </Details>
      ) : null}
    </div>
  );
}

function ChatPanel({ C, ui, status }) {
  const { field } = ui;
  const [items, setItems] = useState([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [context, setContext] = useState(null);
  const endRef = useRef(null);

  useEffect(() => {
    endRef.current && endRef.current.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [items, busy]);

  async function send(question) {
    const q = (question ?? text).trim();
    if (!q || busy) return;
    setText("");
    setItems((x) => [...x, { role: "user", text: q }]);
    setBusy(true);
    try {
      const res = await aiChat(q, context);
      setContext(res.context || null);
      setItems((x) => [...x, { role: "assistant", data: res }]);
    } catch (e) {
      setItems((x) => [...x, { role: "error", text: errText(e) }]);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      {items.length === 0 ? (
        <div style={{ background: C.white, border: `1px solid ${C.border}`, borderRadius: 10, padding: 14, marginBottom: 12 }}>
          <div style={{ fontSize: 12.5, fontWeight: 700, color: C.text, marginBottom: 4 }}>Ask about your career</div>
          <div style={{ fontSize: 11.5, color: C.text2, lineHeight: 1.55, marginBottom: 10 }}>
            Answers are written by a model running on this computer, but every number comes from CareerDNA's own
            calculations and every claim is checked against your records before you see it. Try an example (these are
            just suggestions - you can ask anything):
          </div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
            {EXAMPLES.map((q) => (
              <button
                key={q}
                onClick={() => send(q)}
                disabled={busy}
                style={{ border: `1px solid ${C.border}`, background: C.blueSoft, color: C.blueDark, borderRadius: 999, fontSize: 11, padding: "5px 11px", cursor: "pointer", textAlign: "left" }}
              >
                {q}
              </button>
            ))}
          </div>
        </div>
      ) : null}

      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        {items.map((it, i) =>
          it.role === "user" ? (
            <div key={i} style={{ alignSelf: "flex-end", maxWidth: "85%", background: C.blueDark, color: "#fff", borderRadius: "12px 12px 2px 12px", padding: "8px 12px", fontSize: 12.5 }}>
              {it.text}
            </div>
          ) : it.role === "error" ? (
            <div key={i} style={{ background: "#FBEEEE", border: "1px solid #F0D0D0", color: "#8A3F3F", borderRadius: 10, padding: "9px 12px", fontSize: 11.5 }}>
              {it.text}
            </div>
          ) : (
            <AssistantCard key={i} C={C} m={it.data} />
          )
        )}
        {busy ? (
          <div style={{ color: C.muted, fontSize: 11.5, padding: "4px 2px" }}>
            Thinking locally... the first answer can take a minute while the model loads into memory.
          </div>
        ) : null}
        <div ref={endRef} />
      </div>

      <div style={{ display: "flex", gap: 8, marginTop: 12, alignItems: "flex-end" }}>
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              send();
            }
          }}
          maxLength={800}
          rows={2}
          placeholder={status && !status.ready ? "The local model is not ready - you will still get calculated results..." : "Ask a career question (Enter to send)"}
          style={{ ...field, flex: 1, resize: "vertical", minHeight: 44 }}
        />
        <Btn onClick={() => send()} disabled={busy || !text.trim()}>
          Send
        </Btn>
      </div>
    </div>
  );
}

/* ---------------------------------------------------------
   What-If simulator
   --------------------------------------------------------- */
function Delta({ C, value, unit = "" }) {
  if (value === 0 || value == null) return <span style={{ color: C.muted }}>no change</span>;
  const good = value > 0;
  return (
    <span style={{ color: good ? C.green : C.red, fontWeight: 700 }}>
      {good ? "+" : ""}
      {value}
      {unit}
    </span>
  );
}

function WhatIfPanel({ C, ui, options, roles }) {
  const { field } = ui;
  const [skills, setSkills] = useState([]);
  const [project, setProject] = useState({ on: false, title: "", skills: [] });
  const [cert, setCert] = useState({ on: false, name: "", skills: [] });
  const [months, setMonths] = useState(0);
  const [role, setRole] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [res, setRes] = useState(null);
  const all = (options && options.skills) || [];

  const toggle = (list, setList, s) => setList(list.includes(s) ? list.filter((x) => x !== s) : [...list, s]);
  const chip = (active) => ({
    border: `1px solid ${active ? C.blueDark : C.border}`,
    background: active ? C.blueDark : C.white,
    color: active ? "#fff" : C.text2,
    borderRadius: 999,
    fontSize: 10.5,
    padding: "3px 9px",
    cursor: "pointer",
  });
  const picker = (list, setList) => (
    <div style={{ display: "flex", flexWrap: "wrap", gap: 5, marginTop: 6 }}>
      {all.map((s) => (
        <button key={s} onClick={() => toggle(list, setList, s)} style={chip(list.includes(s))}>
          {s}
        </button>
      ))}
    </div>
  );

  async function run(explain) {
    setBusy(true);
    setErr("");
    try {
      const body = {
        add_skills: skills,
        add_projects: project.on ? [{ title: project.title || "hypothetical project", skills: project.skills }] : [],
        add_certifications: cert.on ? [{ name: cert.name || "hypothetical certification", skills: cert.skills }] : [],
        add_experience_months: Number(months) || 0,
        roles: role ? [role] : [],
        explain: !!explain,
      };
      setRes(await aiWhatIf(body));
    } catch (e) {
      setErr(errText(e));
    } finally {
      setBusy(false);
    }
  }

  const sc = res && res.scenario;
  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))", gap: 12, alignItems: "start" }}>
      <Box>
        <div style={{ fontSize: 12.5, fontWeight: 700, color: C.text }}>Career What-If simulator</div>
        <div style={{ fontSize: 11, color: C.text2, margin: "4px 0 10px", lineHeight: 1.5 }}>
          Try changes on a temporary copy of your profile. Nothing you enter here is saved or changes your real profile.
        </div>

        <label style={{ fontSize: 10.5, fontWeight: 700, color: C.text2 }}>Skills I might add (claimed)</label>
        {picker(skills, setSkills)}

        <div style={{ marginTop: 12 }}>
          <label style={{ fontSize: 11, color: C.text, fontWeight: 700 }}>
            <input type="checkbox" checked={project.on} onChange={(e) => setProject({ ...project, on: e.target.checked })} /> Add a documented project
          </label>
          {project.on ? (
            <div style={{ marginTop: 6 }}>
              <input style={{ ...field, width: "100%", boxSizing: "border-box" }} placeholder="Project title (optional)" value={project.title} maxLength={120} onChange={(e) => setProject({ ...project, title: e.target.value })} />
              <div style={{ fontSize: 10.5, color: C.muted, marginTop: 6 }}>Skills used in the project:</div>
              {picker(project.skills, (v) => setProject({ ...project, skills: v }))}
            </div>
          ) : null}
        </div>

        <div style={{ marginTop: 12 }}>
          <label style={{ fontSize: 11, color: C.text, fontWeight: 700 }}>
            <input type="checkbox" checked={cert.on} onChange={(e) => setCert({ ...cert, on: e.target.checked })} /> Add a certification
          </label>
          {cert.on ? (
            <div style={{ marginTop: 6 }}>
              <input style={{ ...field, width: "100%", boxSizing: "border-box" }} placeholder="Certification name, e.g. AWS Cloud Practitioner" value={cert.name} maxLength={120} onChange={(e) => setCert({ ...cert, name: e.target.value })} />
              <div style={{ fontSize: 10.5, color: C.muted, marginTop: 6 }}>Skills it covers (optional):</div>
              {picker(cert.skills, (v) => setCert({ ...cert, skills: v }))}
            </div>
          ) : null}
        </div>

        <div style={{ display: "flex", gap: 10, marginTop: 12, flexWrap: "wrap" }}>
          <div>
            <div style={{ fontSize: 10.5, fontWeight: 700, color: C.text2 }}>Extra months of experience</div>
            <input type="number" min={0} max={120} value={months} onChange={(e) => setMonths(Math.max(0, Math.min(120, e.target.value)))} style={{ ...field, width: 90 }} />
          </div>
          <div>
            <div style={{ fontSize: 10.5, fontWeight: 700, color: C.text2 }}>Focus on role</div>
            <select value={role} onChange={(e) => setRole(e.target.value)} style={field}>
              <option value="">All roles</option>
              {((options && options.roles) || roles || []).map((r) => (
                <option key={r}>{r}</option>
              ))}
            </select>
          </div>
        </div>

        <div style={{ display: "flex", gap: 8, marginTop: 14, flexWrap: "wrap" }}>
          <Btn onClick={() => run(false)} disabled={busy}>{busy ? "Calculating..." : "Run simulation"}</Btn>
          <Btn kind="ghost" onClick={() => run(true)} disabled={busy} title="Also asks the local AI to explain the results (needs Ollama)">
            Run + explain with local AI
          </Btn>
        </div>
        {err ? <div style={{ marginTop: 10, color: C.red, fontSize: 11.5 }}>{err}</div> : null}
      </Box>

      <div>
        {!sc ? (
          <Box>
            <div style={{ fontSize: 11.5, color: C.muted, lineHeight: 1.55 }}>
              Pick at least one change and run the simulation. You will see your real baseline next to the hypothetical scenario,
              exactly which requirement caused each change, and what the scoring rules cannot tell you.
            </div>
          </Box>
        ) : (
          <>
            <div style={{ background: "#FBF3E3", border: "1px solid #F0DFB9", color: "#7A5A17", borderRadius: 8, padding: "8px 12px", fontSize: 11, fontWeight: 700, marginBottom: 10 }}>
              {sc.label}
            </div>
            <Box>
              <div style={{ overflowX: "auto" }}>
                <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 11.5 }}>
                  <thead>
                    <tr style={{ textAlign: "left", color: C.muted, fontSize: 10 }}>
                      <th style={{ padding: "4px 6px" }}>Role</th>
                      <th style={{ padding: "4px 6px" }}>Official match: real</th>
                      <th style={{ padding: "4px 6px" }}>Hypothetical</th>
                      <th style={{ padding: "4px 6px" }}>Change</th>
                      <th style={{ padding: "4px 6px" }} title="Share of the role's required skills backed by a project or certification (supplementary metric)">Documented %</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.keys(sc.baseline.roles).map((r) => {
                      const b = sc.baseline.roles[r];
                      const s = sc.scenario.roles[r];
                      const c = sc.changes.roles[r];
                      return (
                        <tr key={r} style={{ borderTop: `1px solid ${C.border}` }}>
                          <td style={{ padding: "7px 6px", fontWeight: 700, color: C.text }}>{r}</td>
                          <td style={{ padding: "7px 6px" }}>{b.match_percent}%</td>
                          <td style={{ padding: "7px 6px", color: C.blueDark, fontWeight: 700 }}>{s.match_percent}%</td>
                          <td style={{ padding: "7px 6px" }}><Delta C={C} value={c.match_delta_pp} unit=" pp" /></td>
                          <td style={{ padding: "7px 6px" }}>
                            {b.documented_percent}% to {s.documented_percent}% (<Delta C={C} value={c.documented_delta_pp} unit=" pp" />)
                          </td>
                        </tr>
                      );
                    })}
                    <tr style={{ borderTop: `1px solid ${C.border}` }}>
                      <td style={{ padding: "7px 6px", fontWeight: 700, color: C.text }}>Salary (CareerDNA rules)</td>
                      <td style={{ padding: "7px 6px" }}>{sc.baseline.salary.base_salary_lpa} LPA</td>
                      <td style={{ padding: "7px 6px", color: C.blueDark, fontWeight: 700 }}>{sc.scenario.salary.projected_salary_lpa} LPA</td>
                      <td style={{ padding: "7px 6px" }}><Delta C={C} value={sc.changes.salary_delta_lpa} unit=" LPA" /></td>
                      <td />
                    </tr>
                  </tbody>
                </table>
              </div>

              <Details summary="Why did it change?" open>
                <ul style={{ margin: 0, paddingLeft: 16, fontSize: 11.5, color: C.text2, lineHeight: 1.6 }}>
                  {sc.applied.map((a, i) => (
                    <li key={i}>
                      Simulated: {a.type === "skill" ? `skill ${a.skill}` : a.type === "project" ? `project "${a.title}"` : a.type === "certification" ? `certification "${a.name}"` : `${a.months} months of experience`}
                    </li>
                  ))}
                  {Object.entries(sc.changes.roles).flatMap(([r, c]) =>
                    c.newly_matched.map((n) => (
                      <li key={r + n.skill}>
                        {r}: requirement <b>{n.skill}</b> (weight {n.importance}) is now satisfied.
                      </li>
                    ))
                  )}
                  {Object.entries(sc.changes.roles).flatMap(([r, c]) =>
                    c.evidence_status_changes.map((n) => (
                      <li key={r + n.skill + "e"}>
                        {r}: evidence for <b>{n.skill}</b> {n.before.replace(/_/g, " ")} to {n.after.replace(/_/g, " ")}.
                      </li>
                    ))
                  )}
                  {!sc.applied.length ? <li>No change could be applied (see below).</li> : null}
                </ul>
              </Details>

              {sc.unresolved.length ? (
                <div style={{ marginTop: 8, fontSize: 11, color: "#7A5A17" }}>
                  {sc.unresolved.map((u, i) => (
                    <div key={i}><Pill tone="amber">Not scored</Pill> {u.input}: {u.reason}</div>
                  ))}
                </div>
              ) : null}
              {sc.assumptions.length ? (
                <div style={{ marginTop: 8, fontSize: 11, color: C.text2 }}>
                  {sc.assumptions.map((a, i) => (<div key={i}>Assumption: {a}</div>))}
                </div>
              ) : null}
              <Details summary="Limits of this simulation">
                <ul style={{ margin: 0, paddingLeft: 16, fontSize: 11, color: C.text2, lineHeight: 1.55 }}>
                  {sc.limitations.map((l, i) => (<li key={i}>{l}</li>))}
                </ul>
              </Details>
            </Box>

            {res.explanation ? (
              <div style={{ marginTop: 10 }}>
                <AssistantCard
                  C={C}
                  m={{ ...res.explanation, intent: "what_if", hypothetical: true, evidence: [], facts: [], tools: [] }}
                />
              </div>
            ) : null}
          </>
        )}
      </div>
    </div>
  );
}

/* ---------------------------------------------------------
   Roadmap
   --------------------------------------------------------- */
function RoadmapPanel({ C, ui, options }) {
  const { field } = ui;
  const [role, setRole] = useState("");
  const [hpw, setHpw] = useState(6);
  const [weeks, setWeeks] = useState(12);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [res, setRes] = useState(null);

  async function run(explain) {
    setBusy(true);
    setErr("");
    try {
      setRes(await getAIRoadmap({ role, hoursPerWeek: Number(hpw) || 1, weeks: Number(weeks) || 1, explain }));
    } catch (e) {
      setErr(errText(e));
    } finally {
      setBusy(false);
    }
  }
  const fit = { yes: ["green", "fits your time"], maybe: ["amber", "may not fit"], no: ["red", "beyond your time"] };
  const road = res && res.roadmap;
  return (
    <div>
      <Box style={{ marginBottom: 12 }}>
        <div style={{ display: "flex", gap: 12, flexWrap: "wrap", alignItems: "flex-end" }}>
          <div>
            <div style={{ fontSize: 10.5, fontWeight: 700, color: C.text2 }}>Target role</div>
            <select value={role} onChange={(e) => setRole(e.target.value)} style={field}>
              <option value="">From my profile goals</option>
              {((options && options.roles) || []).map((r) => (<option key={r}>{r}</option>))}
            </select>
          </div>
          <div>
            <div style={{ fontSize: 10.5, fontWeight: 700, color: C.text2 }}>Hours per week</div>
            <input type="number" min={1} max={80} value={hpw} onChange={(e) => setHpw(e.target.value)} style={{ ...field, width: 80 }} />
          </div>
          <div>
            <div style={{ fontSize: 10.5, fontWeight: 700, color: C.text2 }}>Weeks available</div>
            <input type="number" min={1} max={104} value={weeks} onChange={(e) => setWeeks(e.target.value)} style={{ ...field, width: 80 }} />
          </div>
          <Btn onClick={() => run(false)} disabled={busy}>{busy ? "Building..." : "Build roadmap"}</Btn>
          <Btn kind="ghost" onClick={() => run(true)} disabled={busy}>Build + explain with local AI</Btn>
        </div>
        {err ? <div style={{ marginTop: 8, color: C.red, fontSize: 11.5 }}>{err}</div> : null}
      </Box>

      {road ? (
        <Box>
          <div style={{ fontSize: 12.5, fontWeight: 700, color: C.text }}>
            Roadmap toward {road.role} <span style={{ color: C.muted, fontWeight: 500 }}>- budget {road.budget_hours} hours</span>
          </div>
          {res.assumptions.map((a, i) => (<div key={i} style={{ fontSize: 11, color: C.text2, marginTop: 4 }}>{a}</div>))}
          {road.nothing_to_do ? (
            <div style={{ marginTop: 10, fontSize: 11.5, color: C.green }}>Nothing missing: every required skill for this role is in your records with supporting evidence.</div>
          ) : (
            <div style={{ overflowX: "auto", marginTop: 8 }}>
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 11.5 }}>
                <thead>
                  <tr style={{ textAlign: "left", color: C.muted, fontSize: 10 }}>
                    <th style={{ padding: "4px 6px" }}>#</th>
                    <th style={{ padding: "4px 6px" }}>Do this</th>
                    <th style={{ padding: "4px 6px" }}>Why</th>
                    <th style={{ padding: "4px 6px" }}>Estimate (hours)</th>
                    <th style={{ padding: "4px 6px" }}>Time window</th>
                  </tr>
                </thead>
                <tbody>
                  {road.items.map((it) => (
                    <tr key={it.step} style={{ borderTop: `1px solid ${C.border}`, verticalAlign: "top" }}>
                      <td style={{ padding: "7px 6px" }}>{it.step}</td>
                      <td style={{ padding: "7px 6px", fontWeight: 700, color: C.text }}>
                        {it.action} {it.skill}
                        <div><Pill tone={it.source.startsWith("curated") ? "gray" : "blue"}>{it.source}</Pill></div>
                      </td>
                      <td style={{ padding: "7px 6px", color: C.text2 }}>{it.reason}</td>
                      <td style={{ padding: "7px 6px" }}>{it.hours_low}-{it.hours_high} <span style={{ color: C.muted }}>(total {it.cumulative_hours[0]}-{it.cumulative_hours[1]})</span></td>
                      <td style={{ padding: "7px 6px" }}><Pill tone={fit[it.fits_window][0]}>{fit[it.fits_window][1]}</Pill></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <div style={{ marginTop: 8, fontSize: 10.5, color: C.muted }}>{road.disclaimer}</div>
        </Box>
      ) : null}
      {res && res.explanation ? (
        <div style={{ marginTop: 10 }}>
          <AssistantCard C={C} m={{ ...res.explanation, intent: "roadmap", evidence: [], facts: [], tools: [] }} />
        </div>
      ) : null}
    </div>
  );
}

/* ---------------------------------------------------------
   Evidence
   --------------------------------------------------------- */
function EvidencePanel({ C, data, err }) {
  if (err) return <div style={{ color: C.red, fontSize: 11.5 }}>{err}</div>;
  if (!data) return <div style={{ color: C.muted, fontSize: 11.5 }}>Loading evidence...</div>;
  return (
    <div>
      <Box style={{ marginBottom: 12 }}>
        <div style={{ fontSize: 12.5, fontWeight: 700, color: C.text, marginBottom: 6 }}>How your skills are supported by your records</div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          {Object.entries(data.legend).map(([k, v]) => (
            <div key={k} style={{ fontSize: 10.5, color: C.text2 }}>
              <Pill tone={STATUS_STYLE[k].tone}>{STATUS_STYLE[k].label}</Pill> {v}
            </div>
          ))}
        </div>
        <div style={{ fontSize: 10.5, color: C.muted, marginTop: 6 }}>
          CareerDNA has no assessment records, so assessment-based evidence cannot be shown. A missing record means proficiency cannot be established - it is not proof that you lack the skill.
        </div>
      </Box>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(290px, 1fr))", gap: 10 }}>
        {data.skills.map((s) => (
          <Box key={s.skill_id}>
            <div style={{ display: "flex", justifyContent: "space-between", gap: 6, alignItems: "center" }}>
              <b style={{ color: C.text, fontSize: 12.5 }}>{s.skill_name}</b>
              <Pill tone={STATUS_STYLE[s.status].tone}>{STATUS_STYLE[s.status].label}</Pill>
            </div>
            <div style={{ fontSize: 11, color: C.text2, marginTop: 5, lineHeight: 1.5 }}>{s.note}</div>
            {s.self_reported ? (
              <div style={{ fontSize: 10.5, color: C.muted, marginTop: 5 }}>
                [{s.self_reported.ref}] {s.self_reported.proficiency || "level n/a"}, {s.self_reported.years} yrs
                {s.self_reported.recorded_evidence_score != null ? `, recorded evidence score ${s.self_reported.recorded_evidence_score}/100` : ""}
              </div>
            ) : null}
            {s.contradictions.map((c, i) => (<div key={i} style={{ fontSize: 10.5, color: C.red, marginTop: 4 }}>{c}</div>))}
            {s.projects.map((p) => (<div key={p.ref} style={{ fontSize: 10.5, color: C.text2, marginTop: 3 }}>[{p.ref}] {p.title}</div>))}
            {s.certifications.map((c) => (<div key={c.ref} style={{ fontSize: 10.5, color: C.text2, marginTop: 3 }}>[{c.ref}] {c.name} <span style={{ color: C.muted }}>({c.verification_status || "unverified"})</span></div>))}
          </Box>
        ))}
      </div>
      {data.required_by_roles_without_record.length ? (
        <Box style={{ marginTop: 12 }}>
          <div style={{ fontSize: 12, fontWeight: 700, color: C.text }}>Required by roles, but nothing in your records</div>
          <div style={{ fontSize: 10.5, color: C.muted, margin: "3px 0 7px" }}>Proficiency cannot be established from the available data. This is not a statement about your ability.</div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
            {data.required_by_roles_without_record.map((s) => (<Pill key={s.skill_id}>{s.skill_name}</Pill>))}
          </div>
        </Box>
      ) : null}
    </div>
  );
}

/* ---------------------------------------------------------
   Main
   --------------------------------------------------------- */
const TABS = ["Chat", "What-If", "Roadmap", "Evidence"];

export default function AIAssistant({ theme, roles }) {
  const C = theme;
  const ui = useUI(C);
  const [tab, setTab] = useState("Chat");
  const [status, setStatus] = useState(null);
  const [checking, setChecking] = useState(true);
  const [options, setOptions] = useState(null);
  const [evidence, setEvidence] = useState(null);
  const [evErr, setEvErr] = useState("");
  const [loadErr, setLoadErr] = useState("");

  const refresh = useCallback(async () => {
    setChecking(true);
    try {
      setStatus(await getAIStatus());
    } catch (e) {
      setStatus({ reachable: false, ready: false, error: { message: errText(e), instructions: "" } });
    } finally {
      setChecking(false);
    }
  }, []);

  useEffect(() => {
    let alive = true;
    getAIStatus()
      .then((st) => alive && setStatus(st))
      .catch((e) => alive && setStatus({ reachable: false, ready: false, error: { message: errText(e), instructions: "" } }))
      .finally(() => alive && setChecking(false));
    getAIOptions()
      .then((o) => alive && setOptions(o))
      .catch((e) => alive && setLoadErr(errText(e)));
    return () => {
      alive = false;
    };
  }, []);

  useEffect(() => {
    if (tab === "Evidence" && !evidence && !evErr) {
      getAIEvidence().then(setEvidence).catch((e) => setEvErr(errText(e)));
    }
  }, [tab, evidence, evErr]);

  return (
    <ThemeContext.Provider value={C}>
    <div>
      <StatusBar C={C} status={status} loading={checking} onRefresh={refresh} />
      {loadErr ? (
        <div style={{ marginBottom: 10, color: C.red, fontSize: 11.5 }}>{loadErr}</div>
      ) : null}

      <div style={{ display: "flex", gap: 6, marginBottom: 14, flexWrap: "wrap" }}>
        {TABS.map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            style={{
              border: `1px solid ${tab === t ? C.blueDark : C.border}`,
              background: tab === t ? C.blueDark : C.white,
              color: tab === t ? "#fff" : C.text2,
              borderRadius: 7,
              padding: "6px 14px",
              fontSize: 11,
              fontWeight: 700,
              cursor: "pointer",
            }}
          >
            {t}
          </button>
        ))}
      </div>

      {tab === "Chat" ? <ChatPanel C={C} ui={ui} status={status} /> : null}
      {tab === "What-If" ? <WhatIfPanel C={C} ui={ui} options={options} roles={roles} /> : null}
      {tab === "Roadmap" ? <RoadmapPanel C={C} ui={ui} options={options} /> : null}
      {tab === "Evidence" ? <EvidencePanel C={C} data={evidence} err={evErr} /> : null}
    </div>
    </ThemeContext.Provider>
  );
}
