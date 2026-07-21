from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse

from edgecraft import __version__
from edgecraft.ledger import AuditLedger
from edgecraft.observability import autonomy_health, control_plane_snapshot, prometheus_metrics

app = FastAPI(
    title="Edgecraft API",
    version=__version__,
    description="Read-only operational view of the autonomous trading ledger.",
)


@app.middleware("http")
async def security_headers(request, call_next):
    response = await call_next(request)
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self'; "
        "img-src 'self' data:; connect-src 'self'; object-src 'none'; "
        "base-uri 'none'; frame-ancestors 'none'; form-action 'none'"
    )
    response.headers["Permissions-Policy"] = "camera=(), geolocation=(), microphone=()"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    return response


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


@app.get("/api/autonomy/health")
def autonomous_health() -> dict:
    return autonomy_health(AuditLedger(os.getenv("EDGECRAFT_LEDGER", "state/edgecraft.db")))


@app.get("/api/control-plane")
def control_plane() -> dict:
    return control_plane_snapshot(AuditLedger(os.getenv("EDGECRAFT_LEDGER", "state/edgecraft.db")))


@app.get("/api/trades/{order_key}")
def trade_detail(order_key: str) -> dict:
    try:
        return AuditLedger(os.getenv("EDGECRAFT_LEDGER", "state/edgecraft.db")).trade_audit(
            order_key
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/metrics", response_class=PlainTextResponse)
def metrics() -> str:
    return prometheus_metrics(AuditLedger(os.getenv("EDGECRAFT_LEDGER", "state/edgecraft.db")))


frontend_dist = Path(__file__).resolve().parents[2] / "frontend"
if (frontend_dist / "index.html").exists():

    @app.get("/{path:path}")
    def spa(path: str):
        candidate = frontend_dist / ("src/styles.css" if path == "styles.css" else path)
        if path in {"app.js", "styles.css"} and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(frontend_dist / "index.html")
