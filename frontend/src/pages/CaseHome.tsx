import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, BASE_URL } from "../api/client";
import type { components } from "../api/client";
import { clearCaseSession, getCaseId, saveCaseSession } from "../session";

type ChecklistResponse = components["schemas"]["ChecklistResponse"];
type RunResult = components["schemas"]["RunResult"];

export default function CaseHome() {
  const [caseId, setCaseId] = useState<string | null>(getCaseId());
  const [checklist, setChecklist] = useState<ChecklistResponse | null>(null);
  const [runResult, setRunResult] = useState<RunResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [payer, setPayer] = useState("BCBSTX");
  const [providerType, setProviderType] = useState("LPC");
  const [legalName, setLegalName] = useState("");
  const [npi, setNpi] = useState("");

  async function loadChecklist(id: string) {
    const { data, error: err } = await api.GET("/cases/{case_id}/checklist", {
      params: { path: { case_id: id } },
    });
    if (err) {
      setError(JSON.stringify(err));
      return;
    }
    setChecklist(data ?? null);
  }

  useEffect(() => {
    if (caseId) void loadChecklist(caseId);
  }, [caseId]);

  async function createCase() {
    setBusy(true);
    setError(null);
    const { data, error: err } = await api.POST("/cases", {
      body: {
        payer,
        provider_type: providerType,
        provider_profile: { legal_name: legalName, npi },
      },
    });
    setBusy(false);
    if (err || !data) {
      setError(JSON.stringify(err));
      return;
    }
    saveCaseSession(data.id, data.provider_token);
    setCaseId(data.id);
  }

  async function uploadDocument(slot: string, file: File) {
    if (!caseId) return;
    setBusy(true);
    setError(null);
    // openapi-fetch's typed body doesn't model a real File for a
    // multipart/form-data operation (the generated type is just
    // `string`, since OpenAPI's own schema for a binary upload has no
    // closer JS equivalent) - a plain fetch against the same base URL
    // sidesteps that mismatch for this one call.
    const form = new FormData();
    form.append("file", file);
    const url = `${BASE_URL}/cases/${caseId}/documents?slot=${encodeURIComponent(slot)}`;
    const response = await fetch(url, { method: "POST", body: form });
    setBusy(false);
    if (!response.ok) {
      setError(await response.text());
      return;
    }
    await loadChecklist(caseId);
  }

  async function runCase() {
    if (!caseId) return;
    setBusy(true);
    setError(null);
    setRunResult(null);
    const { data, error: err } = await api.POST("/cases/{case_id}/run", {
      params: { path: { case_id: caseId } },
    });
    setBusy(false);
    if (err || !data) {
      setError(JSON.stringify(err));
      return;
    }
    setRunResult(data);
  }

  function startOver() {
    clearCaseSession();
    setCaseId(null);
    setChecklist(null);
    setRunResult(null);
    setError(null);
  }

  if (!caseId) {
    return (
      <section className="card">
        <h1>Start a case</h1>
        <p className="hint">Synthetic data only - this never submits anywhere real.</p>
        <label>
          Payer
          <input value={payer} onChange={(e) => setPayer(e.target.value)} />
        </label>
        <label>
          Provider type
          <input value={providerType} onChange={(e) => setProviderType(e.target.value)} />
        </label>
        <label>
          Legal name
          <input value={legalName} onChange={(e) => setLegalName(e.target.value)} />
        </label>
        <label>
          NPI
          <input value={npi} onChange={(e) => setNpi(e.target.value)} />
        </label>
        <button disabled={busy || !legalName || !npi} onClick={() => void createCase()}>
          Create case
        </button>
        {error && <p className="error">{error}</p>}
      </section>
    );
  }

  return (
    <section className="card">
      <h1>Checklist</h1>
      <p className="hint">
        Case <code>{caseId}</code> ·{" "}
        <button className="link-button" onClick={startOver}>
          start a different case
        </button>
      </p>
      {checklist && (
        <table className="table">
          <thead>
            <tr>
              <th>Slot</th>
              <th>Expected type</th>
              <th>Status</th>
              <th>Upload</th>
            </tr>
          </thead>
          <tbody>
            {checklist.slots.map((slot) => (
              <tr key={slot.slot}>
                <td>{slot.slot}</td>
                <td>{slot.doc_type}</td>
                <td>{slot.uploaded ? "uploaded" : slot.required ? "missing (required)" : "missing"}</td>
                <td>
                  <input
                    type="file"
                    disabled={busy}
                    onChange={(e) => {
                      const file = e.target.files?.[0];
                      if (file) void uploadDocument(slot.slot, file);
                    }}
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <button
        disabled={busy || !checklist || checklist.missing_required_slots.length > 0}
        onClick={() => void runCase()}
      >
        Run
      </button>
      {error && <p className="error">{error}</p>}
      {runResult && (
        <div className="result-box">
          <p>
            {runResult.findings.length} findings, {runResult.escalated_finding_ids.length} sent to
            the reviewer queue.
          </p>
          {runResult.extraction_notes.length > 0 && (
            <ul>
              {runResult.extraction_notes.map((note, i) => (
                <li key={i}>{note}</li>
              ))}
            </ul>
          )}
          <p>
            See the <Link to="/report">Findings</Link> screen for the full report.
          </p>
        </div>
      )}
    </section>
  );
}
