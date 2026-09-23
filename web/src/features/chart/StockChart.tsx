import { BarChart, CandlestickChart, LineChart } from "echarts/charts";
import {
  AxisPointerComponent,
  DataZoomComponent,
  GridComponent,
  MarkAreaComponent,
  MarkLineComponent,
  MarkPointComponent,
  TooltipComponent,
} from "echarts/components";
import * as echarts from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";
import { type CSSProperties, useEffect, useRef } from "react";

import type { Bar, ChartIndicator, ChartIndicatorPoint, PriceZone } from "../../types";
import { buildChartOption } from "./chartOptions";
import { attachPriceScale } from "./priceScale";
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
  MarkPointComponent,
  TooltipComponent,
]);

export interface StockChartProps {
  captureRef?: { current: (() => string) | null };
  bars: Bar[];
  viewKey?: string;
  zones: PriceZone[];
  indicators?: ChartIndicatorPoint[];
  selectedIndicators?: ChartIndicator[];
  marks?: import("../watchlist/model").ConditionMark[];
  drawing?: boolean;
  onAnchor?: (anchor: DrawingAnchor) => void;
  onBarSelect?: (bar: Bar) => void;
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

export function StockChart({ captureRef, bars, viewKey, zones, indicators = [], selectedIndicators, marks = [], drawing = false, onAnchor, onBarSelect }: StockChartProps) {
  const element = useRef<HTMLDivElement>(null);
  const chartRef = useRef<echarts.ECharts | null>(null);
  const previousView = useRef<string | null>(null);
  const currentView = viewKey ?? `${bars[0]?.symbol}:${bars[0]?.timestamp}:${bars.at(-1)?.timestamp}:${bars.length}`;
  const anchorCallback = useRef(onAnchor);
  const barSelectCallback = useRef(onBarSelect);
  anchorCallback.current = onAnchor;
  barSelectCallback.current = onBarSelect;

  useEffect(() => {
    if (!element.current) return;
    const chart = chartRef.current ?? echarts.init(element.current, undefined, { renderer: "canvas" });
    chartRef.current = chart;
    if (captureRef) captureRef.current = () => chart.getDataURL({type: "png", pixelRatio: 1, backgroundColor: "#0b0d0f"});
    const option = buildChartOption(bars, zones, indicators, selectedIndicators, marks);
    if (previousView.current === currentView) {
      const zoom = (chart.getOption()?.dataZoom as Array<{ start?: number; end?: number }> | undefined)?.[0];
      if (zoom && Number.isFinite(zoom.start) && Number.isFinite(zoom.end) && Array.isArray(option.dataZoom)) {
        option.dataZoom = option.dataZoom.map(item => ({ ...item, start: zoom.start, end: zoom.end }));
      }
    }
    previousView.current = currentView;
    chart.setOption(option, true);
    const detachPriceScale = attachPriceScale(chart, bars);
    const resize = () => chart.resize();
    const resizeObserver = typeof ResizeObserver === "undefined" ? undefined : new ResizeObserver(resize);
    resizeObserver?.observe(element.current);
    window.addEventListener("resize", resize);
    const selectAnchor = (event: { offsetX: number; offsetY: number }) => {
      if (!anchorCallback.current) return;
      const point = chart.convertFromPixel({ gridIndex: 0 }, [event.offsetX, event.offsetY]);
      if (!Array.isArray(point) || !Number.isFinite(Number(point[0])) || !Number.isFinite(Number(point[1]))) return;
      const index = Math.max(0, Math.min(bars.length - 1, Math.round(Number(point[0]))));
      const bar = bars[index];
      if (bar) anchorCallback.current({ date: bar.timestamp.slice(0, 10), price: Number(Number(point[1]).toFixed(3)) });
    };
    const selectBar = (params: { seriesType?: unknown; dataIndex?: unknown }) => {
      if (
        drawing
        || params.seriesType !== "candlestick"
        || typeof params.dataIndex !== "number"
        || !Number.isInteger(params.dataIndex)
      ) return;
      const bar = bars[params.dataIndex];
      if (bar) barSelectCallback.current?.(bar);
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
    chart.getZr().on("click", selectAnchor);
    chart.on("click", selectBar);
    chart.on("mousemove", showLineTooltip);
    chart.on("mouseout", hideLineTooltip);
    return () => {
      chart.getZr().off("click", selectAnchor);
      chart.off("click", selectBar);
      chart.off("mousemove", showLineTooltip);
      chart.off("mouseout", hideLineTooltip);
      resizeObserver?.disconnect();
      window.removeEventListener("resize", resize);
      detachPriceScale();
    };
  }, [bars, currentView, drawing, indicators, selectedIndicators, zones, marks]);

  useEffect(() => () => {
    if (captureRef) captureRef.current = null;
    chartRef.current?.dispose();
    chartRef.current = null;
    previousView.current = null;
  }, []);

  const subPaneCount = (selectedIndicators?.filter((item) => ["macd", "kdj", "rsi", "obv", "atr"].includes(item)).length ?? 0) + new Set(marks.filter((mark) => !/^(ma_\d+$|open$|close$|high$|low$|pattern_|volume$)/.test(mark.metric)).map((mark) => mark.metric)).size;
  const chartStyle = {
    "--chart-height": `${560 + subPaneCount * 120}px`,
    "--chart-mobile-height": `${440 + subPaneCount * 110}px`,
  } as CSSProperties;
  return <><div className="limit-color-legend"><span><i style={{ background: "#ffca45" }} />收盘涨停</span><span><i style={{ background: "#a78bfa" }} />收盘跌停</span><small>日线按未复权收盘价与当日涨跌停价判断；缺少数据不着色，盘中触板不算收盘封板。</small></div><div ref={element} style={chartStyle} className={`stock-chart ${drawing ? "drawing" : ""}`} role="img" aria-label="K 线与成交量图" /></>;
}
