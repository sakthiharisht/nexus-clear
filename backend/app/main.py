"""FastAPI entrypoint.

The real API surface (SPEC.md section 8: /cases, /documents, /run,
/report, /reviews, /attest, /packet, /audit, /eval) is added milestone by
milestone, not stubbed ahead of time. M4 adds the intake slice:
create case, checklist, upload document.
"""

from fastapi import FastAPI

from app.api.cases import router as cases_router

app = FastAPI(title="Credentialing Readiness Agent")
app.include_router(cases_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
