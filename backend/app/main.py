"""FastAPI entrypoint.

Only the health check exists at M0. The real API surface (SPEC.md section 8:
/cases, /documents, /run, /report, /reviews, /attest, /packet, /audit, /eval)
is added milestone by milestone, not stubbed ahead of time.
"""

from fastapi import FastAPI

app = FastAPI(title="Credentialing Readiness Agent")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
