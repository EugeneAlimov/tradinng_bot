import React from "react";
import Controls from "./components/Controls";
import Logs from "./components/Logs";
import ChampionCard from "./components/ChampionCard";

export default function App() {
  const [mode, setMode] = React.useState<"manual" | "assist" | "auto">("assist");
  const [wfSplits, setWfSplits] = React.useState<number>(5);
  const [wfMinTrades, setWfMinTrades] = React.useState<number>(3);

  const [sweepArgs, setSweepArgs] = React.useState<string>(
`--ohlcv data/demo_ohlcv_1m.csv --resample 5min \
--ema-fast 12 --ema-slow 21 --adx-len 14 \
--adx-on 28,32 --adx-off 18,20,22 --require-di true \
--htf-tf 15min,1h \
--stop-atr 2.0,2.5,3.0 --take-atr 1.0,1.5,2.0 --trail-atr 1.0,2.0 \
--cooldown-bars 0,12,24 --min-hold-bars 0,6 \
--breakeven-rr 0.5,1.0 --trail-activate-rr 1.5,3.0 \
--fee-bps 10 --slip-bps 2 --qty 1 \
--out reports/sweep_full.csv`
  );

  const [rankArgs, setRankArgs] = React.useState<string>(
`--objective net_pnl --top-k 50 --auto-min-trades \
--neighbor-radius 1 --robust-pos-share 0.55 \
--out-top reports/top_ranked.csv --out-robust reports/top_robust.csv`
  );

  const [runId, setRunId] = React.useState<string | null>(null);

  return (
    <div className="container">
      <h1>Trading Bot — Control Panel</h1>

      <div className="card" style={{ marginBottom: 24 }}>
        <Controls
          onStarted={setRunId}
          mode={mode}
          setMode={setMode}
          sweepArgs={sweepArgs}
          setSweepArgs={setSweepArgs}
          rankArgs={rankArgs}
          setRankArgs={setRankArgs}
          wfSplits={wfSplits}
          setWfSplits={setWfSplits}
          wfMinTrades={wfMinTrades}
          setWfMinTrades={setWfMinTrades}
        />
      </div>

      <div className="grid">
        <div className="card">
          <div className="label">Logs (tail)</div>
          <Logs runId={runId} />
        </div>
        <ChampionCard />
      </div>
    </div>
  );
}
