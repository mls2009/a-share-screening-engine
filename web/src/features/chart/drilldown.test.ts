import type { Bar, Timeframe } from "../../types";
import { drillWindow, drilldownTimeframes, filterWindowBars } from "./drilldown";

const bar = (timestamp: string): Bar => ({
  symbol: "600001.SH",
  timestamp,
  open: 10,
  high: 11,
  low: 9,
  close: 10.5,
  volume_shares: 1_000,
  amount_cny: 10_500,
});

it.each<[Timeframe, Timeframe[]]>([
  ["1mo", ["1w", "1d", "60m", "30m", "15m", "5m"]],
  ["1w", ["1d", "60m", "30m", "15m", "5m"]],
  ["1d", ["60m", "30m", "15m", "5m"]],
  ["60m", ["30m", "15m", "5m"]],
  ["30m", ["15m", "5m"]],
  ["15m", ["5m"]],
  ["5m", []],
])("%s 只提供更小的可下钻周期", (timeframe, expected) => {
  expect(drilldownTimeframes(timeframe)).toEqual(expected);
});

it("按自然月、交易周和交易日建立下钻窗口", () => {
  expect(drillWindow(bar("2026-08-31T15:00:00+08:00"), "1mo", "1d")).toMatchObject({
    timeframe: "1d", start: "2026-08-01", end: "2026-08-31", label: "2026-08",
  });
  expect(drillWindow(bar("2026-08-21T15:00:00+08:00"), "1w", "1d")).toMatchObject({
    timeframe: "1d", start: "2026-08-17", end: "2026-08-21", label: "2026-08-17～08-21",
  });
  expect(drillWindow(bar("2026-08-20T15:00:00+08:00"), "1d", "15m")).toMatchObject({
    timeframe: "15m", start: "2026-08-20", end: "2026-08-20", label: "2026-08-20",
  });
});

it("分钟父 K 使用左开右闭的精确时间窗口", () => {
  const window = drillWindow(bar("2026-08-20T10:30:00+08:00"), "60m", "15m");

  expect(window).toMatchObject({
    timeframe: "15m",
    start: "2026-08-20",
    end: "2026-08-20",
    startAt: "2026-08-20T09:30:00+08:00",
    endAt: "2026-08-20T10:30:00+08:00",
  });
  expect(filterWindowBars([
    bar("2026-08-20T09:30:00+08:00"),
    bar("2026-08-20T09:45:00+08:00"),
    bar("2026-08-20T10:30:00+08:00"),
    bar("2026-08-20T10:45:00+08:00"),
  ], window).map((item) => item.timestamp)).toEqual([
    "2026-08-20T09:45:00+08:00",
    "2026-08-20T10:30:00+08:00",
  ]);
});

it("拒绝同级或向上钻取", () => {
  expect(() => drillWindow(bar("2026-08-20T15:00:00+08:00"), "1d", "1w"))
    .toThrow("目标周期必须小于当前周期");
});
