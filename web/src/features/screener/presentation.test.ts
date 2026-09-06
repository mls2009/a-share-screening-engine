import { describe, boundaryText, metricLabel } from "./presentation";
import { cloneNode, createGroup, moveNode, toApiNode } from "./treeModel";
import type { MetricSpec } from "../../types";
const catalog: MetricSpec[] = [
  {key:"close",label:"收盘价",unit:"price",timeframes:["1d"],operators:["gt"]},
  {key:"ma_20",label:"移动平均线",period:20,unit:"price",timeframes:["1d"],operators:["gt"]},
  {key:"return_20",label:"价格涨跌",period:20,unit:"percent",timeframes:["1d"],operators:["gte"]},
];
it("describes the lookback and the moving average period separately",()=>{
  const text=describe({kind:"condition",metric:"close",timeframe:"1d",operator:"continuous",lookback:5,right:{kind:"metric",metric:"ma_20",timeframe:"1d"}},catalog);
  expect(text).toContain("5 个交易日");expect(text).toContain("20周期");expect(text).toContain("大于");
  expect(metricLabel("1d:ma_20",catalog)).toContain("日线");
});
it("expresses threshold distance in percentage points",()=>{
  expect(boundaryText({kind:"condition",operator:"lte"},{path:"root",result:"true",actual:.95,expected:1,unit:"percent",children:[]})).toContain("0.0500个百分点");
});
it("shows units for form strings and multipliers for metric comparisons",()=>{
  const node=createGroup().children[0];
  if(node.kind!=="condition") throw new Error("expected condition");
  expect(describe({...node,metric:"return_20",right:{kind:"constant",value:"30"}},catalog)).toContain("30%");
  expect(describe({...node,metric:"close",right:{kind:"metric",metric:"ma_20",timeframe:"1d",multiplier:1.05}},catalog)).toContain("× 1.05");
});
it("duplicates with fresh ids and omits paused conditions",()=>{
  const root=createGroup();const copy=cloneNode(root.children[0]);
  expect(copy.id).not.toBe(root.children[0].id);
  root.children.push({...copy,disabled:true});
  expect((toApiNode(root,catalog) as {children:unknown[]}).children).toHaveLength(1);
});
it("moves conditions between groups without allowing cycles",()=>{
  const root=createGroup();const child=createGroup();root.children.push(child);
  const moved=moveNode(root,root.children[0].id,child.id);
  expect(moved.kind==="group" && moved.children.length).toBe(1);
  expect(moveNode(root,child.id,child.id)).toEqual(root);
});
