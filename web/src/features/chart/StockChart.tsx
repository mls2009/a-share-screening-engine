import { BarChart, CandlestickChart, LineChart } from "echarts/charts";
import {
  AxisPointerComponent,
  DataZoomComponent,
  GridComponent,
  MarkAreaComponent,
  MarkLineComponent,
  TooltipComponent,
} from "echarts/components";
import * as echarts from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";
import { type CSSProperties, useEffect, useRef } from "react";

import type { Bar, ChartIndicator, ChartIndicatorPoint, PriceZone } from "../../types";
import { buildChartOption } from "./chartOptions";
import type { DrawingAnchor } from "./drawing";

echarts.use([
  AxisPointerComponent,
  BarChart,
  CandlestickChart,
  CanvasRenderer,
  DataZoomComponent,
  GridComponent,
  LineChart,
  MarkAreaComponent,
  MarkLineComponent,
  TooltipComponent,
]);

export interface StockChartProps {
  bars: Bar[];
  zones: PriceZone[];
  indicators?: ChartIndicatorPoint[];
  selectedIndicators?: ChartIndicator[];
  drawing?: boolean;
  onAnchor?: (anchor: DrawingAnchor) => void;
}

type ChartLinePointerParams = {
  seriesType?: unknown;
  selfType?: unknown;
  seriesIndex?: unknown;
  event?: {
    offsetX?: unknown;
    offsetY?: unknown;
  };
};

function linePointerParams(params: unknown): ChartLinePointerParams | undefined {
  if (typeof params !== "object" || params === null) return undefined;
  const candidate = params as ChartLinePointerParams;
  if (
    candidate.seriesType !== "line"
    || candidate.selfType !== "line"
    || typeof candidate.seriesIndex !== "number"
    || !Number.isInteger(candidate.seriesIndex)
    || candidate.seriesIndex < 0
  ) return undefined;
  return candidate;
}

export function StockChart({ bars, zones, indicators = [], selectedIndicators, drawing = false, onAnchor }: StockChartProps) {
  const element = useRef<HTMLDivElement>(null);
  const anchorCallback = useRef(onAnchor);
  anchorCallback.current = onAnchor;

  useEffect(() => {
    if (!element.current) return;
    const chart = echarts.init(element.current, undefined, { renderer: "canvas" });
    chart.setOption(buildChartOption(bars, zones, indicators, selectedIndicators), true);
    const resize = () => chart.resize();
    const resizeObserver = typeof ResizeObserver === "undefined" ? undefined : new ResizeObserver(resize);
    resizeObserver?.observe(element.current);
    window.addEventListener("resize", resize);
    const click = (event: { offsetX: number; offsetY: number }) => {
      if (!anchorCallback.current) return;
      const point = chart.convertFromPixel({ gridIndex: 0 }, [event.offsetX, event.offsetY]);
      if (!Array.isArray(point) || !Number.isFinite(Number(point[0])) || !Number.isFinite(Number(point[1]))) return;
      const index = Math.max(0, Math.min(bars.length - 1, Math.round(Number(point[0]))));
      const bar = bars[index];
      if (bar) anchorCallback.current({ date: bar.timestamp.slice(0, 10), price: Number(Number(point[1]).toFixed(3)) });
    };
    const showLineTooltip = (params: unknown) => {
      const line = linePointerParams(params);
      if (!line) return;
      const offsetX = line.event?.offsetX;
      const offsetY = line.event?.offsetY;
      if (
        bars.length === 0
        || typeof offsetX !== "number"
        || !Number.isFinite(offsetX)
        || typeof offsetY !== "number"
        || !Number.isFinite(offsetY)
      ) return;
      const point = chart.convertFromPixel({ gridIndex: 0 }, [offsetX, offsetY]);
      if (
        !Array.isArray(point)
        || typeof point[0] !== "number"
        || !Number.isFinite(point[0])
        || typeof point[1] !== "number"
        || !Number.isFinite(point[1])
      ) return;
      const dataIndex = Math.max(0, Math.min(bars.length - 1, Math.round(point[0])));
      chart.dispatchAction({ type: "showTip", seriesIndex: line.seriesIndex, dataIndex });
    };
    const hideLineTooltip = (params: unknown) => {
      if (!linePointerParams(params)) return;
      chart.dispatchAction({ type: "hideTip" });
    };
    chart.getZr().on("click", click);
    chart.on("mousemove", showLineTooltip);
    chart.on("mouseout", hideLineTooltip);
    return () => {
      chart.getZr().off("click", click);
      chart.off("mousemove", showLineTooltip);
      chart.off("mouseout", hideLineTooltip);
      resizeObserver?.disconnect();
      window.removeEventListener("resize", resize);
      chart.dispose();
    };
  }, [bars, indicators, selectedIndicators, zones]);

  const subPaneCount = selectedIndicators?.filter((item) => ["macd", "kdj", "rsi", "obv", "atr"].includes(item)).length ?? 0;
  const chartStyle = {
    "--chart-height": `${560 + subPaneCount * 120}px`,
    "--chart-mobile-height": `${440 + subPaneCount * 110}px`,
  } as CSSProperties;
  return <div ref={element} style={chartStyle} className={`stock-chart ${drawing ? "drawing" : ""}`} role="img" aria-label="K 线与成交量图" />;
}
