import type { ECharts } from "echarts/core";
import type { Bar } from "../../types";

// Overlay lines remain clipped to the candle viewport instead of expanding it.
export function attachPriceScale(chart: ECharts, bars: Bar[]): () => void {
  const update = () => {
    if (!bars.length) return;
    const zoom = (chart.getOption().dataZoom as Array<{start?: number; end?: number}> | undefined)?.[0];
    const first = Math.max(0, Math.round((zoom?.start ?? 0) / 100 * (bars.length - 1)));
    const last = Math.min(bars.length - 1, Math.round((zoom?.end ?? 100) / 100 * (bars.length - 1)));
    let low = Infinity, high = -Infinity;
    for (let index = first; index <= last; index++) {
      if (Number.isFinite(bars[index].low)) low = Math.min(low, bars[index].low);
      if (Number.isFinite(bars[index].high)) high = Math.max(high, bars[index].high);
    }
    if (!Number.isFinite(low) || !Number.isFinite(high)) return;
    const padding = Math.max((high - low) * .08, Math.abs(high) * .001, .01);
    chart.setOption({ yAxis: [{ min: Math.max(0, low - padding), max: high + padding }] });
  };
  chart.on("datazoom", update);
  update();
  return () => { chart.off("datazoom", update); };
}
