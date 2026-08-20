import { Brackets, Check, ChevronDown, Plus, Trash2 } from "lucide-react";

import type { MetricChoice, MetricSpec, Timeframe, UiConditionNode, UiGroupNode, UiNode } from "../../types";
import { createCondition, createGroup, removeNode, updateNode } from "./treeModel";

const operatorLabels: Record<string, string> = {
  eq: "等于", ne: "不等于", gt: "大于", gte: "至少", lt: "小于", lte: "至多",
  between: "介于", not_between: "不介于", crosses_above: "上穿", crosses_below: "下穿",
  at_least: "最近 N 次至少成立", continuous: "连续成立", in: "属于", not_in: "不属于",
};
const timeframeLabels: Record<Timeframe, string> = {
  "5m": "5 分", "15m": "15 分", "30m": "30 分", "60m": "60 分",
  "1d": "日线", "1w": "周线", "1mo": "月线",
};
const unitLabels: Record<string, string> = {
  price: "元", percent: "%", ratio: "倍", shares: "股", amount: "元", days: "周期",
  boolean: "", category: "", score: "分",
};
const groupLabels: Record<string, string> = {
  price: "价格行情",
  activity: "成交活跃度",
  technical: "技术指标",
  attributes: "股票属性",
  status: "交易状态",
  candlestick: "K 线形态",
  trend: "趋势与点位",
};

interface Props {
  tree: UiNode;
  catalog: MetricSpec[];
  onChange: (tree: UiNode) => void;
}

type Direction = NonNullable<UiConditionNode["direction"]>;

interface SelectorOption {
  value: string;
  label: string;
  family: string;
  direction?: Direction;
  metrics: MetricSpec[];
}

const metricGroup = (metric: MetricSpec) => metric.group ?? "technical";
const metricFamily = (metric: MetricSpec) => metric.family ?? metric.key;
const isDirection = (value: string): value is Direction => (
  ["rise", "fall", "increase", "decrease"] as string[]
).includes(value);

function selectorOptions(catalog: MetricSpec[], group: string): SelectorOption[] {
  const families = new Map<string, MetricSpec[]>();
  for (const metric of catalog.filter((item) => item.visible !== false && metricGroup(item) === group)) {
    const family = metricFamily(metric);
    families.set(family, [...(families.get(family) ?? []), metric]);
  }
  return [...families.entries()].flatMap(([family, metrics]) => {
    const directions = metrics[0]?.directions ?? [];
    if (directions.length) {
      return directions.filter((item) => isDirection(item.value)).map((item) => ({
        value: `${family}:${item.value}`,
        label: item.label,
        family,
        direction: item.value,
        metrics,
      }));
    }
    return [{ value: family, label: metrics[0]?.label ?? family, family, metrics }];
  });
}

function preferredMetric(metrics: MetricSpec[], current?: MetricSpec): MetricSpec {
  return metrics.find((metric) => metric.period === current?.period)
    ?? metrics.find((metric) => metric.period === 20)
    ?? metrics[0];
}

function preferredOperator(metric: MetricSpec): string {
  if (metric.multiple && metric.operators.includes("in")) return "in";
  if (metric.operators.includes("gte")) return "gte";
  if (metric.operators.includes("gt")) return "gt";
  return metric.operators[0];
}

function nextCondition(
  node: UiConditionNode,
  option: SelectorOption,
  current?: MetricSpec,
): UiConditionNode {
  const metric = preferredMetric(option.metrics, current);
  const timeframe = metric.timeframes.includes(node.timeframe)
    ? node.timeframe
    : metric.timeframes.includes("1d") ? "1d" : metric.timeframes[0];
  const firstChoice = metric.choices?.[0]?.value;
  return {
    ...node,
    metric: metric.key,
    timeframe,
    operator: preferredOperator(metric),
    right: { kind: "constant", value: metric.unit === "boolean" ? firstChoice ?? "true" : option.direction ? "30" : "0" },
    direction: option.direction,
    selectedValues: metric.multiple && firstChoice ? [firstChoice] : undefined,
    lookback: undefined,
    occurrences: undefined,
  };
}

