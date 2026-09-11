from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pathlib import Path

from .routers.evaluation import router as eval_router
from .routers.evaluation_human_v5 import router as human_eval_v5_router
from .routers.expense import router as expense_router
from .routers.inbox import router as inbox_router
from .routers.schedule import router as schedule_router

app = FastAPI(title="administrative-agent", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.exception_handler(Exception)
async def unhandled_exception(request: Request, exc: Exception) -> JSONResponse:
    """Surface unhandled errors (LLM rate limits, provider outages) as readable JSON so
    the UI can show *why* a call failed instead of a bare 'Internal Server Error'."""
    return JSONResponse(status_code=500,
                        content={"detail": f"{type(exc).__name__}: {exc}"})


app.include_router(expense_router)
app.include_router(eval_router)
app.include_router(human_eval_v5_router)
app.include_router(schedule_router)
app.include_router(inbox_router)

# ── Frontend ──────────────────────────────────────────────────────────────────────────
# There is one production UI: the built React SPA. Missing build output is a deployment
# error, not a reason to silently run a stale implementation with different contracts.
_web_dir = (Path(__file__).resolve().parent.parent / "frontend-next" / "dist").resolve()


@app.get("/health")
async def health_check():
    return {"status": "ok", "project": "administrative-agent", "frontend": "spa"}


# Catch-all LAST: serve a real file when the path names one, else index.html so the SPA's
# client-side routes (/inbox, /eval/wf1, …) survive a hard refresh. /api/* is excluded so an
# unknown endpoint still 404s as JSON instead of silently returning the HTML shell.
@app.get("/{path:path}")
async def serve_frontend(path: str = ""):
    if path.startswith("api/"):
        raise HTTPException(status_code=404, detail="Not found")
    candidate = (_web_dir / path).resolve()
    if path and candidate.is_relative_to(_web_dir) and candidate.is_file():
        return FileResponse(candidate)
    index = _web_dir / "index.html"
    if not index.is_file():
        raise HTTPException(status_code=503, detail="frontend build missing; run npm run build")
    return FileResponse(index)
