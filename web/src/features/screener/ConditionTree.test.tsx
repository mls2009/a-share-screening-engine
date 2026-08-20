import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";

import type { MetricSpec, UiGroupNode } from "../../types";
import { ConditionTree } from "./ConditionTree";
import { createGroup } from "./treeModel";

const catalog: MetricSpec[] = [
  { key: "return_20", label: "20周期涨跌幅", unit: "percent", timeframes: ["1d"], operators: ["gte", "lt"] },
  { key: "volume", label: "成交量", unit: "shares", timeframes: ["15m", "1d", "1w"], operators: ["gt"] },
];

function Harness() {
  const [tree, setTree] = useState<UiGroupNode>(() => createGroup());
  return <ConditionTree tree={tree} catalog={catalog} onChange={(next) => setTree(next as UiGroupNode)} />;
}

describe("ConditionTree", () => {
  it("可在根分组增加条件和嵌套分组", async () => {
    render(<Harness />);

    await userEvent.click(screen.getByRole("button", { name: "根分组添加条件" }));
    expect(screen.getAllByLabelText("指标")).toHaveLength(2);

    await userEvent.click(screen.getByRole("button", { name: "根分组添加子分组" }));
    expect(screen.getAllByLabelText("组合逻辑")).toHaveLength(2);
  });

  it("指标改变后同步可用操作符", async () => {
    render(<Harness />);
    await userEvent.selectOptions(screen.getByLabelText("指标"), "volume");
    expect(screen.getByLabelText("操作符")).toHaveValue("gt");
    expect(screen.getByLabelText("周期")).toHaveValue("1d");
  });
});
