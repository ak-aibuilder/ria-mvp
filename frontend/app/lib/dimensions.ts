// Static mirror of backend/app/services/audit.py's WEIGHTS + GAP_REASONS +
// GAP_THRESHOLD. Kept here (not fetched) since it's fixed scoring rubric
// metadata the UI needs to render tooltips/legends without a round trip.

export const GAP_THRESHOLD = 6.0;

export type DimensionInfo = {
  code: string;
  name: string;
  weight: number;
  description: string;
};

export const DIMENSIONS: DimensionInfo[] = [
  {
    code: "D1",
    name: "Structured Attribute Completeness",
    weight: 0.25,
    description:
      "Core structured fields present: sku, name, price, category depth, images, brand, attributes.",
  },
  {
    code: "D2",
    name: "Descriptive Richness",
    weight: 0.15,
    description:
      "Description length and whether it covers material/fabric and fit/care/styling detail.",
  },
  {
    code: "D3",
    name: "Conversational Q&A Coverage",
    weight: 0.2,
    description:
      "Presence of well-formed Q&A pairs spanning at least two customer intents (sizing, material, care, occasion, fit, styling).",
  },
  {
    code: "D4",
    name: "Review Signal Presence",
    weight: 0.1,
    description: "Presence of review data with a rating/score/sentiment signal.",
  },
  {
    code: "D5",
    name: "Relational Context",
    weight: 0.15,
    description:
      "Presence of product relationships: often_bought_with, substitute, complementary, accessory_for.",
  },
  {
    code: "D6",
    name: "Agent-Actionable Facets",
    weight: 0.15,
    description:
      "Structured facets (occasion/weather/fit/care/season/color/material) an agent can filter on directly.",
  },
];

export const DIMENSION_BY_CODE: Record<string, DimensionInfo> = Object.fromEntries(
  DIMENSIONS.map((d) => [d.code, d])
);
