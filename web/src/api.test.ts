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
