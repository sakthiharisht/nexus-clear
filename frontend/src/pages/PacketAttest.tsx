import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { components } from "../api/client";
import { getCaseId, getProviderToken } from "../session";

type CaqhStylePacket = components["schemas"]["CaqhStylePacket"];

export default function PacketAttest() {
  const [caseId] = useState<string | null>(getCaseId());
  const providerToken = getProviderToken();
  const [packet, setPacket] = useState<CaqhStylePacket | null>(null);
  const [notAttested, setNotAttested] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [attestedBy, setAttestedBy] = useState("");
  const [typedName, setTypedName] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [attestResult, setAttestResult] = useState<string | null>(null);

  async function loadPacket() {
    if (!caseId) return;
    const { data, response } = await api.GET("/cases/{case_id}/packet", {
      params: { path: { case_id: caseId } },
    });
    if (response.status === 404) {
      setNotAttested(true);
      return;
    }
    setPacket(data ?? null);
  }

  useEffect(() => {
    void loadPacket();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [caseId]);

  async function attest() {
    if (!caseId || !providerToken) return;
    setError(null);
    setAttestResult(null);
    const { data, error: err } = await api.POST("/cases/{case_id}/attest", {
      params: { path: { case_id: caseId }, header: { "x-provider-token": providerToken } },
      body: { confirmed: true, attested_by: attestedBy, typed_name: typedName },
    });
    if (err) {
      setError(JSON.stringify(err));
      return;
    }
    setAttestResult(`attested - packet hash ${data?.packet_hash}`);
    await loadPacket();
  }

  if (!caseId) return <p className="hint">Start a case first.</p>;
  if (!providerToken) return <p className="error">No provider token for this case in this browser.</p>;

  return (
    <section className="card">
      <h1>Packet &amp; attest</h1>
      {error && <p className="error">{error}</p>}
      {attestResult && <p className="result-box">{attestResult}</p>}

      {packet && (
        <div className="result-box">
          <p>
            <strong>{packet.label}</strong>
          </p>
          <h3>License (verified fields only)</h3>
          <pre>{JSON.stringify(packet.license, null, 2)}</pre>
          <h3>COI (verified fields only)</h3>
          <pre>{JSON.stringify(packet.coi, null, 2)}</pre>
          <h3>CV (verified fields only)</h3>
          <pre>{JSON.stringify(packet.cv, null, 2)}</pre>
        </div>
      )}

      {notAttested && !packet && (
        <>
          <p className="hint">
            Not yet attested. Attestation blocks on any open blocker finding, any unresolved
            review item, or a run that predates one of those - run the case again after
            resolving everything, then attest.
          </p>
          <label>
            Attested by
            <input value={attestedBy} onChange={(e) => setAttestedBy(e.target.value)} />
          </label>
          <label>
            Typed name
            <input value={typedName} onChange={(e) => setTypedName(e.target.value)} />
          </label>
          <label className="checkbox-label">
            <input
              type="checkbox"
              checked={confirmed}
              onChange={(e) => setConfirmed(e.target.checked)}
            />
            I confirm this packet is accurate and complete.
          </label>
          <button
            disabled={!confirmed || !attestedBy || !typedName}
            onClick={() => void attest()}
          >
            Attest
          </button>
        </>
      )}
    </section>
  );
}
