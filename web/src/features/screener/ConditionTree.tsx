import { Brackets, Plus, Trash2 } from "lucide-react";

import type { MetricSpec, Timeframe, UiConditionNode, UiGroupNode, UiNode } from "../../types";
import { createCondition, createGroup, removeNode, updateNode } from "./treeModel";

const operatorLabels: Record<string, string> = {
  eq: "等于", ne: "不等于", gt: "大于", gte: "大于等于", lt: "小于", lte: "小于等于",
  between: "介于", not_between: "不介于", crosses_above: "上穿", crosses_below: "下穿",
  at_least: "最近 N 次至少成立", continuous: "连续成立",
};
const timeframeLabels: Record<Timeframe, string> = {
  "5m": "5 分", "15m": "15 分", "30m": "30 分", "60m": "60 分",
  "1d": "日线", "1w": "周线", "1mo": "月线",
};
const unitLabels: Record<string, string> = {
  price: "元", percent: "%", ratio: "倍", shares: "股", amount: "元", days: "周期",
  boolean: "", category: "", score: "分",
};

interface Props {
  tree: UiNode;
  catalog: MetricSpec[];
  onChange: (tree: UiNode) => void;
}

function ConditionRow({
  node,
  catalog,
  onUpdate,
  onRemove,
}: {
  node: UiConditionNode;
  catalog: MetricSpec[];
  onUpdate: (next: UiConditionNode) => void;
  onRemove: () => void;
}) {
  const spec = catalog.find((metric) => metric.key === node.metric) ?? catalog[0];
  if (!spec) return null;
  const metricPeers = catalog.filter((metric) => metric.unit === spec.unit);
  const metricOperand = node.right.kind === "metric" ? node.right : null;

  const changeMetric = (metricKey: string) => {
    const next = catalog.find((metric) => metric.key === metricKey)!;
    const timeframe = next.timeframes.includes(node.timeframe)
      ? node.timeframe
      : next.timeframes.includes("1d") ? "1d" : next.timeframes[0];
    onUpdate({
      ...node,
      metric: metricKey,
      timeframe,
      operator: next.operators[0],
      right: { kind: "constant", value: next.unit === "boolean" ? "true" : "0" },
    });
  };

  return (
    <div className="condition-row">
      <select aria-label="指标" value={node.metric} onChange={(event) => changeMetric(event.target.value)}>
        {catalog.map((metric) => <option key={metric.key} value={metric.key}>{metric.label}</option>)}
      </select>
      <select
        aria-label="周期"
        value={node.timeframe}
        onChange={(event) => onUpdate({ ...node, timeframe: event.target.value as Timeframe })}
      >
        {spec.timeframes.map((timeframe) => <option key={timeframe} value={timeframe}>{timeframeLabels[timeframe]}</option>)}
      </select>
      <select
        aria-label="操作符"
        value={node.operator}
        onChange={(event) => onUpdate({ ...node, operator: event.target.value })}
      >
        {spec.operators.map((operator) => <option key={operator} value={operator}>{operatorLabels[operator] ?? operator}</option>)}
      </select>
      <select
        aria-label="比较类型"
        value={node.right.kind}
        onChange={(event) => {
          const right = event.target.value === "metric"
            ? { kind: "metric" as const, metric: metricPeers[0]?.key ?? node.metric, timeframe: node.timeframe, multiplier: 1 }
            : { kind: "constant" as const, value: "0" };
          onUpdate({ ...node, right });
        }}
      >
        <option value="constant">固定值</option>
        <option value="metric">另一指标</option>
      </select>
      {node.right.kind === "constant" ? (
        <label className="value-field">
          {spec.unit === "boolean" ? (
            <select aria-label="比较值" value={node.right.value} onChange={(event) => onUpdate({ ...node, right: { kind: "constant", value: event.target.value } })}>
              <option value="true">是</option><option value="false">否</option>
            </select>
          ) : (
            <input
              aria-label="比较值"
              value={node.right.value}
              placeholder={node.operator.includes("between") ? "10, 30" : "0"}
              onChange={(event) => onUpdate({ ...node, right: { kind: "constant", value: event.target.value } })}
            />
          )}
          <span>{unitLabels[spec.unit]}</span>
        </label>
      ) : metricOperand ? (
        <div className="metric-operand">
          <select aria-label="对比指标" value={metricOperand.metric} onChange={(event) => onUpdate({ ...node, right: { ...metricOperand, metric: event.target.value } })}>
            {metricPeers.map((metric) => <option key={metric.key} value={metric.key}>{metric.label}</option>)}
          </select>
          <input aria-label="倍数" type="number" step="0.1" value={metricOperand.multiplier} onChange={(event) => onUpdate({ ...node, right: { ...metricOperand, multiplier: Number(event.target.value) } })} />
        </div>
      ) : null}
      {(["at_least", "continuous"].includes(node.operator)) && (
        <div className="lookback-fields">
          <input aria-label="回看周期" type="number" min="1" value={node.lookback ?? 5} onChange={(event) => onUpdate({ ...node, lookback: Number(event.target.value) })} />
          {node.operator === "at_least" && <input aria-label="成立次数" type="number" min="1" value={node.occurrences ?? 3} onChange={(event) => onUpdate({ ...node, occurrences: Number(event.target.value) })} />}
        </div>
      )}
      <button type="button" className="icon-button danger" aria-label="删除条件" onClick={onRemove}><Trash2 size={15} /></button>
    </div>
  );
}

