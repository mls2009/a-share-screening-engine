import { useState } from "react";
import { api } from "../../api";
import type { MetricSpec, UiNode } from "../../types";
import { createGroup, fromApiNode } from "../screener/treeModel";

export function ConditionJsonImport({ label, catalog, onImport }: { label: string; catalog: MetricSpec[]; onImport: (tree: UiNode) => void }) {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const apply = async () => {
    setBusy(true); setError("");
    try {
      const parsed: unknown = JSON.parse(text);
      const validation = await api.validateScreen(parsed);
      if (!validation.valid) throw new Error(validation.errors[0]?.message ?? "条件校验失败");
      const node = fromApiNode(parsed, catalog);
      onImport(node.kind === "group" ? node : { ...createGroup(), children: [node] });
      setOpen(false);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "导入失败"); }
    finally { setBusy(false); }
  };
  return <>
    <button className="ghost-button" onClick={() => setOpen(!open)}>导入{label} JSON</button>
    {open && <div className="json-import-panel" role="dialog" aria-label={`${label} JSON 导入`}>
      <p>粘贴条件选股的 JSON 或选择文件；保留各条件周期，校验后替换{label}条件。</p>
      <textarea aria-label={`${label}条件 JSON`} disabled={busy} value={text} onChange={event=>setText(event.target.value)} />
      <div className="json-import-actions"><label className="file-button">选择文件<input type="file" aria-label={`${label} JSON 文件`} accept="application/json,.json" disabled={busy} onChange={event=>{
        const file = event.target.files?.[0];
        if (file) void file.text().then(setText).catch(()=>setError("读取文件失败"));
        event.target.value = "";
      }} /></label><button disabled={busy} onClick={()=>setOpen(false)}>取消</button><button className="run-button" disabled={busy || !text.trim()} onClick={()=>void apply()}>应用{label} JSON</button></div>
      {error && <p className="error-banner" role="alert">{error}</p>}
    </div>}
  </>;
}
