import { Bell, Bot, Play, Plus, Radar, Square, Trash2, Zap } from "lucide-react";
import { useEffect, useState } from "react";

import { api } from "../../api";
import type { MonitorSignal, MonitorStatus, MonitorTask, PriceComparator } from "../../types";

export interface MonitorClient {
  monitorTasks(): Promise<MonitorTask[]>;
  monitorStatus(): Promise<MonitorStatus>;
  monitorSignals(): Promise<MonitorSignal[]>;
  createMonitorTask(payload: object): Promise<MonitorTask>;
  toggleMonitorTask(taskId: string, enabled: boolean): Promise<MonitorTask>;
  deleteMonitorTask(taskId: string): Promise<void>;
  startMonitor(): Promise<{ running: boolean }>;
  stopMonitor(): Promise<{ running: boolean }>;
  scanMonitor(): Promise<{ triggered: number }>;
  testFeishu(): Promise<{ success: boolean }>;
}

const comparatorLabels: Record<PriceComparator, string> = {
  above: "价格达到上方",
  below: "价格达到下方",
  cross_above: "向上突破",
  cross_below: "向下跌破",
};

export function MonitorPage({ client = api }: { client?: MonitorClient }) {
  const [tasks, setTasks] = useState<MonitorTask[]>([]);
  const [status, setStatus] = useState<MonitorStatus>();
  const [signals, setSignals] = useState<MonitorSignal[]>([]);
  const [name, setName] = useState("价格点位提醒");
  const [symbols, setSymbols] = useState("600519.SH");
  const [comparator, setComparator] = useState<PriceComparator>("cross_above");
  const [threshold, setThreshold] = useState(1500);
  const [cooldown, setCooldown] = useState(300);
  const [scope, setScope] = useState<"watchlist" | "market">("watchlist");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    Promise.all([client.monitorTasks(), client.monitorStatus(), client.monitorSignals()])
      .then(([nextTasks, nextStatus, nextSignals]) => {
        setTasks(nextTasks); setStatus(nextStatus); setSignals(nextSignals);
      })
      .catch((cause: Error) => setError(cause.message));
  }, [client]);

  const create = async () => {
    setError(""); setMessage("");
    try {
      const created = await client.createMonitorTask({
        name,
        symbols: symbols.split(/[，,\s]+/).map((value) => value.trim().toUpperCase()).filter(Boolean),
        comparator,
        threshold,
        cooldown_seconds: cooldown,
        scope,
        enabled: true,
      });
      setTasks((current) => [...current, created]);
      setMessage("监控规则已创建");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "创建失败");
    }
  };

  const switchRuntime = async () => {
    if (!status) return;
    const result = status.running ? await client.stopMonitor() : await client.startMonitor();
    setStatus({ ...status, running: result.running });
  };

  return (
    <main className="monitor-page">
      <header className="compact-heading">
        <div><p className="eyebrow">5 SEC WATCHLIST / 5 MIN MARKET</p><h1>实时监控</h1></div>
        <div className="monitor-runtime">
          <span className={status?.running ? "live" : "stopped"}><i />{status?.running ? "运行中" : "已停止"}</span>
          <button type="button" className="run-button" aria-label={status?.running ? "停止实时监控" : "启动实时监控"} disabled={!status} onClick={() => void switchRuntime()}>{status?.running ? <Square size={14} /> : <Play size={15} />}{status?.running ? "停止" : "启动"}</button>
        </div>
      </header>
      {error && <div className="error-banner" role="alert">{error}</div>}
      {message && <div className="success-banner">{message}</div>}
      <section className="monitor-summary">
        <div><Radar size={17} /><span>自选扫描</span><strong>{status?.watchlist_interval_seconds ?? 5}s</strong></div>
        <div><Zap size={17} /><span>全市场扫描</span><strong>{status?.market_interval_seconds ?? 300}s</strong></div>
        <div><Bell size={17} /><span>启用任务</span><strong>{status?.enabled_tasks ?? 0}</strong></div>
        <div><Bot size={17} /><span>飞书机器人</span><strong>{status?.feishu_configured ? "已连接" : "未配置"}</strong></div>
      </section>
      <section className="monitor-composer">
        <div className="section-title"><div><Plus size={15} /><span>新建点位规则</span></div></div>
        <div className="monitor-form">
          <label><span>名称</span><input aria-label="监控名称" value={name} onChange={(event) => setName(event.target.value)} /></label>
          <label><span>证券代码（可多个）</span><input aria-label="监控证券代码" value={symbols} onChange={(event) => setSymbols(event.target.value)} /></label>
          <label><span>扫描范围</span><select aria-label="扫描范围" value={scope} onChange={(event) => setScope(event.target.value as "watchlist" | "market")}><option value="watchlist">自选股 / 5 秒</option><option value="market">全市场 / 5 分钟</option></select></label>
          <label><span>触发方式</span><select aria-label="触发方式" value={comparator} onChange={(event) => setComparator(event.target.value as PriceComparator)}>{Object.entries(comparatorLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
          <label><span>目标价格</span><input aria-label="目标价格" type="number" min="0.001" step="0.01" value={threshold} onChange={(event) => setThreshold(Number(event.target.value))} /></label>
          <label><span>冷却秒数</span><input aria-label="冷却秒数" type="number" min="0" value={cooldown} onChange={(event) => setCooldown(Number(event.target.value))} /></label>
          <button type="button" className="run-button" aria-label="创建监控规则" onClick={() => void create()}><Plus size={15} />创建规则</button>
        </div>
      </section>
      {scope === "market" && <p className="scope-note">全市场任务可留空证券代码，将按数据库内全部在市 A 股分批扫描。</p>}
      <div className="monitor-grid">
        <section className="task-ledger">
          <div className="section-title"><div><span>监控任务</span><em>{tasks.length}</em></div><button type="button" className="ghost-button" onClick={async () => { const result = await client.scanMonitor(); setMessage(`手动扫描完成，触发 ${result.triggered} 条`); }}>立即扫描</button></div>
          {!tasks.length ? <div className="result-empty">尚未创建监控规则。</div> : <div className="task-list">{tasks.map((task) => <article key={task.task_id} className={task.enabled ? "" : "disabled"}><div><i className={task.comparator.includes("above") ? "up" : "down"} /><span>{task.enabled ? "监控中" : "已暂停"} · {task.scope === "market" ? "全市场" : "自选股"}</span></div><h3>{task.name}</h3><code>{task.symbols.length ? task.symbols.join(" · ") : "ALL A-SHARES"}</code><p>{comparatorLabels[task.comparator]} <strong>{task.threshold}</strong> · 冷却 {task.cooldown_seconds}s</p><footer><button type="button" onClick={async () => { const next = await client.toggleMonitorTask(task.task_id, !task.enabled); setTasks((current) => current.map((item) => item.task_id === task.task_id ? next : item)); }}>{task.enabled ? "暂停" : "启用"}</button><button type="button" aria-label={`删除监控 ${task.name}`} onClick={async () => { await client.deleteMonitorTask(task.task_id); setTasks((current) => current.filter((item) => item.task_id !== task.task_id)); }}><Trash2 size={13} /></button></footer></article>)}</div>}
        </section>
        <section className="signal-ledger">
          <div className="section-title"><div><span>最近触发</span></div><button type="button" className="ghost-button" disabled={!status?.feishu_configured} onClick={async () => { await client.testFeishu(); setMessage("飞书测试消息已发送"); }}><Bot size={13} />测试飞书</button></div>
          {!signals.length ? <div className="result-empty">暂无触发记录。</div> : <div className="signal-list">{signals.map((signal) => <article key={signal.signal_key}><time>{new Date(signal.triggered_at).toLocaleString("zh-CN")}</time><strong>{signal.symbol}</strong><p>{comparatorLabels[signal.comparator]} {signal.threshold}</p><b>{signal.price}</b></article>)}</div>}
        </section>
      </div>
    </main>
  );
}
