import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../api", () => ({
  getAIStatus: vi.fn(),
  getAIOptions: vi.fn(),
  aiChat: vi.fn(),
  aiWhatIf: vi.fn(),
  getAIEvidence: vi.fn(),
  getAIRoadmap: vi.fn(),
}));

import * as api from "../api";
import AIAssistant from "./AIAssistant";

const C = { page: "#fff", white: "#fff", border: "#ddd", soft: "#eee", text: "#111", text2: "#333", muted: "#777", blue: "#36a", blueDark: "#248", blueSoft: "#eef", amber: "#c93", red: "#c66", green: "#4b8", track: "#eee" };

const READY = { reachable: true, ready: true, model_installed: true, model: "qwen2.5:3b", loaded: false, model_size_bytes: 1.9e9, error: null };
const OPTIONS = { roles: ["ML Engineer", "Cybersecurity Analyst"], skills: ["PyTorch", "Docker", "Python"], default_role: "ML Engineer" };

function chatReply(extra = {}) {
  return {
    ok: true, intent: "match_explain", model: "qwen2.5:3b", latency_ms: 4200, hypothetical: false,
    answer: "Your official match for ML Engineer is 81.2% [job:1]. PyTorch cannot be established from your records.",
    verification: { status: "passed", issues: [] },
    evidence: [{ ref: "job:1", type: "job", label: "ML Engineer (Acme AI)" }],
    facts: [{ tool: "calculate_job_match", lines: ["OFFICIAL MATCH for ML Engineer [job:1]: 81.2%"], assumptions: [] }],
    tools: [{ name: "calculate_job_match", args: { role: "ML Engineer" }, ok: true }],
    notes: [], context: { roles: ["ML Engineer"] }, ...extra,
  };
}

beforeEach(() => {
  api.getAIStatus.mockResolvedValue(READY);
  api.getAIOptions.mockResolvedValue(OPTIONS);
  window.HTMLElement.prototype.scrollIntoView = vi.fn();
});
afterEach(() => { cleanup(); vi.clearAllMocks(); });

const mount = () => render(<AIAssistant theme={C} roles={["ML Engineer"]} />);

describe("status indicator", () => {
  it("shows the local model as ready", async () => {
    mount();
    expect(await screen.findByText(/Local model ready: qwen2.5:3b/)).toBeTruthy();
    expect(screen.getByText(/100% local - no cloud AI/)).toBeTruthy();
  });

  it("shows actionable instructions when the model is missing, and says the rest of the app still works", async () => {
    api.getAIStatus.mockResolvedValue({ reachable: true, ready: false, model_installed: false, model: "qwen2.5:3b", error: { code: "MODEL_MISSING", message: "Model 'qwen2.5:3b' is not installed in Ollama.", instructions: "Install it with: ollama pull qwen2.5:3b (then click Refresh)." } });
    mount();
    expect(await screen.findByText(/ollama pull qwen2.5:3b/)).toBeTruthy();
    expect(screen.getByText(/keeps working without the AI/)).toBeTruthy();
  });

  it("shows 'not running' when Ollama is unreachable", async () => {
    api.getAIStatus.mockResolvedValue({ reachable: false, ready: false, error: { code: "OLLAMA_UNREACHABLE", message: "Cannot reach Ollama", instructions: "Start Ollama: ollama serve" } });
    mount();
    expect(await screen.findByText(/Local AI is not running/)).toBeTruthy();
    expect(screen.getByText(/ollama serve/)).toBeTruthy();
  });
});

