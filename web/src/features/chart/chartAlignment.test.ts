// @vitest-environment node
import * as echarts from "echarts";
import { buildChartOption } from "./chartOptions";

it("aligns each candle with volume and indicator dates before and after zoom and resize", () => {
  const bars = Array.from({ length: 60 }, (_, index) => ({
    symbol: "600001.SH", timestamp: new Date(Date.UTC(2026, 0, index + 1)).toISOString(),
    open: 10, close: 11, low: 9, high: 12, volume_shares: 123456789 + index, amount_cny: 100000,
  }));
  const chart = echarts.init(null, undefined, { renderer: "svg", ssr: true, width: 960, height: 600 });
  try {
    const indicators = bars.map((bar) => ({
      timestamp: bar.timestamp, ma_5: null, ma_10: null, ma_20: null, ma_30: null,
      boll_upper: null, boll_middle: null, boll_lower: null,
      macd: 0.2, macd_signal: 0.1, macd_hist: 0.2,
      kdj_k: null, kdj_d: null, kdj_j: null, rsi_14: null,
      volume_ma_5: null, volume_ma_20: null, obv: null, atr_14: null,
    }));
    chart.setOption(buildChartOption(bars, [], indicators, ["macd"]));
    const check = () => {
      for (const index of [20, 30, 40]) {
        const candle = chart.convertToPixel({ xAxisIndex: 0 }, index);
        expect(chart.convertToPixel({ xAxisIndex: 1 }, index)).toBeCloseTo(candle, 5);
        expect(chart.convertToPixel({ xAxisIndex: 2 }, index)).toBeCloseTo(candle, 5);
      }
    };
    check();
    chart.dispatchAction({ type: "dataZoom", start: 25, end: 80 });
    check();
    chart.resize({ width: 375, height: 600 });
    check();
  } finally { chart.dispose(); }
});
