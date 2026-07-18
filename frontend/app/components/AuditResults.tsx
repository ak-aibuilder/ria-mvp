import { StartResponse } from "../lib/api";
import TierChart from "./TierChart";

const TIER_PILL_COLOR: Record<string, string> = {
  "0": "var(--tier-0)",
  I: "var(--tier-I)",
  II: "var(--tier-II)",
  III: "var(--tier-III)",
};

export default function AuditResults({
  data,
  onConfirmEnrich,
  enriching,
  error,
  alreadyEnriched,
}: {
  data: StartResponse;
  onConfirmEnrich: () => void;
  enriching: boolean;
  error: string | null;
  alreadyEnriched: boolean;
}) {
  const readyCount =
    (data.tier_distribution.II ?? 0) + (data.tier_distribution.III ?? 0);
  const nsm = data.product_count
    ? ((readyCount / data.product_count) * 100).toFixed(1)
    : "0.0";

  return (
    <section className="card">
      <h2>
        <span className="step-badge">2</span> Audit Results
      </h2>
      <p className="subtitle">
        {data.report.rows_parsed} rows parsed
        {data.report.rows_dropped
          ? `, ${data.report.rows_dropped} dropped`
          : ""}
        {data.report.duplicate_count
          ? `, ${data.report.duplicate_count} duplicate variants merged`
          : ""}
        . {data.product_count} products scored.
      </p>

      <TierChart distribution={data.tier_distribution} />
      <p className="nsm">
        Catalog Agent-Readiness Rate: <strong>{nsm}%</strong> ({readyCount}/
        {data.product_count} at Tier II+)
      </p>

      <table>
        <thead>
          <tr>
            <th>SKU</th>
            <th>Name</th>
            <th>Score</th>
            <th>Tier</th>
            <th>Gaps</th>
          </tr>
        </thead>
        <tbody>
          {data.scored_products.map((p) => (
            <tr key={p.sku}>
              <td>{p.sku}</td>
              <td>{p.name}</td>
              <td>{p.readiness_score.toFixed(1)}</td>
              <td>
                <span
                  className="tier-pill"
                  style={{ background: TIER_PILL_COLOR[p.tier] }}
                >
                  {p.tier} · {p.label}
                </span>
              </td>
              <td>
                {p.gaps.map((g) => (
                  <span key={g.dimension} className={`gap-chip ${g.severity}`}>
                    {g.dimension}
                  </span>
                ))}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <div className="gate">
        {alreadyEnriched ? (
          <span className="gate-done">✓ Enrichment confirmed</span>
        ) : (
          <button
            className="primary"
            onClick={onConfirmEnrich}
            disabled={enriching}
          >
            {enriching ? "Enriching…" : "Gate 1 — Confirm Enrichment →"}
          </button>
        )}
        {error && <span className="error-text">{error}</span>}
      </div>
    </section>
  );
}