describe("chat", () => {
  it("sends a clicked example question and renders a verified, cited answer", async () => {
    api.aiChat.mockResolvedValue(chatReply());
    mount();
    fireEvent.click(await screen.findByText("Which skills are holding me back?"));
    await waitFor(() => expect(api.aiChat).toHaveBeenCalledWith("Which skills are holding me back?", null));
    expect(await screen.findByText(/Your official match for ML Engineer is 81.2%/)).toBeTruthy();
    expect(screen.getByText("Checked against your data")).toBeTruthy();
    expect(screen.getByText("Based on your real records")).toBeTruthy();
    fireEvent.click(screen.getByTitle("Show the record behind this statement"));
    expect((await screen.findAllByText(/ML Engineer \(Acme AI\)/)).length).toBeGreaterThanOrEqual(2);   // chip detail + evidence list: the citation resolves to a real record
    expect(screen.getByText(/Verified facts used/)).toBeTruthy();
  });

  it("sends typed questions and passes the previous context back for follow-ups", async () => {
    api.aiChat.mockResolvedValue(chatReply());
    mount();
    const box = await screen.findByPlaceholderText(/Ask a career question/);
    fireEvent.change(box, { target: { value: "How do I match ML Engineer?" } });
    fireEvent.click(screen.getByText("Send"));
    await screen.findByText(/Your official match/);
    fireEvent.change(box, { target: { value: "what about the gaps there?" } });
    fireEvent.click(screen.getByText("Send"));
    await waitFor(() => expect(api.aiChat).toHaveBeenCalledTimes(2));
    expect(api.aiChat.mock.calls[1]).toEqual(["what about the gaps there?", { roles: ["ML Engineer"] }]);
  });

  it("labels hypothetical answers", async () => {
    api.aiChat.mockResolvedValue(chatReply({ hypothetical: true, intent: "what_if", answer: "In this hypothetical scenario the match would be 100.0%." }));
    mount();
    fireEvent.click(await screen.findByText(/What if I learn PyTorch/));
    expect(await screen.findByText(/HYPOTHETICAL - not your real profile/)).toBeTruthy();
    expect(screen.queryByText("Based on your real records")).toBeNull();
  });

  it("explains removed statements instead of hiding them", async () => {
    api.aiChat.mockResolvedValue(chatReply({ verification: { status: "qualified", issues: [{ code: "claimed_skill_not_in_profile", detail: "'PyTorch' is not in your profile records", sentence: "x" }] } }));
    mount();
    fireEvent.click(await screen.findByText("Which skills are holding me back?"));
    expect(await screen.findByText(/could not be verified against your data/)).toBeTruthy();
    expect(screen.getByText("Partly removed - see note")).toBeTruthy();
  });

  it("when the model is unavailable shows the error, instructions and the calculated results (no fake AI answer)", async () => {
    api.aiChat.mockResolvedValue({ ok: false, intent: "match_explain", error: { code: "OLLAMA_UNREACHABLE", message: "Cannot reach Ollama at http://localhost:11434.", instructions: "Start Ollama: ollama serve" }, answer: null, fallback_summary: "ML Engineer: 81.2% match", verification: { status: "skipped", issues: [] }, evidence: [], facts: [], tools: [], notes: [], context: { roles: [] } });
    mount();
    fireEvent.click(await screen.findByText("Which skills are holding me back?"));
    expect(await screen.findByText(/Cannot reach Ollama/)).toBeTruthy();
    expect(screen.getByText(/Calculated results \(no AI explanation available\)/)).toBeTruthy();
    expect(screen.getByText(/ML Engineer: 81.2% match/)).toBeTruthy();
  });

  it("shows a network/auth error without crashing", async () => {
    api.aiChat.mockRejectedValue(new Error("Your session has expired. Please sign in again."));
    mount();
    fireEvent.click(await screen.findByText("Which skills are holding me back?"));
    expect(await screen.findByText(/session has expired/)).toBeTruthy();
  });
});

describe("retrieval diagnostics", () => {
  const retr = (extra) => ({ requested_mode: "hybrid", effective_mode: "hybrid", fallback: false, fallback_reason: null, fallback_message: null, ...extra });

  it("shows keyword retrieval when only BM25 ran", async () => {
    api.aiChat.mockResolvedValue(chatReply({ retrieval: [retr({ requested_mode: "bm25", effective_mode: "bm25" })] }));
    mount();
    fireEvent.click(await screen.findByText("Which skills are holding me back?"));
    expect(await screen.findByText("Retrieval: keyword (BM25)")).toBeTruthy();
  });

  it("shows hybrid only when hybrid really ran", async () => {
    api.aiChat.mockResolvedValue(chatReply({ retrieval: [retr({})] }));
    mount();
    fireEvent.click(await screen.findByText("Which skills are holding me back?"));
    expect(await screen.findByText("Retrieval: hybrid (keyword + semantic)")).toBeTruthy();
  });

  it("never labels a failed hybrid request as hybrid: shows the fallback and its reason", async () => {
    api.aiChat.mockResolvedValue(chatReply({ retrieval: [retr({ effective_mode: "bm25", fallback: true, fallback_reason: "EMBED_MODEL_MISSING", fallback_message: "Embedding model 'nomic-embed-text' is not installed." })] }));
    mount();
    fireEvent.click(await screen.findByText("Which skills are holding me back?"));
    expect(await screen.findByText(/Hybrid unavailable - keyword search used \(EMBED_MODEL_MISSING\)/)).toBeTruthy();
    expect(screen.queryByText("Retrieval: hybrid (keyword + semantic)")).toBeNull();
  });

  it("shows no retrieval pill when no retrieval happened", async () => {
    api.aiChat.mockResolvedValue(chatReply({ retrieval: [] }));
    mount();
    fireEvent.click(await screen.findByText("Which skills are holding me back?"));
    await screen.findByText(/Your official match/);
    expect(screen.queryByText(/Retrieval:/)).toBeNull();
  });
});

