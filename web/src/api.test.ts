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

it("K线页面按当前周期读取技术指标", async () => {
  const fetchMock = vi.fn().mockResolvedValue(
    new Response(JSON.stringify([]), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }),
  );
  vi.stubGlobal("fetch", fetchMock);

  await api.indicators("600519.SH", "1d", "2026-01-01", "2026-08-21");

  expect(fetchMock.mock.calls[0][0]).toBe(
    "/api/symbols/600519.SH/indicators?timeframe=1d&start=2026-01-01&end=2026-08-21",
  );
});

it("大盘对比请求携带当前下钻的精确时间窗口", async () => {
  const fetchMock = vi.fn().mockResolvedValue(
    new Response(JSON.stringify({ points: [] }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }),
  );
  vi.stubGlobal("fetch", fetchMock);

  await api.benchmarkComparison(
    "600519.SH",
    "15m",
    "2026-08-20",
    "2026-08-20",
    "2026-08-20T09:30:00+08:00",
    "2026-08-20T10:30:00+08:00",
  );

  expect(fetchMock.mock.calls[0][0]).toBe(
    "/api/symbols/600519.SH/benchmark-comparison?timeframe=15m&start=2026-08-20&end=2026-08-20&start_at=2026-08-20T09%3A30%3A00%2B08%3A00&end_at=2026-08-20T10%3A30%3A00%2B08%3A00",
  );
});

it("定向同步只提交当前图表范围", async () => {
  const fetchMock = vi.fn().mockResolvedValue(
    new Response(JSON.stringify({ stock_bars: 12, benchmark_bars: 12 }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }),
  );
  vi.stubGlobal("fetch", fetchMock);

  await api.syncChartData("600519.SH", {
    timeframe: "15m",
    start: "2026-08-20",
    end: "2026-08-20",
    include_benchmark: true,
  });

  expect(fetchMock.mock.calls[0][0]).toBe("/api/symbols/600519.SH/chart-data/sync");
  expect(fetchMock.mock.calls[0][1]).toMatchObject({
    method: "POST",
    body: JSON.stringify({
      timeframe: "15m",
      start: "2026-08-20",
      end: "2026-08-20",
      include_benchmark: true,
    }),
  });
});
