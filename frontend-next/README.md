# Administrative Agent frontend

The only supported UI is this React 19 + TypeScript + Vite SPA. FastAPI serves the committed
production build from `dist/`; there is no legacy frontend or runtime fallback.

## Commands

```bash
npm ci
npx tsc --noEmit
npm run build
```

For local hot reload, run `npm run dev`; Vite proxies `/api` to the FastAPI server on
`127.0.0.1:8000`. Production changes are not visible until `npm run build` refreshes `dist/`.

## Structure

- `src/pages/`: Overview, Inbox (WF1), Calendar (WF2), Expenses (WF3), Evaluation.
- `src/components/`: shared accessible controls and the business-aware date/time fields.
- `src/lib/api.ts`: the current typed API contract; do not add compatibility calls to removed
  endpoints.
- `smoke.mjs`: route, theme, chart and horizontal-overflow browser checks.

WF3 uses only the evidence-first lifecycle: receipt bytes are persisted, immutable extraction
and submission snapshots are stored, a second person reviews them, and deterministic policy
checks run again before a versioned decision.
