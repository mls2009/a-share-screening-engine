import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { MonitorStatus, MonitorTask } from "../../types";
import { MonitorPage } from "./MonitorPage";

const task: MonitorTask = {
  task_id: "task-1", name: "茅台突破 1500", symbols: ["600519.SH"],
  comparator: "cross_above", threshold: 1500, cooldown_seconds: 300,
  scope: "watchlist", enabled: true, created_at: "2026-08-20", updated_at: "2026-08-20",
};
const stopped: MonitorStatus = {
  running: false, tasks: 1, enabled_tasks: 1, pending_notifications: 0,
  feishu_configured: true, watchlist_interval_seconds: 5, market_interval_seconds: 300,
};

describe("MonitorPage", () => {
  it("创建点位规则、启动监控并展示历史信号", async () => {
    const client = {
      monitorTasks: vi.fn().mockResolvedValue([task]),
      monitorStatus: vi.fn().mockResolvedValue(stopped),
      monitorSignals: vi.fn().mockResolvedValue([{ signal_key: "s1", symbol: "600519.SH", price: 1501, threshold: 1500, comparator: "cross_above", triggered_at: "2026-08-20T10:00:00+08:00" }]),
      createMonitorTask: vi.fn().mockResolvedValue(task),
      toggleMonitorTask: vi.fn().mockResolvedValue(task),
      deleteMonitorTask: vi.fn().mockResolvedValue(undefined),
      startMonitor: vi.fn().mockResolvedValue({ running: true }),
      stopMonitor: vi.fn().mockResolvedValue({ running: false }),
      scanMonitor: vi.fn().mockResolvedValue({ triggered: 0 }),
      testFeishu: vi.fn().mockResolvedValue({ success: true }),
    };
    render(<MonitorPage client={client} />);

    expect(await screen.findByRole("heading", { name: "实时监控" })).toBeInTheDocument();
    expect(await screen.findByText("茅台突破 1500")).toBeInTheDocument();
    expect(screen.getAllByText("600519.SH")).toHaveLength(2);
    await userEvent.click(screen.getByRole("button", { name: "启动实时监控" }));
    expect(client.startMonitor).toHaveBeenCalledOnce();
    expect(await screen.findByText("运行中")).toBeInTheDocument();

    await userEvent.clear(screen.getByLabelText("监控名称"));
    await userEvent.type(screen.getByLabelText("监控名称"), "平安跌破 10");
    await userEvent.click(screen.getByRole("button", { name: "创建监控规则" }));
    expect(client.createMonitorTask).toHaveBeenCalledOnce();
  });
});
