import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { App } from "./App";

describe("App", () => {
  it("展示选股工作台和全部主要模块", () => {
    render(<App />);

    expect(screen.getByRole("heading", { name: "选股工作台" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "条件选股" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "K 线研究" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "策略回测" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "实时监控" })).toBeInTheDocument();
  });

  it("可以切换到 K 线研究页", async () => {
    render(<App />);
    expect(screen.getByRole("button", { name: "条件选股" })).toHaveAttribute("aria-current", "page");
    await userEvent.click(screen.getByRole("button", { name: "K 线研究" }));
    expect(screen.getByRole("button", { name: "K 线研究" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("button", { name: "条件选股" })).not.toHaveAttribute("aria-current");
    expect(await screen.findByRole("heading", { name: "K 线研究" })).toBeInTheDocument();
    expect(await screen.findByLabelText("证券代码或名称")).toHaveValue("600519.SH");
  });
});
