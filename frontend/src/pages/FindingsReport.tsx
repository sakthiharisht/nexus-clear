import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { components } from "../api/client";
import { getCaseId, getProviderToken } from "../session";
import { InjectionBadge, NeedsVerificationBadge, SeverityBadge, StatusBadge } from "../components/Badges";

type GapReport = components["schemas"]["GapReport"];
type Finding = components["schemas"]["Finding"];

// M9.1 #5: same hardcoded-rule-id pattern as the injection badge above
// (R-SEC-001) - the gap-explanation form only makes sense on the one
// rule it's for.
const GAP_EXPLANATION_RULE_ID = "R-WORK-001";

export default function FindingsReport() {
  const [caseId] = useState<string | null>(getCaseId());
  const [report, setReport] = useState<GapReport | null>(null);
  const [findingsById, setFindingsById] = useState<Record<string, Finding>>({});
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [onlyIssues, setOnlyIssues] = useState(true);
  const [gapStart, setGapStart] = useState("");
  const [gapEnd, setGapEnd] = useState("");
  const [gapText, setGapText] = useState("");
  const [gapResult, setGapResult] = useState<string | null>(null);
  const [gapError, setGapError] = useState<string | null>(null);

  async function submitGapExplanation() {
    const providerToken = getProviderToken();
    if (!caseId || !providerToken) return;
    setGapError(null);
    setGapResult(null);
    const { data, error: err } = await api.POST("/cases/{case_id}/gap-explanation", {
      params: { path: { case_id: caseId }, header: { "x-provider-token": providerToken } },
      body: { gap_start: gapStart, gap_end: gapEnd, explanation: gapText },
    });
    if (err) {
      setGapError(JSON.stringify(err));
      return;
    }
    setGapResult(
      data.injection_detected
        ? "Saved - instruction-like text detected in your explanation; a reviewer will see it as written."
        : "Saved. Run the case again to send this to the reviewer queue.",
    );
  }

  useEffect(() => {
    if (!caseId) return;
    void (async () => {
      const [reportRes, findingsRes] = await Promise.all([
        api.GET("/cases/{case_id}/report", { params: { path: { case_id: caseId } } }),
        api.GET("/cases/{case_id}/findings", { params: { path: { case_id: caseId } } }),
      ]);
      if (reportRes.error) {
        setError(JSON.stringify(reportRes.error));
        return;
      }
      setReport(reportRes.data ?? null);
      const byId: Record<string, Finding> = {};
      for (const finding of findingsRes.data ?? []) byId[finding.finding_id] = finding;
      setFindingsById(byId);
    })();
  }, [caseId]);

  if (!caseId) return <p className="hint">Start a case first.</p>;
  if (error) return <p className="error">{error}</p>;
  if (!report) return <p>Loading...</p>;

  return (
    <section className="card">
      <h1>Findings</h1>
      <p className="readiness-score">
        Readiness score: <strong>{report.readiness_score}</strong> / 100
      </p>
      {report.simulated && (
        <p className="badge badge-simulated">SIMULATED - not a live model run</p>
      )}
      <label className="checkbox-label">
        <input
          type="checkbox"
          checked={onlyIssues}
          onChange={(e) => setOnlyIssues(e.target.checked)}
        />
        Show only issues (fail / unknown)
      </label>
      <ul className="findings-list">
        {report.entries
          .filter((entry) => !onlyIssues || entry.status === "fail" || entry.status === "unknown")
          .map((entry) => {
          const finding = findingsById[entry.finding_id];
          const isInjection = entry.rule_id === "R-SEC-001";
          return (
            <li key={entry.finding_id} className="finding-row">
              <div className="finding-summary">
                <StatusBadge status={entry.status} />
                {/* Severity (blocker/warning/info) only matters once a check
                    isn't passing - "pass" + "blocker" side by side reads as
                    a contradiction even though it just means "this is an
                    important check, and right now it's fine." */}
                {entry.status !== "pass" && <SeverityBadge severity={entry.severity} />}
                <NeedsVerificationBadge needsVerification={entry.needs_verification} />
                {isInjection && entry.status === "fail" && <InjectionBadge />}
                <span className="finding-title">{entry.rule_title}</span>
                <button
                  className="link-button"
                  onClick={() => setExpanded(expanded === entry.finding_id ? null : entry.finding_id)}
                >
                  {expanded === entry.finding_id ? "hide evidence" : "view evidence"}
                </button>
              </div>
              <p className="finding-sentence">
                {entry.sentence}{" "}
                {!entry.sentence_model_phrased && (
                  <span className="hint">(templated, not model-phrased)</span>
                )}
              </p>
              <p className="hint">
                source: {entry.source_id}
                {entry.doc_date ? ` · dated ${entry.doc_date}` : ""} · last verified{" "}
                {entry.last_verified}
              </p>
              {entry.rule_id === GAP_EXPLANATION_RULE_ID && entry.status === "fail" && (
                <div className="evidence-box">
                  <p className="hint">
                    Explain this gap. This does not change the finding - it stays a gap on
                    record, and a reviewer decides whether to accept your explanation.
                  </p>
                  <label>
                    Gap start
                    <input
                      type="date"
                      value={gapStart}
                      onChange={(e) => setGapStart(e.target.value)}
                    />
                  </label>
                  <label>
                    Gap end
                    <input type="date" value={gapEnd} onChange={(e) => setGapEnd(e.target.value)} />
                  </label>
                  <label>
                    Explanation (max 1000 characters)
                    <textarea
                      maxLength={1000}
                      value={gapText}
                      onChange={(e) => setGapText(e.target.value)}
                    />
                  </label>
                  {gapError && <p className="error">{gapError}</p>}
                  {gapResult && <p className="hint">{gapResult}</p>}
                  <button
                    disabled={!gapStart || !gapEnd || !gapText}
                    onClick={() => void submitGapExplanation()}
                  >
                    Submit explanation
                  </button>
                </div>
              )}
              {expanded === entry.finding_id && finding && (
                <div className="evidence-box">
                  {finding.confidence != null && <p>confidence: {finding.confidence.toFixed(2)}</p>}
                  {finding.evidence.length === 0 && <p className="hint">no evidence recorded</p>}
                  {finding.evidence.map((ev, i) => (
                    <div key={i} className="evidence-item">
                      {ev.kind === "document" ? (
                        <>
                          <p className="evidence-quote">"{ev.quote}"</p>
                          <p className="hint">
                            document{ev.doc_id ? ` ${ev.doc_id}` : ""}
                            {ev.page != null ? `, page ${ev.page}` : ""}
                          </p>
                        </>
                      ) : (
                        <>
                          <p className="evidence-quote">"{ev.quote}"</p>
                          <p className="hint">
                            registry {ev.registry}
                            {ev.fetched_at ? ` · fetched ${ev.fetched_at}` : ""}
                          </p>
                        </>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
}
