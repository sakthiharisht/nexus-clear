"""Demo-grade auth (pre-M9 fix #4; SPEC.md section 8: "a role switch
(provider | reviewer), no real auth in MVP"). Two roles, proven by
possessing a token - nothing more:

- provider: a per-case token (app/core/orm.py's Case.provider_token),
  generated once at case creation and returned only in that response.
  Proves "whoever is calling this knows the token this specific case
  was created with" - not a real identity.
- reviewer: one shared secret (settings.reviewer_token) across every
  case - there is exactly one reviewer role in this demo.

Not a substitute for real authentication/authorization. No sessions,
no expiry, no per-user accounts. README (M9) states this plainly.
"""

from __future__ import annotations

import secrets
from uuid import UUID

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_session
from app.core.config import settings
from app.core.orm import Case


def require_provider_token(
    case_id: UUID,
    x_provider_token: str = Header(...),
    session: Session = Depends(get_session),
) -> Case:
    case = session.get(Case, case_id)
    if case is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"case {case_id} not found")
    if not secrets.compare_digest(x_provider_token, case.provider_token):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "X-Provider-Token does not match this case"
        )
    return case


def require_reviewer_token(x_reviewer_token: str = Header(...)) -> None:
    if not secrets.compare_digest(x_reviewer_token, settings.reviewer_token):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "invalid X-Reviewer-Token")
