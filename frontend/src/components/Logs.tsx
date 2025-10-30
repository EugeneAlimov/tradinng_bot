import React from "react";

export default function Logs({ runId }: { runId: string | null }) {
  const [text, setText] = React.useState<string>("");

  React.useEffect(() => {
    setText("");
    const es = new EventSource("/api/logs");
    es.onmessage = (ev) => setText((t) => (t ? t + "\n" : "") + ev.data);
    es.onerror = () => es.close();
    return () => es.close();
  }, [runId]);

  return <textarea readOnly value={text || "-"} style={{height:420}} />;
}
