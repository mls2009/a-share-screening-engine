import { buildChartOption } from '../chart/chartOptions';
import type { Bar } from '../../types';
import { sequoiaChartMarks } from './chartMarks';
import type { EvidenceGroup } from './api';

it('collapses each strategy and day to a named, distinct colored chart signal', () => {
  const day='2026-05-01';
  const check=(label:string, metric:string) => ({label,actual:1,expected:1,operator:'gte',result:'true',mark:{metric,timeframe:'1d' as const,date:day,startDate:day,periods:1,label}});
  const groups:EvidenceGroup[]=[
    {id:'turtle',name:'海龟突破',checks:[check('突破前高','close'),check('相对放量','volume')]},
    {id:'rps',name:'RPS 强势',checks:[check('RPS 百分位','close'),check('接近高点','high')]},
  ];
  const marks=sequoiaChartMarks(groups);
  expect(marks).toHaveLength(2);
  expect(marks.map(mark=>mark.strategyId)).toEqual(['turtle','rps']);
  const bars:Bar[]=[{symbol:'600001.SH',timestamp:`${day}T15:00:00+08:00`,open:10,high:11,low:9,close:11,volume_shares:100,amount_cny:1000}];
  const option=buildChartOption(bars,[],[],[],marks);
  const series=option.series as Array<{name?:string;markPoint?:{itemStyle:{color:string}};markArea?:unknown}>;
  const signals=series.filter(item=>item.name?.endsWith('信号'));
  expect(signals).toHaveLength(2);
  expect(signals.map(item=>item.markPoint?.itemStyle.color)).toEqual(['#f3c969','#6bc5ff']);
  expect(series.filter(item=>item.markArea)).toHaveLength(0);
});

it('renders many dates of one strategy in a single chart series', () => {
  const days=['2026-05-01','2026-05-02'];
  const bars:Bar[]=days.map(day=>({symbol:'600001.SH',timestamp:`${day}T15:00:00+08:00`,open:10,high:11,low:9,close:11,volume_shares:100,amount_cny:1000}));
  const marks=days.map(day=>({metric:'close',timeframe:'1d' as const,date:day,startDate:day,periods:1,label:`RPS 强势 · 命中 ${day}`,strategyId:'rps',strategyName:'RPS 强势'}));
  const series=buildChartOption(bars,[],[],[],marks).series as Array<{name?:string;markPoint?:{data:unknown[]}}>;
  const signals=series.filter(item=>item.name==='RPS 强势信号');
  expect(signals).toHaveLength(1);
  expect(signals[0].markPoint?.data).toHaveLength(2);
});
