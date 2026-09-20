import { supabase } from "./supabase";

const BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export type IngestStatus = "pending" | "extracting" | "ok" | "degraded" | "failed";

export interface IngestReport {
  status: string;
  reasons: string[];
  needs_ocr: boolean;
  mean_arabic_ratio?: number;
  mean_fragmentation_ratio?: number;
}

export interface Resource {
  id: string;
  title: string;
  type: string;
  author: string | null;
  level_hint: string | null;
  position_value: number | null;
  position_unit: string | null;
  total_length: number | null;
  ingest_status: IngestStatus;
  ingest_report: IngestReport;
  created_at: string | null;
}

export interface KeyPoint {
  id: string;
  text: string;
}

export interface Question {
  item_id: string;
  resource_id: string;
  question_arabic: string;
  question_english: string;
  difficulty_cefr: string;
  key_points: KeyPoint[];
}

export interface ErrorTag {
  category: string;
  subcategory: string;
  span: string;
  correction: string | null;
  explanation: string;
  severity: "minor" | "moderate" | "blocking";
}

export interface Grade {
  gradable: boolean;
  ungradable_reason: string | null;
  content_score: number;
  language_score: number;
  final_score: number;
  key_point_verdicts: { id: string; status: string; why: string }[];
  errors: ErrorTag[];
  feedback: string;
}

/** Thrown for any non-2xx response, carrying the server's own detail message. */
export class ApiError extends Error {
  // Declared explicitly rather than as constructor parameter properties:
  // the tsconfig sets erasableSyntaxOnly, which forbids that shorthand.
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }

  /** 409 means the position gate has nothing to offer, or no groundable
   *  question could be produced. Expected, not a fault — worth showing
   *  differently from a real error. */
  get isNoContent() {
    return this.status === 409;
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const { data } = await supabase.auth.getSession();
  const token = data.session?.access_token;
  if (!token) throw new ApiError(401, "Not signed in.");

  const headers = new Headers(init.headers);
  headers.set("Authorization", `Bearer ${token}`);
  if (init.body && !(init.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }

  const response = await fetch(`${BASE}${path}`, { ...init, headers });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail = body.detail ?? detail;
    } catch {
      /* non-JSON error body; keep the status text */
    }
    throw new ApiError(response.status, detail);
  }
  return response.status === 204 ? (undefined as T) : response.json();
}

export interface SkillEstimate {
  skill: string;
  cefr_level: string | null;
  confidence: number;
  n_observations: number;
  sufficient: boolean;
}

export interface WeakSpot {
  category: string;
  subcategory: string;
  count: number;
  severity_mix: Record<string, number>;
}

export interface Overview {
  attempts_total: number;
  attempts_7d: number;
  mean_content_score: number | null;
  mean_language_score: number | null;
  streak_days: number;
  estimates: SkillEstimate[];
  weak_spots: WeakSpot[];
  activity: { date: string; count: number }[];
  vocab_total: number;
  vocab: VocabStats;
  cost_usd_total: number;
}

export interface VocabCard {
  id: string;
  arabic: string;
  root: string | null;
  pos: string | null;
  translation: string;
  context_sentence: string | null;
  resource_id: string | null;
}

export interface HarvestResult {
  added: number;
  skipped_duplicates: number;
  /** Found, but discarded as damaged by PDF extraction. */
  rejected_damaged: number;
  items: VocabCard[];
}

export interface DeckCard {
  id: string;
  kind: "vocab" | "error_tag";
  front: string;
  back: string;
  hint: string | null;
  reps: number;
  lapses: number;
  due_at: string;
  resting: boolean;
}

export interface DeckState {
  cards: DeckCard[];
  due_now: number;
  resting: number;
  retired: number;
  total: number;
}

export interface VocabStats {
  total: number;
  known: number;
  due_now: number;
  retired: number;
  retention_rate: number | null;
  total_reviews: number;
  by_resource: { title: string; count: number }[];
}

export interface ReviewCard {
  id: string;
  kind: "vocab" | "error_tag";
  front: string;
  back: string;
  hint: string | null;
  reps: number;
  lapses: number;
  due_at: string;
}

export interface ReviewResult {
  next_due_at: string;
  interval_days: number;
  reps: number;
  lapses: number;
  retired: boolean;
}

export interface QueueStats {
  due_now: number;
  total_active: number;
  retired: number;
}

export const api = {
  deck: (includeResting = false) =>
    request<DeckState>(`/review/deck?include_resting=${includeResting}`),

  resetDeck: () => request<DeckState>("/review/reset", { method: "POST" }),

  resourceFileUrl: (id: string) =>
    request<{ url: string }>(`/resources/${id}/file`),

  reviewDue: (limit = 20) => request<ReviewCard[]>(`/review/due?limit=${limit}`),

  reviewStats: () => request<QueueStats>("/review/stats"),

  gradeReview: (cardId: string, score: number) =>
    request<ReviewResult>("/review/grade", {
      method: "POST",
      body: JSON.stringify({ card_id: cardId, score }),
    }),

  enqueueVocab: () => request<QueueStats>("/review/enqueue-vocab", { method: "POST" }),

  vocabDeck: (resourceId?: string) =>
    request<VocabCard[]>(`/vocab/deck${resourceId ? `?resource_id=${resourceId}` : ""}`),

  harvestVocab: (resourceId: string) =>
    request<HarvestResult>(`/vocab/harvest?resource_id=${resourceId}`, { method: "POST" }),

  overview: () => request<Overview>("/metrics/overview"),

  me: () => request<{ id: string; email: string | null }>("/me"),

  listResources: () => request<Resource[]>("/resources"),

  getResource: (id: string) => request<Resource>(`/resources/${id}`),

  uploadPdf: (file: File, title: string, positionValue: number, author?: string) => {
    const form = new FormData();
    form.append("file", file);
    form.append("title", title);
    form.append("position_value", String(positionValue));
    if (author) form.append("author", author);
    return request<Resource>("/resources/upload", { method: "POST", body: form });
  },

  deleteResource: (id: string) =>
    request<void>(`/resources/${id}`, { method: "DELETE" }),

  updatePosition: (id: string, positionValue: number) =>
    request<Resource>(`/resources/${id}/position`, {
      method: "PATCH",
      body: JSON.stringify({ position_value: positionValue }),
    }),

  nextQuestion: (resourceId?: string) =>
    request<Question>(
      `/learning/next${resourceId ? `?resource_id=${resourceId}` : ""}`,
    ),

  submitAnswer: (itemId: string, answer: string) =>
    request<Grade>("/learning/answer", {
      method: "POST",
      body: JSON.stringify({ item_id: itemId, answer }),
    }),
};
