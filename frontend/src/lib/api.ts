const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

function headers(): HeadersInit {
  const h: HeadersInit = { "Content-Type": "application/json" };
  const key = localStorage.getItem("gemini_api_key");
  if (key) h["X-Gemini-Key"] = key;
  return h;
}

async function get<T = unknown>(path: string): Promise<T> {
  const res = await fetch(`${API_URL}${path}`);
  if (!res.ok) throw new Error(`${res.status}: ${await res.text()}`);
  return res.json();
}

async function post<T = unknown>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    method: "POST",
    headers: headers(),
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) throw new Error(`${res.status}: ${await res.text()}`);
  return res.json();
}

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

export interface ToolCallRecord {
  name: string;
  args: Record<string, string>;
  result_preview: string;
}

export interface ChatResponse {
  response: string;
  tool_calls: ToolCallRecord[];
  model: string;
}

export const api = {
  // Health
  health: () => get<{ status: string }>("/health"),

  // Tools
  listTools: () => get<{ tools: { name: string; description: string }[]; count: number }>("/tools"),
  runTool: (tool: string, intervention: string) =>
    get<Record<string, unknown>>(`/tools/${tool}/${intervention}`),

  // Landscape (all interventions + evidence scores in one call)
  landscapeScores: () =>
    get<{ interventions: { name: string; document_count: number; confidence: number; source_types: number }[]; count: number }>("/tools/landscape/scores"),

  // Interventions
  listInterventions: () =>
    get<{ interventions: { name: string; document_count: number }[]; total: number }>("/interventions"),
  getStats: (name: string) => get<Record<string, unknown>>(`/interventions/${name}/stats`),
  getTimeline: (name: string) => get<Record<string, unknown>>(`/interventions/${name}/timeline`),

  // Pharma
  listPharma: () => get<{ profiles: Record<string, unknown>[]; count: number }>("/pharma/profiles"),
  getPharma: (name: string) => get<Record<string, unknown>>(`/pharma/profiles/${name}`),
  listBiotech: () => get<{ profiles: Record<string, unknown>[]; count: number }>("/biotech/profiles"),
  getBiotech: (name: string) => get<Record<string, unknown>>(`/biotech/profiles/${name}`),
  runPharmaDd: (name: string) => post<Record<string, unknown>>(`/pharma/dd/${name}`),

  // Chat
  chat: (messages: ChatMessage[]) => post<ChatResponse>("/chat", { messages }),
};
