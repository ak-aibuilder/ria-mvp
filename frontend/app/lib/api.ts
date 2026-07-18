// Typed client for the RIA v2 backend (goals.md §7 endpoints). One function
// per endpoint the pipeline UI calls; shapes mirror the FastAPI response
// bodies in backend/app/api/v1/{pipeline,validate}.py.

const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000/api/v1";

export type Tier = "III" | "II" | "I" | "0";
export const TIER_ORDER: Tier[] = ["0", "I", "II", "III"];
export const TIER_LABELS: Record<Tier, string> = {
  "0": "Not Agent Ready",
  I: "Markup Ready",
  II: "API Ready",
  III: "Graph Ready",
};

export type Gap = {
  dimension: string;
  severity: "high" | "medium" | "low";
  reason: string;
};

export type ScoredProduct = {
  sku: string;
  name: string | null;
  readiness_score: number;
  dimension_scores: Record<string, number>;
  gaps: Gap[];
  tier: Tier;
  label: string;
};

export type TierDistribution = Record<Tier, number>;

export type AuditView = {
  scored_products: ScoredProduct[];
  tier_distribution: TierDistribution;
  product_count: number;
};

export type StartResponse = AuditView & {
  session_id: string;
  phase: string;
  report: {
    rows_parsed: number;
    rows_dropped: number;
    duplicate_count: number;
    alias_mapping: Record<string, string>;
  };
};

export type QAndA = {
  question: string;
  answer: string;
  intent?: string;
  speculative?: boolean;
};

export type Relationship = {
  related_sku: string;
  relationship_type: string;
  rationale?: string;
};

export type EnrichedProductRow = {
  sku: string;
  original_fields: {
    name?: string | null;
    description?: string | null;
    price?: number | null;
    category?: string | null;
    brand?: string | null;
    image_urls?: string[] | null;
    attributes?: Record<string, unknown> | null;
  };
  enriched_fields: {
    description?: string;
    q_and_a?: QAndA[];
    agent_facets?: Record<string, unknown>;
    relationship_type?: Relationship[];
  };
  confidence_scores: Record<string, number>;
  enrichment_status: string;
  audit_trail: unknown[];
};

export type TokenAggregate = {
  calls: number;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  cost_usd: number;
};

export type EnrichResponse = {
  session_id: string;
  phase: string;
  before: { tier_distribution: TierDistribution };
  after: AuditView;
  enriched_products: EnrichedProductRow[];
  report: { succeeded: number; failed: number };
  token_metrics: {
    enrichment: TokenAggregate;
    per_product: Record<string, TokenAggregate>;
  };
};

export type ConfirmValidateResponse = {
  session_id: string;
  phase: string;
  validation_enabled: boolean;
};

export type ToolCall = {
  name: string;
  args: Record<string, unknown>;
  result: Record<string, unknown>;
  via?: string;
};

export type AgentTranscript = {
  index_type: "pre" | "post";
  query_text: string;
  tool_calls: ToolCall[];
  tool_call_count: number;
  skus_examined: string[];
  agent_response: string;
  turns_used: number;
  terminator: string;
  fallback_fired: boolean;
  cart_preview: unknown[];
  checkout_intent: Record<string, unknown> | null;
};

export type QueryComparison = {
  pre: TokenAggregate;
  post: TokenAggregate;
  token_reduction_pct: number;
  cost_reduction_pct: number;
};

export type CompareResponse = {
  session_id: string;
  query: string;
  query_comparison: QueryComparison;
  pre: AgentTranscript;
  post: AgentTranscript;
};

async function handle<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = res.statusText || `HTTP ${res.status}`;
    try {
      const body = await res.json();
      detail =
        typeof body.detail === "string"
          ? body.detail
          : JSON.stringify(body.detail ?? body);
    } catch {
      // no JSON body — keep statusText
    }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

export async function startPipeline(file: File): Promise<StartResponse> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${API_BASE}/pipeline/start`, {
    method: "POST",
    body: form,
  });
  return handle<StartResponse>(res);
}

export async function confirmEnrich(sessionId: string): Promise<EnrichResponse> {
  const res = await fetch(`${API_BASE}/pipeline/confirm-enrich`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId }),
  });
  return handle<EnrichResponse>(res);
}

export async function confirmValidate(
  sessionId: string
): Promise<ConfirmValidateResponse> {
  const res = await fetch(`${API_BASE}/pipeline/confirm-validate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId }),
  });
  return handle<ConfirmValidateResponse>(res);
}

export async function compareQuery(
  sessionId: string,
  query: string
): Promise<CompareResponse> {
  const res = await fetch(`${API_BASE}/validate/compare`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId, query }),
  });
  return handle<CompareResponse>(res);
}

// Exports (goals.md §12) ship in Step 6 — the URL contract is fixed now so the
// UI can wire real buttons, but the route doesn't exist on the backend yet.
export type ExportFormat = "ucp_supplemental" | "acp_feed" | "asa_readiness" | "enriched_csv";

export function exportUrl(sessionId: string, format: ExportFormat): string {
  return `${API_BASE}/exports/${sessionId}/${format}`;
}
