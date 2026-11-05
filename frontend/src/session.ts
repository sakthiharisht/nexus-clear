// Demo-grade auth (backend/app/api/auth.py): a per-case provider
// token, generated once at case creation and never re-shown by the
// API, is kept here only so this browser tab can keep acting as that
// case's provider across page loads. The reviewer token is one
// shared secret for the whole demo (there is exactly one reviewer
// role) - typed in once, remembered the same way. Neither is a real
// session; there is no server-side session state at all.

const CASE_ID_KEY = "nexus-clear:case-id";
const PROVIDER_TOKEN_KEY = "nexus-clear:provider-token";
const REVIEWER_TOKEN_KEY = "nexus-clear:reviewer-token";

export function saveCaseSession(caseId: string, providerToken: string): void {
  localStorage.setItem(CASE_ID_KEY, caseId);
  localStorage.setItem(PROVIDER_TOKEN_KEY, providerToken);
}

export function getCaseId(): string | null {
  return localStorage.getItem(CASE_ID_KEY);
}

export function getProviderToken(): string | null {
  return localStorage.getItem(PROVIDER_TOKEN_KEY);
}

export function clearCaseSession(): void {
  localStorage.removeItem(CASE_ID_KEY);
  localStorage.removeItem(PROVIDER_TOKEN_KEY);
}

export function getReviewerToken(): string | null {
  return localStorage.getItem(REVIEWER_TOKEN_KEY);
}

export function saveReviewerToken(token: string): void {
  localStorage.setItem(REVIEWER_TOKEN_KEY, token);
}
