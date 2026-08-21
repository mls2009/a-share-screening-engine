import { api } from "./api";

afterEach(() => {
  vi.unstubAllGlobals();
});

it("K线页面每类最多请求三条自动支撑压力线", async () => {
  const fetchMock = vi.fn().mockResolvedValue(
    new Response(JSON.stringify([]), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }),
  );
  vi.stubGlobal("fetch", fetchMock);

  await api.zones("600519.SH", "1d", "2026-08-21");

  expect(fetchMock.mock.calls[0][0]).toBe(
    "/api/symbols/600519.SH/zones?timeframe=1d&as_of=2026-08-21&limit_each=3",
  );
});

it("按代码或中文名称搜索证券", async () => {
  const fetchMock = vi.fn().mockResolvedValue(
    new Response(JSON.stringify([]), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }),
  );
  vi.stubGlobal("fetch", fetchMock);

  await api.searchSymbols("创业板 ETF");

  expect(fetchMock.mock.calls[0][0]).toBe(
    "/api/symbols/search?q=%E5%88%9B%E4%B8%9A%E6%9D%BF+ETF",
  );
});
