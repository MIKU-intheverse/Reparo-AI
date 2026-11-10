"use client";

import { useState } from "react";
import { api, ApiError } from "@/lib/api";
import { HBarList, ReliabilityChart } from "./Charts";
import { pct } from "./format";
import { ActionButton, Banner, Card, Stat, Th } from "./ui";

const ROWS: [string, string][] = [
  ["gbm_calibrated", "Gradient boosting + calibration (deployed)"],
  ["gbm_uncalibrated", "Gradient boosting, uncalibrated"],
  ["logistic_regression", "Logistic regression baseline"],
  ["rules_baseline", "Static rule score (before ML)"],
];
const COLS: [string, string, boolean][] = [
  ["auc", "ROC AUC", true],
  ["pr_auc", "PR AUC", true],
  ["brier", "BRIER", false],
  ["log_loss", "LOG LOSS", false],
  ["ece", "ECE", false],
];

export default function ModelTab({ card, resolved, onRetrained }: { card: any; resolved: number; onRetrained: () => void }) {
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const m = card.metrics;

  async function retrain() {
    setBusy(true);
    setMsg(null);
    try {
      const r = await api.mlRetrain();
      setMsg(`Retrained → ${r.version} (AUC ${r.metrics.auc}). Used ${r.real_data?.used_for_training ?? 0} logged production outcome(s) alongside synthetic data.`);
      onRetrained();
    } catch (e) {
      setMsg(e instanceof ApiError ? e.message : "Retraining failed.");
    } finally {
      setBusy(false);
    }
  }

  const best = (key: string, higher: boolean) => {
    const vals = ROWS.map(([k]) => m[k][key]);
    return higher ? Math.max(...vals) : Math.min(...vals);
  };

  return (
    <div className="space-y-6">
      <Banner tone="warn">
        <strong className="text-gold-bright">Read this first — what these numbers mean.</strong> {card.data_provenance}
      </Banner>

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Stat label="MODEL VERSION" value={card.version.replace("risk-gbm-", "")} sub={card.algorithm.split(" + ")[0]} />
        <Stat label="TEST AUC" value={m.gbm_calibrated.auc.toFixed(3)} sub={`rule score: ${m.rules_baseline.auc.toFixed(3)}`} tone="good" />
        <Stat label="CALIBRATION ERROR (ECE)" value={pct(m.gbm_calibrated.ece, 1)} sub={`rule score: ${pct(m.rules_baseline.ece, 1)}`} tone="good" />
        <Stat label="TRAINING ROWS" value={card.dataset.n_rows.toLocaleString()} sub={`${card.dataset.n_cases.toLocaleString()} simulated failed payments`} />
      </div>

      <Card title="HELD-OUT TEST PERFORMANCE" subtitle={`${card.dataset.split}. Test rows: ${card.dataset.test_rows.toLocaleString()}. Best value per column is highlighted.`}>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gold-dim/20">
                <Th>MODEL</Th>
                {COLS.map(([, label]) => (
                  <Th key={label} right>{label}</Th>
                ))}
              </tr>
            </thead>
            <tbody>
              {ROWS.map(([k, label]) => (
                <tr key={k} className="border-b border-gold-dim/10">
                  <td className="px-3 py-2 text-parchment">{label}</td>
                  {COLS.map(([c, , higher]) => (
                    <td key={c} className={`px-3 py-2 text-right font-mono ${m[k][c] === best(c, higher) ? "text-[#3fbf9f]" : "text-parchmentdim"}`}>
                      {m[k][c].toFixed(3)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="mt-3 text-[11px] leading-relaxed text-parchmentdim/80">
          Logistic regression is competitive here because the simulated world is smooth — the honest takeaway is that the
          big win is over the old static scores (ranking <em>and</em> calibration), not boosting over a linear model.
          Calibration matters because the engine multiplies this probability by the amount to rank cases by expected recovered value.
        </p>
      </Card>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card title="RELIABILITY DIAGRAM" subtitle="Points on the dashed diagonal mean “when the model says 60%, 60% recover”. Teal = this model, gold = old rule score. Bubble size = rows.">
          <div className="flex justify-center">
            <ReliabilityChart model={card.reliability.model} baseline={card.reliability.rules_baseline} />
          </div>
        </Card>
        <Card title="WHAT DRIVES THE SCORE" subtitle="Grouped permutation importance on the test split: how much log-loss worsens when a factor is scrambled.">
          <HBarList items={card.feature_importance.map((f: any) => ({ label: f.factor, value: f.importance }))} format={(v) => v.toFixed(3)} />
        </Card>
      </div>

      <Card title="BY FAILURE CATEGORY" subtitle="Mean predicted vs observed recovery on the test split — and what the old static rule would have said.">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gold-dim/20">
                <Th>CATEGORY</Th><Th right>ROWS</Th><Th right>OBSERVED</Th><Th right>MODEL</Th><Th right>OLD RULE</Th><Th right>AUC</Th>
              </tr>
            </thead>
            <tbody>
              {card.metrics_by_category.map((c: any) => (
                <tr key={c.category} className="border-b border-gold-dim/10">
                  <td className="px-3 py-2 text-parchment">{c.category.replace("_", " ")}</td>
                  <td className="px-3 py-2 text-right font-mono text-parchmentdim">{c.rows.toLocaleString()}</td>
                  <td className="px-3 py-2 text-right font-mono text-parchment">{pct(c.observed_rate)}</td>
                  <td className="px-3 py-2 text-right font-mono text-[#3fbf9f]">{pct(c.mean_predicted)}</td>
                  <td className="px-3 py-2 text-right font-mono text-parchmentdim">{pct(c.rules_baseline_predicted)}</td>
                  <td className="px-3 py-2 text-right font-mono text-parchmentdim">{c.auc}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <Card title="CLOSING THE LOOP" subtitle="Every scored case is logged with its exact features; when the case ends (recovered / exhausted / expired) the outcome is attached.">
        <div className="flex flex-wrap items-center gap-4">
          <p className="text-xs text-parchmentdim">
            Resolved production decisions available for retraining: <span className="font-mono text-gold-bright">{resolved}</span>
            {resolved < 50 && " (needs ≥ 50 to be used; until then the model trains on synthetic data only)"}
          </p>
          <ActionButton onClick={retrain} busy={busy} tone="gold">RETRAIN NOW</ActionButton>
        </div>
        {msg && <p className="mt-3 text-xs text-parchment">{msg}</p>}
        <p className="mt-3 text-[10px] text-parchmentdim/60">CLI equivalent: <code>python -m app.ml.train --from-db</code>. Single-tenant assumption: the model is shared process-wide.</p>
      </Card>
    </div>
  );
}
