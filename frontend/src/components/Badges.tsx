// Shared badges (SPEC.md section 9/M9 UI requirements):
// - needs_verification must stay visible, never silently dropped.
// - "unknown" renders as its own distinct state, never blank/blended
//   with "pass".
// - injection flags are labeled neutrally ("instruction-like text
//   detected"), not as an alarm - a correctly-caught attempt is
//   evidence the defense worked, not something gone wrong.

export function StatusBadge({ status }: { status: string }) {
  const label =
    status === "not_applicable" ? "not applicable" : status === "unknown" ? "unknown" : status;
  return <span className={`badge badge-status-${status}`}>{label}</span>;
}

export function SeverityBadge({ severity }: { severity: string }) {
  return <span className={`badge badge-severity-${severity}`}>{severity}</span>;
}

export function NeedsVerificationBadge({ needsVerification }: { needsVerification: boolean }) {
  if (!needsVerification) return null;
  return (
    <span className="badge badge-needs-verification" title="This rule's sourcing is not independently verified - treat it as guidance, not confirmed payer policy.">
      needs verification
    </span>
  );
}

export function InjectionBadge() {
  return (
    <span className="badge badge-injection" title="Deterministic text-pattern detection, not a model's self-report (CLAUDE.md invariant 1).">
      instruction-like text detected
    </span>
  );
}
