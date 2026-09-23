import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { api } from "../../api";
import { WatchlistPage } from "./WatchlistPage";

vi.mock("../chart/ChartPage", () => ({ ChartPage: () => <div>股票详情图表</div> }));
vi.mock("./HistoryWaves", () => ({ HistoryWaves: () => <div>历史条件工具</div> }));
const stock = { symbol: "600001.SH", name: "测试股票", sources: [], groups: [{ id: "g1", name: "芯片观察" }], quote: { date: "2026-09-04", close: 12.3, change_percent: 2.5 } };
let events: EventTarget;
let closeEvents: ReturnType<typeof vi.fn>;
beforeEach(() => {
  closeEvents = vi.fn();
  vi.stubGlobal("EventSource", class extends EventTarget {
    close = closeEvents;
    constructor() { super(); events = this; queueMicrotask(() => this.dispatchEvent(new Event("ready"))); }
  });
  vi.spyOn(api, "watchlist").mockResolvedValue([stock]);
  vi.spyOn(api, "watchGroups").mockResolvedValue(stock.groups);
  vi.spyOn(api, "catalog").mockResolvedValue([]);
});
afterEach(() => { vi.restoreAllMocks(); vi.useRealTimers(); vi.unstubAllGlobals(); });

it("shows quotes and groups in the list and opens details only after selection", async () => {
  render(<WatchlistPage />);
  expect(await screen.findByText("12.30")).toBeInTheDocument();
  expect(screen.getByText("+2.50%")).toBeInTheDocument();
  expect(screen.getByText("最近成交 2026-09-04")).toBeInTheDocument();
  expect(screen.getAllByText("芯片观察").length).toBeGreaterThan(0);
  expect(screen.queryByText("股票详情图表")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "查看详情" }));
  expect(screen.getByText("股票详情图表")).toBeInTheDocument();
  const chart = screen.getByText("股票详情图表");
  expect(chart.compareDocumentPosition(screen.getByRole("region", { name: "股票行情与估值" })) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(chart.compareDocumentPosition(screen.getByText("历史条件工具")) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(screen.queryByPlaceholderText("搜索名称或代码")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "返回自选股" }));
  fireEvent.click(screen.getByRole("button", { name: /^未分组$/ }));
  expect(screen.queryByText("12.30")).not.toBeInTheDocument();
});

it("refreshes only on entry and completion events, then closes the subscription", async () => {
  vi.useFakeTimers();
  const view = render(<WatchlistPage />);
  await act(async () => { await Promise.resolve(); });
  expect(screen.getByText("12.30")).toBeInTheDocument();
  vi.mocked(api.watchlist).mockResolvedValue([{ ...stock, quote: { date: "2026-09-07", close: 13, change_percent: -1 } }]);
  const calls = vi.mocked(api.watchlist).mock.calls.length;
  await act(async () => { await vi.advanceTimersByTimeAsync(60000); });
  expect(api.watchlist).toHaveBeenCalledTimes(calls);
  await act(async () => { events.dispatchEvent(new Event("market-updated")); });
  expect(screen.getByText("13.00")).toBeInTheDocument();
  expect(screen.getByText("最近成交 2026-09-07")).toBeInTheDocument();
  view.unmount();
  expect(closeEvents).toHaveBeenCalled();
});

it("creates groups through the persisted API", async () => {
  const create = vi.spyOn(api, "createWatchGroup").mockResolvedValue({ id: "g2", name: "重点关注" });
  render(<WatchlistPage />);
  await screen.findByText("12.30");
  fireEvent.click(screen.getByText("管理我的分组"));
  fireEvent.change(screen.getByLabelText("分组名称"), { target: { value: "重点关注" } });
  fireEvent.click(screen.getByRole("button", { name: "创建分组" }));
  await waitFor(() => expect(create).toHaveBeenCalledWith("重点关注"));
});


it("distinguishes suspension status from last traded date", async () => {
  vi.mocked(api.watchlist).mockResolvedValue([{ ...stock, trading_status: { date: "2026-09-08", is_suspended: true } }]);
  render(<WatchlistPage />);
  expect(await screen.findByText("停牌")).toBeInTheDocument();
  expect(screen.getByText("状态截至 2026-09-08")).toBeInTheDocument();
  expect(screen.getByText("最近成交 2026-09-04")).toBeInTheDocument();
  expect(screen.queryByText("+2.50%")).not.toBeInTheDocument();
});

it("prefers current quote return over old adjusted daily data", async () => {
  vi.mocked(api.watchlist).mockResolvedValue([{ ...stock, current_quote: { date: "2026-09-08", timestamp: "2026-09-08T15:00:00+08:00", close: 13, change_percent: -1.25, source: "tencent" } }]);
  render(<WatchlistPage />);
  expect(await screen.findByText("-1.25%")).toBeInTheDocument();
  expect(screen.queryByText("+2.50%")).not.toBeInTheDocument();
  expect(screen.getByText("相对昨收 · 2026-09-08")).toBeInTheDocument();
});
