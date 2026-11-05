import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { components } from "../api/client";
import { getCaseId, getReviewerToken, saveReviewerToken } from "../session";
import { NeedsVerificationBadge, SeverityBadge, StatusBadge } from "../components/Badges";

type ReviewItemResponse = components["schemas"]["ReviewItemResponse"];
type ReviewItemDetailResponse = components["schemas"]["ReviewItemDetailResponse"];
type ReviewDecision = components["schemas"]["ResolveReviewRequest"]["decision"];
type FindingStatus = NonNullable<components["schemas"]["ResolveReviewRequest"]["override_status"]>;

export default function ReviewerQueue() {
  const [caseId] = useState<string | null>(getCaseId());
  const [reviewerToken, setReviewerToken] = useState(getReviewerToken() ?? "");
  const [items, setItems] = useState<ReviewItemResponse[]>([]);
  const [detail, setDetail] = useState<ReviewItemDetailResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [decision, setDecision] = useState<ReviewDecision>("confirm");
  const [overrideStatus, setOverrideStatus] = useState<FindingStatus>("pass");
  const [note, setNote] = useState("");
  const [resolvedBy, setResolvedBy] = useState("reviewer-1");

  async function loadQueue() {
    const { data, error: err } = await api.GET("/reviews", {
      params: { query: caseId ? { case_id: caseId } : {} },
    });
    if (err) {
      setError(JSON.stringify(err));
      return;
    }
    setItems(data ?? []);
  }

  useEffect(() => {
    void loadQueue();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [caseId]);

  async function openDetail(id: string) {
    setError(null);
    const { data, error: err } = await api.GET("/reviews/{review_id}", {
      params: { path: { review_id: id } },
    });
    if (err) {
      setError(JSON.stringify(err));
      return;
    }
    setDetail(data ?? null);
    setNote("");
  }

  async function resolve() {
    if (!detail) return;
    saveReviewerToken(reviewerToken);
    setError(null);
    const { error: err } = await api.POST("/reviews/{review_id}/resolve", {
      params: { path: { review_id: detail.id }, header: { "x-reviewer-token": reviewerToken } },
      body: {
        decision,
        note,
        resolved_by: resolvedBy,
        override_status: decision === "override" ? overrideStatus : null,
      },
    });
    if (err) {
      setError(JSON.stringify(err));
      return;
    }
    setDetail(null);
    await loadQueue();
  }

  return (
    <section className="card">
      <h1>Reviewer queue</h1>
      <label>
        Reviewer token
        <input
          type="password"
          value={reviewerToken}
          onChange={(e) => setReviewerToken(e.target.value)}
        />
      </label>
      {error && <p className="error">{error}</p>}
      <table className="table">
        <thead>
          <tr>
            <th>Status</th>
            <th>Created</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {items.map((item) => (
            <tr key={item.id}>
              <td>{item.status}</td>
              <td>{item.created_at}</td>
              <td>
                <button className="link-button" onClick={() => void openDetail(item.id)}>
                  view
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {detail && (
        <div className="result-box">
          <h2>{detail.finding.rule_id}</h2>
          <StatusBadge status={detail.finding.status} />
          <SeverityBadge severity={detail.finding.severity} />
          <NeedsVerificationBadge needsVerification={detail.finding.rule_source.needs_verification} />
          {detail.finding.confidence != null && <p>confidence: {detail.finding.confidence.toFixed(2)}</p>}
          <ul>
            {detail.finding.evidence.map((ev, i) => (
              <li key={i}>"{ev.quote}"</li>
            ))}
          </ul>

          {detail.status === "resolved" ? (
            <p className="hint">already resolved: {JSON.stringify(detail.reviewer_resolution)}</p>
          ) : (
            <>
              <label>
                Decision
                <select
                  value={decision}
                  onChange={(e) => setDecision(e.target.value as ReviewDecision)}
                >
                  <option value="confirm">confirm</option>
                  <option value="override">override</option>
                  <option value="needs_more_info">needs more info</option>
                </select>
              </label>
              {decision === "override" && (
                <label>
                  New status
                  <select
                    value={overrideStatus}
                    onChange={(e) => setOverrideStatus(e.target.value as FindingStatus)}
                  >
                    <option value="pass">pass</option>
                    <option value="fail">fail</option>
                    <option value="not_applicable">not applicable</option>
                    <option value="unknown">unknown</option>
                  </select>
                </label>
              )}
              <label>
                Resolved by
                <input value={resolvedBy} onChange={(e) => setResolvedBy(e.target.value)} />
              </label>
              <label>
                Note
                <textarea value={note} onChange={(e) => setNote(e.target.value)} />
              </label>
              <button disabled={!reviewerToken || !note} onClick={() => void resolve()}>
                Resolve
              </button>
            </>
          )}
        </div>
      )}
    </section>
  );
}
