// @vitest-environment node
import * as echarts from "echarts";
import { attachPriceScale } from "./priceScale";
import { buildChartOption } from "./chartOptions";
import type { ChartIndicatorPoint } from "../../types";
it("keeps zoomed candle heights readable despite distant moving averages", () => {
  const bars = Array.from({length:60}, (_,i) => ({symbol:"600001.SH",timestamp:new Date(Date.UTC(2026,0,i+1)).toISOString(),open:i<30?100:10,close:i<30?110:11,low:i<30?99:9,high:i<30?112:12,volume_shares:100,amount_cny:1000}));
  const indicators = bars.map(bar => ({timestamp:bar.timestamp,ma_30:90})) as ChartIndicatorPoint[];
  const chart = echarts.init(null,undefined,{renderer:"svg",ssr:true,width:960,height:600});
  try {
    chart.setOption(buildChartOption(bars,[],indicators,["ma"]));
    attachPriceScale(chart, bars);
    chart.dispatchAction({type:"dataZoom",start:70,end:100});
    const height = Math.abs(Number(chart.convertToPixel({yAxisIndex:0},12))-Number(chart.convertToPixel({yAxisIndex:0},9)));
    expect(height).toBeGreaterThan(200);
    chart.dispatchAction({type:"dataZoom",start:85,end:100});
    expect(Math.abs(Number(chart.convertToPixel({yAxisIndex:0},12))-Number(chart.convertToPixel({yAxisIndex:0},9)))).toBeCloseTo(height, 5);
    chart.dispatchAction({type:"dataZoom",start:0,end:20});
    expect(Number(chart.convertToPixel({yAxisIndex:0},100))).toBeGreaterThan(30);
    chart.resize({width:390,height:600});
    expect(Number.isFinite(Number(chart.convertToPixel({yAxisIndex:0},110)))).toBe(true);
  } finally {chart.dispose();}
});
