# Bug Log — RIA v2

Bugs found after a build step shipped (via user testing, manual QA, or eval
runs) and their fixes. Distinct from [build-log.md](build-log.md), which
records problems hit *during* each build step's own implementation, and from
[model-behavior-log.md](model-behavior-log.md), which tracks LLM-specific
failure modes (FM-1..FM-5), not general app bugs. Maintained as bugs are
found, not on a step cadence.

## Entry Template

```
### YYYY-MM-DD - short title
- **Found by:** user report / self-discovered / eval run
- **Symptom:**
- **Root cause:**
- **Fix:**
- **Files changed:**
- **Verification:**
```

## Entries

### 2026-07-18 - Hydration console error on load
- **Found by:** user report (screenshot of a Next.js "Console Error" overlay)
- **Symptom:** "A tree hydrated but some attributes of the server rendered
  HTML didn't match the client properties" on every page load, flagging
  `data-be-installed="true"` and `style={{width:"100%"}}` on `<html>`.
- **Root cause:** Not app code — a browser extension injects those attributes
  into `<html>` before React hydrates, which is one of the explicitly
  documented causes of this exact React warning.
- **Fix:** Added `suppressHydrationWarning` to the `<html>` element, the
  React/Next.js-recommended mitigation for attributes a third party (not our
  render tree) mutates before hydration.
- **Files changed:** `frontend/app/layout.tsx`
- **Verification:** Live browser reload via `gstack browse`; zero console
  errors on load and after upload.

### 2026-07-18 - Audit table rows gave no way to see full product detail
- **Found by:** user report ("product details ... not clickable ... no way
  of knowing what each product detail is")
- **Symptom:** The audit results table showed sku/name/score/tier/gap-codes
  only. No way to see a product's description, price, category, brand,
  attributes, or *why* a gap dimension was flagged (the gap chips only ever
  showed a bare code like "D3").
- **Root cause:** Two layers. (1) Frontend: `AuditResults` rendered a flat,
  non-interactive table row. (2) Backend: `scored_entry()` only returned the
  compact score row (sku/name/score/dims/gaps/tier) — the raw catalog fields
  needed for a detail view weren't in the `/pipeline/start` response at all,
  so there was no data to expand into even if the row were clickable.
- **Fix:** `scored_entry()` now also returns description/price/category/
  brand/attributes/image_urls. `AuditResults` rows are clickable
  (`cursor:pointer`, hover highlight) and toggle an inline detail row with
  the full product fields, a per-dimension score breakdown, and the full gap
  reason text (previously only the gap *code* was shown anywhere).
- **Files changed:** `backend/app/services/pipeline.py`,
  `frontend/app/components/AuditResults.tsx`, `frontend/app/lib/api.ts`
  (`ScoredProduct` type)
- **Verification:** Live browser click-through; expanded row rendered
  description/category/brand/price/attributes/dimension scores/gap reasons
  correctly for a real uploaded catalog. Zero console errors.

### 2026-07-18 - No explanation of what D1–D6 dimensions mean
- **Found by:** user report (wanted tooltips "like it was in RIA v1")
- **Symptom:** The audit table's gap chips (D1..D6) and dimension scores had
  no explanation anywhere in the UI of what each dimension measures, its
  weight, or why a gap threshold applies.
- **Root cause:** Missing feature — this metadata only existed in the
  backend (`audit.py`'s `WEIGHTS` + `GAP_REASONS`) and was never surfaced.
- **Fix:** Added `frontend/app/lib/dimensions.ts` (a static mirror of the
  backend's weights/descriptions/gap threshold), a reusable `Tooltip`
  component (CSS hover/focus bubble, no new dependency), a collapsible
  "What do D1–D6 mean?" legend at the top of the audit table listing all six
  dimensions with weight + description, and per-gap-chip / per-dimension-row
  hover tooltips showing the dimension name and (for gaps) the specific
  reason it was flagged.
- **Files changed:** `frontend/app/lib/dimensions.ts` (new),
  `frontend/app/components/Tooltip.tsx` (new),
  `frontend/app/components/AuditResults.tsx`, `frontend/app/globals.css`
- **Verification:** Live browser click-through; legend expand and tooltip
  hover both rendered correct content. Zero console errors.
