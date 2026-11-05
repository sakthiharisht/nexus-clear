import { useEffect, useState } from "react";
import { api } from "../api/client";

// The backend returns this run's shape as a loose dict (app/eval/run.py's
// run_eval()) rather than a typed Pydantic model - it is a dev/demo
// artifact (eval/runs/*.json, gitignored), not part of the production
// API contract. Typed loosely here to match, not strictly.
interface EvalRun {
  rule_pack_version: string;
  ground_truth_seed: number;
  metrics: Record<string, { exact_match_rate: number; coverage: number; accuracy_when_decided: number }>;
  classify_metrics: Record<
    string,
    { n: number; accuracy: number; ece: number; total_cost_usd: number; mean_latency_ms: number; cost_known: boolean }
  >;
  extract_metrics: Record<
    string,
    { n_documents: number; overall_coverage: number; overall_accuracy_when_known: number; total_cost_usd: number }
  >;
  escalate_metrics: {
    mode: string;
    total_findings: number;
    escalated_count: number;
    escalation_rate: number;
    precision: number | null;
    recall: number | null;
    simulated: boolean;
  } | null;
}

function isSimulated(mode: string): boolean {
  return mode.endsWith("-SIMULATED");
}

export default function EvalDashboard() {
  const [run, setRun] = useState<EvalRun | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void (async () => {
      const { data, response } = await api.GET("/eval/latest", {});
      if (response.status === 404) {
        setError(
          "No eval run found. From backend/, run: uv run python -m app.eval.run",
        );
        return;
      }
      setRun((data as unknown as EvalRun) ?? null);
    })();
  }, []);

  if (error) return <p className="error">{error}</p>;
  if (!run) return <p>Loading...</p>;

  return (
    <section className="card">
      <h1>Eval dashboard</h1>
      <p className="hint">
        rule_pack_version {run.rule_pack_version} · seed {run.ground_truth_seed}
      </p>

      <h2>Ceiling / baseline / end-to-end</h2>
      <table className="table">
        <thead>
          <tr>
            <th>mode</th>
            <th>exact match</th>
            <th>coverage</th>
            <th>accuracy when decided</th>
          </tr>
        </thead>
        <tbody>
          {Object.entries(run.metrics).map(([mode, m]) => (
            <tr key={mode}>
              <td>{mode}</td>
              <td>{(m.exact_match_rate * 100).toFixed(1)}%</td>
              <td>{(m.coverage * 100).toFixed(1)}%</td>
              <td>{(m.accuracy_when_decided * 100).toFixed(1)}%</td>
            </tr>
          ))}
        </tbody>
      </table>

      <h2>Classify (per tier)</h2>
      <table className="table">
        <thead>
          <tr>
            <th>mode</th>
            <th>n</th>
            <th>accuracy</th>
            <th>ECE</th>
            <th>cost</th>
            <th>mean latency</th>
          </tr>
        </thead>
        <tbody>
          {Object.entries(run.classify_metrics).map(([mode, m]) => (
            <tr key={mode}>
              <td>
                {mode} {isSimulated(mode) && <span className="badge badge-simulated">SIMULATED</span>}
              </td>
              <td>{m.n}</td>
              <td>{(m.accuracy * 100).toFixed(1)}%</td>
              <td>{m.ece.toFixed(3)}</td>
              <td>{m.cost_known ? `$${m.total_cost_usd.toFixed(4)}` : "n/a"}</td>
              <td>{m.mean_latency_ms.toFixed(0)} ms</td>
            </tr>
          ))}
        </tbody>
      </table>

      <h2>Extract (per tier)</h2>
      <table className="table">
        <thead>
          <tr>
            <th>mode</th>
            <th>n documents</th>
            <th>coverage</th>
            <th>accuracy when known</th>
            <th>cost</th>
          </tr>
        </thead>
        <tbody>
          {Object.entries(run.extract_metrics).map(([mode, m]) => (
            <tr key={mode}>
              <td>
                {mode} {isSimulated(mode) && <span className="badge badge-simulated">SIMULATED</span>}
              </td>
              <td>{m.n_documents}</td>
              <td>{(m.overall_coverage * 100).toFixed(1)}%</td>
              <td>{(m.overall_accuracy_when_known * 100).toFixed(1)}%</td>
              <td>${m.total_cost_usd.toFixed(4)}</td>
            </tr>
          ))}
        </tbody>
      </table>

      {run.escalate_metrics && (
        <>
          <h2>Escalate</h2>
          <table className="table">
            <thead>
              <tr>
                <th>mode</th>
                <th>total findings</th>
                <th>escalated</th>
                <th>escalation rate</th>
                <th>precision</th>
                <th>recall</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>
                  {run.escalate_metrics.mode}{" "}
                  {run.escalate_metrics.simulated && (
                    <span className="badge badge-simulated">SIMULATED</span>
                  )}
                </td>
                <td>{run.escalate_metrics.total_findings}</td>
                <td>{run.escalate_metrics.escalated_count}</td>
                <td>{(run.escalate_metrics.escalation_rate * 100).toFixed(2)}%</td>
                <td>{run.escalate_metrics.precision?.toFixed(2) ?? "n/a"}</td>
                <td>{run.escalate_metrics.recall?.toFixed(2) ?? "n/a"}</td>
              </tr>
            </tbody>
          </table>
        </>
      )}
    </section>
  );
}
