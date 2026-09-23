import { buildChartOption } from '../chart/chartOptions';
import { describe } from '../screener/presentation';
import { sourceMarks, type WatchSource } from '../watchlist/model';
import type { Bar, ChartIndicatorPoint } from '../../types';

it('retains named strategy groups and renders saved price and volume evidence on their original dates', () => {
  const bars: Bar[] = [1,2,3].map(i => ({symbol:'600001.SH',timestamp:`2026-09-0${i}T15:00:00+08:00`,open:10,high:12,low:9,close:11,volume_shares:i*100,amount_cny:10000}));
  const source: WatchSource = {run_id:'sq',as_of:'2026-09-03',mode:'sequoia',tree:{kind:'group',label:'Sequoia：海龟突破 / 均线金叉放量',logic:'or',children:[]},explanation:{path:'root',result:'true',children:[]},marks:[{metric:'close',timeframe:'1d',date:'2026-09-03',startDate:'2026-09-01',periods:3,label:'海龟突破'},{metric:'volume',timeframe:'1d',date:'2026-09-02',periods:1,label:'均线金叉放量'}]};
  expect(describe(source.tree,[])).toBe(source.tree.label);
  const indicators = bars.map(b=>({timestamp:b.timestamp,volume:b.volume_shares})) as unknown as ChartIndicatorPoint[];
  const option = buildChartOption(bars,[],indicators,[],sourceMarks(source));
  const series = option.series as {markArea?:unknown;markPoint?:{data:{coord:unknown[]}[]};xAxisIndex?:number}[];
  expect(series.filter(s=>s.markArea)).toHaveLength(1);
  const volume = series.find(s=>s.markPoint);
  expect(volume?.xAxisIndex).toBe(1);
  expect(volume?.markPoint?.data[0].coord).toEqual([bars[1].timestamp,200]);
});

it('海龟首日历史标记进入初始可视范围，并显示命名箭头', () => {
  const bars: Bar[] = Array.from({length:300},(_,i)=>({symbol:'600001.SH',timestamp:new Date(Date.UTC(2025,0,1+i)).toISOString(),open:10,high:12,low:9,close:11,volume_shares:100,amount_cny:10000}));
  const day=bars[20].timestamp.slice(0,10);
  const option=buildChartOption(bars,[],[],[],[{metric:'close',timeframe:'1d',date:day,startDate:day,periods:1,label:`海龟突破 · 首次满足 ${day}`}]);
  const zoom=option.dataZoom as Array<{start:number}>;
  expect(zoom[0].start).toBeLessThanOrEqual(20/300*100);
  const series=option.series as Array<{name?:string;markPoint?:{data:Array<{name:string;coord:unknown[]}>}}>;
  const signal=series.find(s=>s.name==='海龟突破信号');
  expect(signal?.markPoint?.data[0]).toEqual({name:'海龟突破',coord:[bars[20].timestamp,9]});
});

it('旧海龟快照也保留真实前高参考窗口，初始视图展示完整前置K线', () => {
  const bars: Bar[] = Array.from({length:300},(_,i)=>({symbol:'600001.SH',timestamp:new Date(Date.UTC(2025,0,1+i)).toISOString(),open:10,high:12,low:9,close:11,volume_shares:100,amount_cny:10000}));
  const day=bars[40].timestamp.slice(0,10), reference=bars[20].timestamp.slice(0,10);
  const source = {run_id:'sq',as_of:'2026-09-03',mode:'sequoia',tree:{kind:'group'},explanation:{path:'root',result:'true',children:[]},marks:[{metric:'close',timeframe:'1d',date:day,startDate:day,periods:1,label:`海龟突破 · 首次满足 ${day}`}],groups:[{id:'turtle',occurrences:[{date:day,checks:[{mark:{date:day,startDate:reference}}]}]}]} as unknown as WatchSource;
  const marks=sourceMarks(source);
  expect(marks[0].referenceStartDate).toBe(reference);
  expect(marks[0].startDate).toBe(day);
  const zoom=buildChartOption(bars,[],[],[],marks).dataZoom as Array<{start:number}>;
  expect(zoom[0].start).toBeLessThanOrEqual(20/300*100);
});
