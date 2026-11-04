"""FastAPI entrypoint.

The real API surface (SPEC.md section 8: /cases, /documents, /run,
/report, /reviews, /attest, /packet, /audit, /eval) is added milestone by
milestone, not stubbed ahead of time. M4 added the intake slice (create
case, checklist, upload document); M8 adds /run, /report, /reviews,
/attest, /packet.
"""

from fastapi import FastAPI

from app.api.cases import router as cases_router
from app.api.middleware import MaxContentLengthMiddleware
from app.api.reviews import router as reviews_router
from app.core.config import settings

app = FastAPI(title="Credentialing Readiness Agent")
# Rejects on a too-large Content-Length before Starlette's multipart
# parser (triggered by any route's `UploadFile` parameter) reads a
# single byte of the body - app/api/middleware.py explains why this
# can't be done inside the route handler itself.
app.add_middleware(MaxContentLengthMiddleware, max_bytes=settings.max_upload_size_bytes)
app.include_router(cases_router)
app.include_router(reviews_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
