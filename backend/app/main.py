"""FastAPI entrypoint.

The real API surface (SPEC.md section 8: /cases, /documents, /run,
/report, /reviews, /attest, /packet, /audit, /eval) is added milestone by
milestone, not stubbed ahead of time. M4 added the intake slice (create
case, checklist, upload document); M8 added /run, /report, /reviews,
/attest, /packet; M9 adds /audit, /eval/latest, and CORS for the
frontend dev server.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.audit import router as audit_router
from app.api.cases import router as cases_router
from app.api.eval_endpoint import router as eval_router
from app.api.middleware import MaxContentLengthMiddleware
from app.api.reviews import router as reviews_router
from app.core.config import settings

app = FastAPI(title="Credentialing Readiness Agent")
# Rejects on a too-large Content-Length before Starlette's multipart
# parser (triggered by any route's `UploadFile` parameter) reads a
# single byte of the body - app/api/middleware.py explains why this
# can't be done inside the route handler itself.
app.add_middleware(MaxContentLengthMiddleware, max_bytes=settings.max_upload_size_bytes)
# Demo-grade (README states this plainly): the Vite dev server and a
# static-file preview both run on localhost at a different port than
# the API, so the browser needs CORS to call it at all. Real auth is
# the X-Provider-Token/X-Reviewer-Token headers (app/api/auth.py), not
# origin checking - this is permissive on purpose for a local demo.
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"http://localhost:\d+",
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(cases_router)
app.include_router(reviews_router)
app.include_router(audit_router)
app.include_router(eval_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
