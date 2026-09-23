import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { api } from "../../api";
import { MarketSearch } from "./MarketSearch";
afterEach(() => vi.restoreAllMocks());
it("searches the whole market and adds a result to the chosen group", async () => {
  const stock = { symbol: "600519.SH", name: "贵州茅台", exchange: "SH" as const, instrument_type: "stock" as const };
  const search = vi.spyOn(api, "searchSymbols").mockResolvedValue([stock]);
  const add = vi.spyOn(api, "addWatchlist").mockResolvedValue({ ...stock, sources: [] });
  const updated = vi.fn().mockResolvedValue(undefined);
  render(<MarketSearch items={[]} groups={[{ id: "g1", name: "长期观察" }]} onAdded={updated} onOpen={vi.fn()} />);
  fireEvent.change(screen.getByLabelText("全市场股票搜索"), { target: { value: "600519" } });
  expect(await screen.findByText("贵州茅台")).toBeInTheDocument();
  expect(search).toHaveBeenCalledWith("600519");
  fireEvent.change(screen.getByLabelText("搜索添加目标分组"), { target: { value: "g1" } });
  fireEvent.click(screen.getByRole("button", { name: /^加入自选$/ }));
  await waitFor(() => expect(add).toHaveBeenCalledWith("600519.SH", undefined, "g1"));
  expect(updated).toHaveBeenCalled();
});
