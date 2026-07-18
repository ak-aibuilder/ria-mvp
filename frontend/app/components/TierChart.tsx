import { TIER_LABELS, TIER_ORDER, TierDistribution } from "../lib/api";

const TIER_COLOR: Record<string, string> = {
  "0": "var(--tier-0)",
  I: "var(--tier-I)",
  II: "var(--tier-II)",
  III: "var(--tier-III)",
};

export default function TierChart({
  distribution,
  before,
}: {
  distribution: TierDistribution;
  /** When provided, renders a paired before/after bar per tier. */
  before?: TierDistribution;
}) {
  const max = Math.max(
    1,
    ...TIER_ORDER.map((t) => distribution[t] ?? 0),
    ...(before ? TIER_ORDER.map((t) => before[t] ?? 0) : [])
  );

  return (
    <div>
      {before && (
        <div className="legend">
          <span>
            <span
              className="legend-swatch"
              style={{ background: "var(--text-dim)", opacity: 0.45 }}
            />
            Before
          </span>
          <span>
            <span className="legend-swatch" style={{ background: "var(--text-dim)" }} />
            After
          </span>
        </div>
      )}
      <div className="tier-chart">
        {TIER_ORDER.map((tier) => {
          const count = distribution[tier] ?? 0;
          const beforeCount = before?.[tier] ?? 0;
          return (
            <div className="tier-col" key={tier}>
              <div className="tier-bars">
                {before && (
                  <div
                    className="tier-bar before"
                    style={{
                      height: `${(beforeCount / max) * 100}%`,
                      background: TIER_COLOR[tier],
                    }}
                  >
                    <span className="tier-bar-count">{beforeCount || ""}</span>
                  </div>
                )}
                <div
                  className="tier-bar"
                  style={{
                    height: `${(count / max) * 100}%`,
                    background: TIER_COLOR[tier],
                  }}
                >
                  <span className="tier-bar-count">{count}</span>
                </div>
              </div>
              <div className="tier-col-label">
                Tier {tier}
                <br />
                {TIER_LABELS[tier]}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