describe("what-if simulator", () => {
  it("sends the chosen hypothetical changes and shows baseline vs scenario with causes and limits", async () => {
    api.aiWhatIf.mockResolvedValue({
      hypothetical: true,
      scenario: {
        label: "HYPOTHETICAL SCENARIO - these changes are NOT part of your real profile",
        applied: [{ type: "skill", skill: "PyTorch", via: "claimed skill (self-reported)" }], unresolved: [], assumptions: [], notes: [],
        limitations: ["The official match score only counts WHICH required skills appear in your profile."],
        baseline: { salary: { base_salary_lpa: 13.9 }, roles: { "ML Engineer": { match_percent: 81.2, documented_percent: 46.9 } } },
        scenario: { salary: { projected_salary_lpa: 14.5 }, roles: { "ML Engineer": { match_percent: 100.0, documented_percent: 46.9 } } },
        changes: { salary_delta_lpa: 0.6, roles: { "ML Engineer": { match_delta_pp: 18.8, documented_delta_pp: 0, newly_matched: [{ skill: "PyTorch", importance: 1.2 }], evidence_status_changes: [] } } },
      },
    });
    mount();
    fireEvent.click(await screen.findByText("What-If"));
    fireEvent.click(await screen.findByText("PyTorch"));
    fireEvent.click(screen.getByText("Run simulation"));
    await waitFor(() => expect(api.aiWhatIf).toHaveBeenCalled());
    const body = api.aiWhatIf.mock.calls[0][0];
    expect(body.add_skills).toEqual(["PyTorch"]);
    expect(body.add_projects).toEqual([]);
    expect(body.explain).toBe(false);
    expect(await screen.findByText(/HYPOTHETICAL SCENARIO/)).toBeTruthy();
    expect(screen.getByText("81.2%")).toBeTruthy();
    expect(screen.getByText("100%")).toBeTruthy();
    expect(screen.getByText("14.5 LPA")).toBeTruthy();
    expect(screen.getByText(/requirement/)).toBeTruthy();
    expect(screen.getByText(/Limits of this simulation/)).toBeTruthy();
  });

  it("reports a backend validation error", async () => {
    api.aiWhatIf.mockRejectedValue(new Error("Describe at least one hypothetical change"));
    mount();
    fireEvent.click(await screen.findByText("What-If"));
    fireEvent.click(await screen.findByText("Run simulation"));
    expect(await screen.findByText(/Describe at least one hypothetical change/)).toBeTruthy();
  });
});

describe("evidence and roadmap", () => {
  it("renders evidence statuses and the 'no record is not inability' wording", async () => {
    api.getAIEvidence.mockResolvedValue({
      legend: { documented: "supported by a project or certification record", self_reported_only: "listed, no project", contradictory: "records disagree", no_record: "nothing recorded" },
      assessment_data_available: false,
      skills: [{ skill_id: 1, skill_name: "Python", status: "documented", note: "Supported by 2 project(s).", self_reported: { ref: "candidate_skill:10:1", proficiency: "Advanced", years: 3, recorded_evidence_score: 91 }, contradictions: [], projects: [{ ref: "project:1", title: "AI-SOC Platform" }], certifications: [] },
               { skill_id: 10, skill_name: "Deep Learning", status: "contradictory", note: "The records disagree.", self_reported: null, contradictions: ["Profile says 'Advanced' but the recorded evidence score is 12/100"], projects: [], certifications: [] }],
      required_by_roles_without_record: [{ skill_id: 11, skill_name: "PyTorch" }],
    });
    mount();
    fireEvent.click(await screen.findByText("Evidence"));
    expect(await screen.findByText("AI-SOC Platform", { exact: false })).toBeTruthy();
    expect(screen.getAllByText("Records disagree").length).toBeGreaterThan(0);
    expect(screen.getByText(/not a statement about your ability/)).toBeTruthy();
    expect(screen.getByText("PyTorch")).toBeTruthy();
  });

  it("builds a roadmap with estimates and time-window flags", async () => {
    api.getAIRoadmap.mockResolvedValue({
      assumptions: ["Target role taken from your profile goals ('ML Engineer')."], facts: [],
      roadmap: { role: "ML Engineer", budget_hours: 72, nothing_to_do: false, disclaimer: "Hour figures are rough planning estimates, not promises.",
                 items: [{ step: 1, action: "learn", skill: "PyTorch", reason: "Required skill not in your profile", source: "job requirement (database)", hours_low: 30, hours_high: 60, cumulative_hours: [30, 60], fits_window: "yes", estimated_weeks: [5, 10] }] },
    });
    mount();
    fireEvent.click(await screen.findByText("Roadmap"));
    fireEvent.click(await screen.findByText("Build roadmap"));
    await waitFor(() => expect(api.getAIRoadmap).toHaveBeenCalledWith({ role: "", hoursPerWeek: 6, weeks: 12, explain: false }));
    expect(await screen.findByText(/learn PyTorch/)).toBeTruthy();
    expect(screen.getByText("fits your time")).toBeTruthy();
    expect(screen.getByText(/not promises/)).toBeTruthy();
  });
});
