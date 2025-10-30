import React from "react";
import api, { RunPayload, Mode } from "../lib/api";

type Props = {
  onStarted: (runId: string) => void;
  mode: Mode;
  setMode: (m: Mode) => void;
  sweepArgs: string;
  setSweepArgs: (s: string) => void;
  rankArgs: string;
  setRankArgs: (s: string) => void;
  wfSplits: number;
  setWfSplits: (n: number) => void;
  wfMinTrades: number;
  setWfMinTrades: (n: number) => void;
};

export default function Controls(p: Props) {
  const [busy, setBusy] = React.useState(false);

  const run = async () => {
    const payload: RunPayload = {
      mode: p.mode,
      sweep_args: p.sweepArgs,
      rank_args: p.rankArgs,
      wf_splits: p.wfSplits || 0,
      wf_min_trades: p.wfMinTrades || 0,
    };
    setBusy(true);
    try {
      const r = await api.run(payload);
      p.onStarted(r.run_id);
    } catch (e: any) {
      alert(e?.message || String(e));
    } finally {
      setBusy(false);
    }
  };

  const cancel = async () => {
    try { await api.cancel(); } catch (e: any) { alert(e?.message || String(e)); }
  };

  return (
    <div className="space">
      <div className="row">
        <label>Mode:</label>
        <select value={p.mode} onChange={(e) => p.setMode(e.target.value as Mode)}>
          <option value="manual">manual</option>
          <option value="assist">assist</option>
          <option value="auto">auto</option>
        </select>

        <label>WF splits:</label>
        <input type="number" min={0} value={p.wfSplits} onChange={(e) => p.setWfSplits(Number(e.target.value))} style={{width:80}} />

        <label>WF min trades:</label>
        <input type="number" min={0} value={p.wfMinTrades} onChange={(e) => p.setWfMinTrades(Number(e.target.value))} style={{width:80}} />

        <div className="mr-auto" />
        <button onClick={run} disabled={busy} className="btn-primary">{busy ? "Running…" : "Run"}</button>
        <button onClick={cancel} className="btn-secondary">Cancel</button>
      </div>

      <div className="grid" style={{gridTemplateColumns:"1fr 1fr", gap:16, marginTop:12}}>
        <div>
          <div className="label">sweep_args</div>
          <textarea rows={10} value={p.sweepArgs} onChange={(e)=>p.setSweepArgs(e.target.value)} />
        </div>
        <div>
          <div className="label">rank_args</div>
          <textarea rows={10} value={p.rankArgs} onChange={(e)=>p.setRankArgs(e.target.value)} />
        </div>
      </div>
    </div>
  );
}
