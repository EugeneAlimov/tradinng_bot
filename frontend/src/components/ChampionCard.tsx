import React from "react";
import api from "../lib/api";

export default function ChampionCard() {
  const [data, setData] = React.useState<any>({});
  const refresh = async () => setData(await api.champion());
  React.useEffect(() => { refresh(); }, []);

  return (
    <div className="card">
      <div className="row" style={{marginBottom:8}}>
        <div className="label" style={{fontSize:14, color:"var(--text)"}}>Champion</div>
        <div className="mr-auto" />
        <button onClick={refresh} className="btn-secondary">Refresh</button>
      </div>
      <pre style={{maxHeight:460, overflow:"auto"}}>{JSON.stringify(data, null, 2)}</pre>
    </div>
  );
}