function ChoicePanel({
  metric,
  selected,
  onChange,
}: {
  metric: MetricSpec;
  selected: string[];
  onChange: (values: string[]) => void;
}) {
  const choices = metric.choices ?? [];
  const selectedLabels = choices.filter((choice) => selected.includes(choice.value)).map((choice) => choice.label);
  const toggle = (choice: MetricChoice) => {
    if (selected.includes(choice.value)) {
      if (selected.length > 1) onChange(selected.filter((value) => value !== choice.value));
    } else {
      onChange([...selected, choice.value]);
    }
  };
  return (
    <details className="choice-panel">
      <summary aria-label={`选择${metric.label}选项`}>
        <span>{selectedLabels.length <= 2 ? selectedLabels.join(" / ") : `已选 ${selectedLabels.length} 项`}</span>
        <ChevronDown size={13} />
      </summary>
      <div className="choice-popover">
        {choices.map((choice) => (
          <label key={choice.value}>
            <input type="checkbox" checked={selected.includes(choice.value)} onChange={() => toggle(choice)} />
            <i><Check size={11} /></i><span>{choice.label}</span>
          </label>
        ))}
      </div>
    </details>
  );
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
  const group = metricGroup(spec);
  const groups = [...new Set(catalog.filter((metric) => metric.visible !== false).map(metricGroup))];
  const options = selectorOptions(catalog, group);
  const family = metricFamily(spec);
  const selectorValue = node.direction ? `${family}:${node.direction}` : family;
  const familyMetrics = catalog.filter((metric) => metricFamily(metric) === family);
  const periods = familyMetrics.filter((metric) => metric.period != null).sort((a, b) => Number(a.period) - Number(b.period));
  const metricPeers = catalog.filter((metric) => metric.unit === spec.unit);
  const metricOperand = node.right.kind === "metric" ? node.right : null;
  const directionalOperators = new Set(["gte", "lte", "between", "not_between"]);
  const operators = node.direction
    ? spec.operators.filter((operator) => directionalOperators.has(operator))
    : spec.operators;

  const changeGroup = (nextGroup: string) => {
    const option = selectorOptions(catalog, nextGroup)[0];
    if (option) onUpdate(nextCondition(node, option, spec));
  };
  const changeSelector = (value: string) => {
    const option = options.find((item) => item.value === value);
    if (option) onUpdate(nextCondition(node, option, spec));
  };
  const changePeriod = (period: number) => {
    const metric = periods.find((item) => item.period === period);
    if (metric) onUpdate({ ...node, metric: metric.key });
  };

  return (
    <div className="condition-row">
      <div className="condition-path">
        <select aria-label="指标分类" value={group} onChange={(event) => changeGroup(event.target.value)}>
          {groups.map((item) => <option key={item} value={item}>{groupLabels[item] ?? item}</option>)}
        </select>
        <span>/</span>
        <select aria-label="指标" value={selectorValue} onChange={(event) => changeSelector(event.target.value)}>
          {options.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
        </select>
        {periods.length > 1 && <><span>/</span><select aria-label="计算周期" value={spec.period ?? ""} onChange={(event) => changePeriod(Number(event.target.value))}>
          {periods.map((metric) => <option key={metric.key} value={metric.period ?? ""}>{metric.period} 周期</option>)}
        </select></>}
      </div>
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
        {operators.map((operator) => <option key={operator} value={operator}>{operatorLabels[operator] ?? operator}</option>)}
      </select>
      {spec.multiple ? (
        <ChoicePanel metric={spec} selected={node.selectedValues ?? [spec.choices?.[0]?.value ?? ""]} onChange={(selectedValues) => onUpdate({ ...node, selectedValues })} />
      ) : spec.unit === "boolean" ? (
        <select aria-label="比较值" value={node.right.kind === "constant" ? node.right.value : ""} onChange={(event) => onUpdate({ ...node, right: { kind: "constant", value: event.target.value } })}>
          {(spec.choices ?? []).map((choice) => <option key={choice.value} value={choice.value}>{choice.label}</option>)}
        </select>
      ) : (
        <>
          {!node.direction && <select
            aria-label="比较类型"
            value={node.right.kind}
            onChange={(event) => {
              const right = event.target.value === "metric"
                ? { kind: "metric" as const, metric: metricPeers[0]?.key ?? node.metric, timeframe: node.timeframe, multiplier: 1 }
                : { kind: "constant" as const, value: "0" };
              onUpdate({ ...node, right });
            }}
          ><option value="constant">固定值</option><option value="metric">另一指标</option></select>}
          {node.right.kind === "constant" ? (
            <label className="value-field">
              <input aria-label="比较值" value={node.right.value} placeholder={node.operator.includes("between") ? "10, 30" : "0"} onChange={(event) => onUpdate({ ...node, right: { kind: "constant", value: event.target.value } })} />
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
        </>
      )}
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
        <select aria-label="组合逻辑" value={node.logic} onChange={(event) => {
          const logic = event.target.value as UiGroupNode["logic"];
          setGroup({ ...node, logic, children: logic === "not" ? node.children.slice(0, 1) : node.children });
        }}>
          <option value="and">AND 全部成立</option><option value="or">OR 任一成立</option><option value="not">NOT 条件取反</option>
        </select>
        <div className="group-actions">
          <button type="button" aria-label={`${groupName}添加条件`} disabled={node.logic === "not" && node.children.length >= 1} onClick={() => setGroup({ ...node, children: [...node.children, createCondition()] })}><Plus size={14} />条件</button>
          <button type="button" aria-label={`${groupName}添加子分组`} disabled={node.logic === "not" && node.children.length >= 1} onClick={() => setGroup({ ...node, children: [...node.children, createGroup()] })}><Plus size={14} />分组</button>
        </div>
      </header>
      <div className="group-children">
        {node.children.map((child) => child.kind === "condition" ? (
          <ConditionRow key={child.id} node={child} catalog={catalog} onUpdate={(next) => setGroup(updateNode(node, child.id, () => next) as UiGroupNode)} onRemove={() => setGroup(removeNode(node, child.id) as UiGroupNode)} />
        ) : (
          <Group key={child.id} node={child} catalog={catalog} root={false} onChange={(next) => setGroup(updateNode(node, child.id, () => next) as UiGroupNode)} />
        ))}
      </div>
    </section>
  );
}

export function ConditionTree({ tree, catalog, onChange }: Props) {
  if (tree.kind !== "group") return null;
  return <Group node={tree} catalog={catalog} root onChange={onChange} />;
}
