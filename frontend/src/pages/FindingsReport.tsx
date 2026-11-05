import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { components } from "../api/client";
import { getCaseId } from "../session";
import { InjectionBadge, NeedsVerificationBadge, SeverityBadge, StatusBadge } from "../components/Badges";

type GapReport = components["schemas"]["GapReport"];
type Finding = components["schemas"]["Finding"];

export default function FindingsReport() {
  const [caseId] = useState<string | null>(getCaseId());
  const [report, setReport] = useState<GapReport | null>(null);
  const [findingsById, setFindingsById] = useState<Record<string, Finding>>({});
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);

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
      <ul className="findings-list">
        {report.entries.map((entry) => {
          const finding = findingsById[entry.finding_id];
          const isInjection = entry.rule_id === "R-SEC-001";
          return (
            <li key={entry.finding_id} className="finding-row">
              <div className="finding-summary">
                <StatusBadge status={entry.status} />
                <SeverityBadge severity={entry.severity} />
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
