import { buildManualZonePayload } from "./drawing";

it("用两个锚点构建手动趋势支撑价格区间", () => {
  const payload = buildManualZonePayload(
    "1d", "support", "trend",
    [{ date: "2026-08-01", price: 10 }, { date: "2026-08-20", price: 11 }],
  );

  expect(payload).toMatchObject({
    timeframe: "1d",
    as_of_date: "2026-08-20",
    zone_kind: "support",
    geometry: "trend",
    center_price: 11,
    anchors: [["2026-08-01", 10], ["2026-08-20", 11]],
  });
  expect(payload.slope).toBeGreaterThan(0);
  expect(payload.lower_price).toBeLessThan(11);
  expect(payload.upper_price).toBeGreaterThan(11);
});
