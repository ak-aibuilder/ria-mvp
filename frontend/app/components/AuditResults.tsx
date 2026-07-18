"use client";

import { Fragment, useState } from "react";
import { ScoredProduct, StartResponse } from "../lib/api";
import { DIMENSIONS, DIMENSION_BY_CODE, GAP_THRESHOLD } from "../lib/dimensions";
import TierChart from "./TierChart";
import Tooltip from "./Tooltip";

const TIER_PILL_COLOR: Record<string, string> = {
  "0": "var(--tier-0)",
  I: "var(--tier-I)",
  II: "var(--tier-II)",
  III: "var(--tier-III)",
};

function ProductDetail({ product }: { product: ScoredProduct }) {
  const attrs = product.attributes || {};
  const attrEntries = Object.entries(attrs);
  return (
    <div className="detail-grid">
      <div className="detail-full">
        <h4>Product</h4>
        <p>
          {product.description || "(no description)"}
          <br />
          {product.category && <>Category: {product.category} · </>}
          {product.brand && <>Brand: {product.brand} · </>}
          {product.price != null && <>Price: ${product.price}</>}
        </p>
        {attrEntries.length > 0 && (
          <ul className="attr-list">
            {attrEntries.map(([k, v]) => (
              <li key={k}>
                {k}: {Array.isArray(v) ? v.join(", ") : String(v)}
              </li>
            ))}
          </ul>
        )}
      </div>
      <div>
        <h4>Dimension Scores</h4>
        {DIMENSIONS.map((d) => (
          <div className="dim-score-row" key={d.code}>
            <Tooltip
              label={
                <>
                  <strong>
                    {d.code} · {d.name}
                  </strong>{" "}
                  (weight {d.weight})
                  <br />
                  {d.description}
                </>
              }
            >
              <span>
                {d.code} <span className="info-icon">i</span>
              </span>
            </Tooltip>
            <span>{(product.dimension_scores[d.code] ?? 0).toFixed(1)} / 10</span>
          </div>
        ))}
      </div>
      <div>
        <h4>Gaps (below {GAP_THRESHOLD.toFixed(1)} threshold)</h4>
        {product.gaps.length === 0 && <p>No gaps — every dimension clears threshold.</p>}
        {product.gaps.map((g) => (
          <p className="gap-reason-item" key={g.dimension}>
            <span className={`sev-${g.severity}`}>
              {g.dimension} · {DIMENSION_BY_CODE[g.dimension]?.name ?? g.dimension} (
              {g.severity})
            </span>
            <br />
            {g.reason}
          </p>
        ))}
      </div>
    </div>
  );
}

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
  const [expandedSku, setExpandedSku] = useState<string | null>(null);
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

      <details className="dimension-legend">
        <summary>What do D1–D6 mean, and how is the score computed?</summary>
        <p>
          Readiness score is a weighted sum of six 0–10 dimension scores. A
          dimension below {GAP_THRESHOLD.toFixed(1)} is flagged as a gap for
          that product.
        </p>
        <div className="dimension-legend-grid">
          {DIMENSIONS.map((d) => (
            <div className="dimension-legend-item" key={d.code}>
              <span className="dim-name">
                {d.code} · {d.name}
              </span>
              <span className="dim-meta">weight {d.weight}</span>
              {d.description}
            </div>
          ))}
        </div>
      </details>

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
          {data.scored_products.map((p) => {
            const isOpen = expandedSku === p.sku;
            return (
              <Fragment key={p.sku}>
                <tr
                  className="clickable-row"
                  onClick={() => setExpandedSku(isOpen ? null : p.sku)}
                >
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
                      <Tooltip
                        key={g.dimension}
                        label={
                          <>
                            <strong>
                              {g.dimension} ·{" "}
                              {DIMENSION_BY_CODE[g.dimension]?.name ?? g.dimension}
                            </strong>
                            <br />
                            {g.reason}
                          </>
                        }
                      >
                        <span className={`gap-chip ${g.severity}`}>{g.dimension}</span>
                      </Tooltip>
                    ))}
                  </td>
                </tr>
                {isOpen && (
                  <tr className="detail-row">
                    <td colSpan={5}>
                      <ProductDetail product={p} />
                    </td>
                  </tr>
                )}
              </Fragment>
            );
          })}
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
