import { EnrichResponse } from "../lib/api";
import TierChart from "./TierChart";

export default function EnrichmentResults({
  data,
  onConfirmValidate,
  confirming,
  error,
  validateEnabled,
}: {
  data: EnrichResponse;
  onConfirmValidate: () => void;
  confirming: boolean;
  error: string | null;
  validateEnabled: boolean;
}) {
  const before = data.before.tier_distribution;
  const after = data.after.tier_distribution;
  const total = data.after.product_count;
  const nsmBefore = total
    ? (((before.II ?? 0) + (before.III ?? 0)) / total) * 100
    : 0;
  const nsmAfter = total
    ? (((after.II ?? 0) + (after.III ?? 0)) / total) * 100
    : 0;
  const em = data.token_metrics.enrichment;

  return (
    <section className="card">
      <h2>
        <span className="step-badge">3</span> Enrichment Results
      </h2>
      <p className="subtitle">
        {data.report.succeeded} products enriched
        {data.report.failed ? `, ${data.report.failed} failed` : ""}.
      </p>

      <TierChart distribution={after} before={before} />
      <p className="nsm">
        Catalog Agent-Readiness Rate: <strong>{nsmBefore.toFixed(1)}%</strong>{" "}
        → <strong>{nsmAfter.toFixed(1)}%</strong>
      </p>

      <div className="metrics-row">
        <div className="metric">
          <div className="label">Enrichment calls</div>
          <div className="value">{em.calls}</div>
        </div>
        <div className="metric">
          <div className="label">Total tokens</div>
          <div className="value">{em.total_tokens.toLocaleString()}</div>
        </div>
        <div className="metric">
          <div className="label">Cost</div>
          <div className="value">${em.cost_usd.toFixed(4)}</div>
        </div>
      </div>

      <div style={{ marginTop: "1.25rem" }}>
        {data.enriched_products.map((p) => (
          <details className="product-diff" key={p.sku}>
            <summary>
              <span>{p.sku}</span>
              <span className={`status-pill ${p.enrichment_status}`}>
                {p.enrichment_status}
              </span>
            </summary>
            <div className="diff-grid">
              <div className="diff-col">
                <h4>Before</h4>
                <p>{p.original_fields.description || "(no description)"}</p>
              </div>
              <div className="diff-col">
                <h4>After</h4>
                <p>
                  {p.enriched_fields.description ||
                    p.original_fields.description ||
                    "(unchanged)"}
                </p>
                {p.enriched_fields.agent_facets && (
                  <p>
                    <strong>Facets:</strong>{" "}
                    {Object.entries(p.enriched_fields.agent_facets)
                      .map(([k, v]) => `${k}=${Array.isArray(v) ? v.join("/") : v}`)
                      .join(", ")}
                  </p>
                )}
                {p.enriched_fields.q_and_a && (
                  <p>
                    <strong>Q&amp;A:</strong> {p.enriched_fields.q_and_a.length}{" "}
                    pairs
                  </p>
                )}
                {p.enriched_fields.relationship_type && (
                  <p>
                    <strong>Relationships:</strong>{" "}
                    {p.enriched_fields.relationship_type.length}
                  </p>
                )}
              </div>
            </div>
          </details>
        ))}
      </div>

      <div className="gate">
        {validateEnabled ? (
          <span className="gate-done">✓ Validation enabled</span>
        ) : (
          <button
            className="primary"
            onClick={onConfirmValidate}
            disabled={confirming}
          >
            {confirming ? "Enabling…" : "Gate 2 — Confirm Validation →"}
          </button>
        )}
        {error && <span className="error-text">{error}</span>}
      </div>
    </section>
  );
}
