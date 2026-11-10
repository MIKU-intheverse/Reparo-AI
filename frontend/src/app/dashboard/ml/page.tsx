"use client";

import { useCallback, useEffect, useState } from "react";
import { BrainCircuit } from "lucide-react";
import DashboardShell from "@/components/DashboardShell";
import { api, getEnvironment } from "@/lib/api";
import BanditTab from "@/components/ml/BanditTab";
import EvaluationTab from "@/components/ml/EvaluationTab";
import ModelTab from "@/components/ml/ModelTab";
import SecurityTab from "@/components/ml/SecurityTab";
import WhatIfTab from "@/components/ml/WhatIfTab";
import { Banner, Stat } from "@/components/ml/ui";

const TABS = [
  { key: "model", label: "Recovery model" },
  { key: "eval", label: "Policy evaluation" },
  { key: "timing", label: "Retry timing" },
  { key: "security", label: "Security & anomalies" },
  { key: "whatif", label: "What-if scorer" },
] as const;
type TabKey = (typeof TABS)[number]["key"];

export default function MLInsightsPage() {
  const [tab, setTab] = useState<TabKey>("model");
  const [overview, setOverview] = useState<any>(null);
  const [card, setCard] = useState<any>(null);
  const [anomaly, setAnomaly] = useState<any>(null);
  const [evaluation, setEvaluation] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const [isTest, setIsTest] = useState(false);

  const refresh = useCallback(async () => {
    setOverview(await api.mlOverview());
  }, []);

  useEffect(() => {
    setIsTest(getEnvironment() === "test");
    api.mlOverview().then(setOverview).catch(() => setError("Could not reach the ML service."));
    api.mlModel().then(setCard).catch(() => setCard(null));
    api.mlAnomalyModel().then(setAnomaly).catch(() => setAnomaly(null));
    api.mlEvaluation().then(setEvaluation).catch(() => setEvaluation(null));
  }, []);

  return (
    <DashboardShell>
      <div className="mb-6 flex items-center gap-3">
        <BrainCircuit className="h-6 w-6 text-gold" />
        <div>
          <h1 className="font-display text-2xl tracking-wide text-gold-bright">ML Insights</h1>
          <p className="text-xs text-parchmentdim">
            A calibrated recovery model, a bandit that learns retry timing, and anomaly detectors — all inside deterministic guardrails.
          </p>
        </div>
      </div>

      {error && <Banner tone="warn">{error}</Banner>}

      {overview && (
        <div className="mb-6 grid grid-cols-2 gap-4 lg:grid-cols-4">
          <Stat label="RISK MODEL" value={overview.risk_model ? overview.risk_model.version.replace("risk-gbm-", "") : "off"} sub={overview.risk_model ? `${overview.risk_model.calibration} calibration` : "rule-based scoring in use"} />
          <Stat label="DECISIONS LOGGED" value={String(overview.decisions_logged)} sub={`${overview.decisions_resolved} resolved into training labels`} />
          <Stat label="OPEN ALERTS" value={String(overview.open_alerts)} tone={overview.open_alerts > 0 ? "bad" : undefined} sub={overview.anomaly_enabled ? "anomaly detection on" : "anomaly detection off"} />
          <Stat label="FALLBACK" value="Rules" sub="every ML component degrades to deterministic rules" />
        </div>
      )}

      <div className="mb-6 flex flex-wrap gap-2 border-b border-gold-dim/20">
        {TABS.map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={`-mb-px border-b-2 px-4 py-2.5 text-xs tracking-widest transition ${tab === t.key ? "border-gold text-gold-bright" : "border-transparent text-parchmentdim hover:text-parchment"}`}
          >
            {t.label.toUpperCase()}
          </button>
        ))}
      </div>

      {tab === "model" && (card ? <ModelTab card={card} resolved={overview?.decisions_resolved ?? 0} onRetrained={() => { api.mlModel().then(setCard); refresh(); }} /> : <Banner tone="warn">The risk model is unavailable, so the engine is using rule-based scoring.</Banner>)}
      {tab === "eval" && (evaluation ? <EvaluationTab key={evaluation.generated_at} initial={evaluation} onUpdated={setEvaluation} /> : <Banner tone="warn">No evaluation report found. Run <code>python -m app.ml.evaluate</code> in the backend.</Banner>)}
      {tab === "timing" && <BanditTab isTest={isTest} onChanged={refresh} />}
      {tab === "security" && <SecurityTab card={anomaly} isTest={isTest} onChanged={refresh} />}
      {tab === "whatif" && <WhatIfTab />}
    </DashboardShell>
  );
}
