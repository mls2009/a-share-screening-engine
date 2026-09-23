import { render, screen } from "@testing-library/react";
import { api } from "../../api";
import { StockOverview } from "./StockOverview";
afterEach(() => vi.restoreAllMocks());
it("shows valuations with units, original timestamp and absent values", async () => {
  vi.spyOn(api, "stockOverview").mockResolvedValue({ symbol: "600519.SH", name: "贵州茅台", exchange: "SH", board: "main", listed_on: null, quote: { timestamp: "2026-09-08T15:00:00+08:00", source: "tencent", price: 12, pe_ratio: -5, total_market_cap: 1200000000, float_market_cap: 800000000, volume_shares: 100, amount_cny: 1200 }, message: null, valuation_note: "腾讯原值" });
  render(<StockOverview symbol="600519.SH" />);
  expect(await screen.findByText("-5 倍")).toBeInTheDocument();
  expect(screen.getByText("12 亿")).toBeInTheDocument();
  expect(screen.getByText("8 亿")).toBeInTheDocument();
  expect(screen.getAllByText("暂无").length).toBeGreaterThan(0);
  expect(screen.getByText(/2026-09-08 15:00:00/)).toBeInTheDocument();
});