function Group({ node, catalog, root, onChange }: { node: UiGroupNode; catalog: MetricSpec[]; root: boolean; onChange: (tree: UiNode) => void }) {
  const groupName = root ? "根分组" : "子分组";
  const setGroup = (next: UiGroupNode) => onChange(next);
  return (
    <section className={`condition-group ${root ? "root-group" : "nested-group"}`}>
      <header className="group-header">
        <Brackets size={16} />
        <select
          aria-label="组合逻辑"
          value={node.logic}
          onChange={(event) => {
            const logic = event.target.value as UiGroupNode["logic"];
            setGroup({ ...node, logic, children: logic === "not" ? node.children.slice(0, 1) : node.children });
          }}
        >
          <option value="and">AND 全部成立</option>
          <option value="or">OR 任一成立</option>
          <option value="not">NOT 条件取反</option>
        </select>
        <div className="group-actions">
          <button
            type="button"
            aria-label={`${groupName}添加条件`}
            disabled={node.logic === "not" && node.children.length >= 1}
            onClick={() => setGroup({ ...node, children: [...node.children, createCondition(catalog[0]?.key)] })}
          ><Plus size={14} />条件</button>
          <button
            type="button"
            aria-label={`${groupName}添加子分组`}
            disabled={node.logic === "not" && node.children.length >= 1}
            onClick={() => setGroup({ ...node, children: [...node.children, createGroup()] })}
          ><Plus size={14} />分组</button>
        </div>
      </header>
      <div className="group-children">
        {node.children.map((child) => child.kind === "condition" ? (
          <ConditionRow
            key={child.id}
            node={child}
            catalog={catalog}
            onUpdate={(next) => setGroup(updateNode(node, child.id, () => next) as UiGroupNode)}
            onRemove={() => setGroup(removeNode(node, child.id) as UiGroupNode)}
          />
        ) : (
          <Group
            key={child.id}
            node={child}
            catalog={catalog}
            root={false}
            onChange={(next) => setGroup(updateNode(node, child.id, () => next) as UiGroupNode)}
          />
        ))}
      </div>
    </section>
  );
}

export function ConditionTree({ tree, catalog, onChange }: Props) {
  if (tree.kind !== "group") return null;
  return <Group node={tree} catalog={catalog} root onChange={onChange} />;
}
