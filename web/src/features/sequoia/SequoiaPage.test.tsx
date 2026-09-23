import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { SequoiaPage } from './SequoiaPage';
import { parseConfig, sequoiaApi, type Run, type Strategy } from './api';

vi.mock('../chart/ChartPage', () => ({ ChartPage: (props: {watchSource: {marks: {label: string}[]}}) => <div data-testid="chart-marks">{props.watchSource.marks.map(m => m.label).join('/')}</div> }));
const catalog: Strategy[] = [{ id: 'turtle', name: '海龟突破', description: '突破此前高点', parameters: {window:{label:'前高窗口',default:20,min:2,max:250,integer:true}} }, {id:'rps',name:'RPS 强势',description:'全市场排名',parameters:{}}];
const mark = {metric:'close',timeframe:'1d' as const,date:'2026-05-01',startDate:'2026-04-01',periods:21,label:'海龟突破 · 收盘突破前高'};
const run: Run = {run_id:'r1',status:'completed',progress:100,message:'完成',config:{as_of:'2026-05-01',scope:'market',group_id:null,strategies:['turtle'],parameters:{}},data_date:'2026-05-01',universe_size:3,match_count:1,groups:[{id:'turtle',name:'海龟突破',matched:1,rejected:1,unknown:1,examples:[{symbol:'600003.SH',reason:'停更'}]}],matches:[{symbol:'600001.SH',name:'测试股票',close:11,change_percent:10,groups:[{id:'turtle',name:'海龟突破',checks:[{label:'收盘突破前高',actual:11,expected:10.5,operator:'gt',result:'true',mark}]}],source:{run_id:'r1',as_of:'2026-05-01',mode:'sequoia',tree:{kind:'group'},explanation:{path:'root',result:'true',children:[]},marks:[mark]}}]};
beforeEach(() => {
  vi.spyOn(sequoiaApi,'catalog').mockResolvedValue(catalog);
  vi.spyOn(sequoiaApi,'groups').mockResolvedValue([{id:'g1',name:'长期观察'}]);
  vi.spyOn(sequoiaApi,'history').mockResolvedValue([run]);
  vi.spyOn(sequoiaApi,'run').mockResolvedValue(run);
  vi.spyOn(sequoiaApi,'start').mockResolvedValue(run);
  vi.spyOn(sequoiaApi,'add').mockResolvedValue({added:1});
  Element.prototype.scrollIntoView = vi.fn();
});
afterEach(() => vi.restoreAllMocks());
it('runs by strategy, displays evidence groups, preserves marks and adds to a selected group', async () => {
  render(<SequoiaPage />);
  await screen.findByText('突破此前高点');
  fireEvent.click(screen.getByRole('button',{name:'开始分组选股'}));
  await screen.findByText('测试股票');
  fireEvent.click(screen.getByLabelText('选择当前分组全部股票'));
  fireEvent.change(screen.getByLabelText('添加到自选分组'),{target:{value:'g1'}});
  fireEvent.click(screen.getByRole('button',{name:'批量加入自选（1）'}));
  await waitFor(() => expect(sequoiaApi.add).toHaveBeenCalledWith('r1',['600001.SH'],'g1'));
  fireEvent.click(screen.getByRole('button',{name:'查看 测试股票 600001.SH'}));
  expect(await screen.findByRole('heading',{name:'海龟突破'})).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button',{name:/✓ 收盘突破前高/}));
  expect(await screen.findByTestId('chart-marks')).toHaveTextContent(mark.label);
});
it('loads a historical snapshot and defaults to native strategy watch groups', async () => {
  render(<SequoiaPage />);
  await screen.findByText('突破此前高点');
  fireEvent.change(screen.getByLabelText('Sequoia 历史记录'),{target:{value:'r1'}});
  await screen.findByText('测试股票');
  fireEvent.click(screen.getByRole('button',{name:'加入自选'}));
  await waitFor(() => expect(sequoiaApi.add).toHaveBeenCalledWith('r1',['600001.SH'],'strategy'));
});
it('imports configuration and rejects unrelated condition JSON without overwriting the form', async () => {
  render(<SequoiaPage />); await screen.findByText('突破此前高点');
  fireEvent.change(screen.getByLabelText('Sequoia JSON 配置'), {target:{value:JSON.stringify({...run.config,strategies:['rps']})}});
  fireEvent.click(screen.getByRole('button',{name:'导入 JSON'}));
  expect(screen.getByLabelText('选择策略 RPS 强势')).toBeChecked();
  fireEvent.change(screen.getByLabelText('Sequoia JSON 配置'),{target:{value:'{"kind":"group"}'}});
  fireEvent.click(screen.getByRole('button',{name:'导入 JSON'}));
  expect(await screen.findByRole('alert')).toHaveTextContent('不支持');
  expect(screen.getByLabelText('选择策略 RPS 强势')).toBeChecked();
});
it('validates parameter ranges, integers and unknown strategy IDs', () => {
  for(const config of [{...run.config,strategies:['x']},{...run.config,parameters:{turtle:{window:1}}},{...run.config,parameters:{turtle:{window:2.5}}}]) expect(()=>parseConfig(JSON.stringify(config),catalog)).toThrow();
  expect(parseConfig(JSON.stringify(run.config),catalog)).toEqual(run.config);
});

it('选择近两年提交历史范围，并展示多次命中日期', async () => {
  const historical = structuredClone(run);
  historical.config.period='2y'; historical.range_start='2024-05-01'; historical.observation_days=250;
  const group=historical.matches![0].groups[0];
  group.occurrences=[{date:'2026-04-01',end_date:'2026-04-20',days:14,breakout_level:10.5,ended_on:'2026-04-21',active:false,checks:group.checks},{date:'2026-05-01',checks:group.checks}];
  vi.mocked(sequoiaApi.start).mockResolvedValue(historical);
  render(<SequoiaPage />); await screen.findByText('突破此前高点');
  fireEvent.change(screen.getByLabelText('识别时间范围'),{target:{value:'2y'}});
  fireEvent.click(screen.getByRole('button',{name:'开始分组选股'}));
  await screen.findByText('测试股票');
  expect(sequoiaApi.start).toHaveBeenCalledWith(expect.objectContaining({period:'2y'}));
  fireEvent.click(screen.getByRole('button',{name:'查看 测试股票 600001.SH'}));
  expect(await screen.findByText('2026-04-01 ～ 2026-04-20 · 阶段内 14 根日线 · 1 项首日条件满足')).toBeInTheDocument();
  expect(screen.getByText('2026-05-01 · 1 项首日条件满足')).toBeInTheDocument();
});

it('股票详情可按当前结果排序切换上下只并处理首尾边界', async () => {
  const multiple=structuredClone(run);
  multiple.matches!.push({...structuredClone(multiple.matches![0]),symbol:'600002.SH',name:'第二只',change_percent:20});
  vi.mocked(sequoiaApi.start).mockResolvedValue(multiple);
  render(<SequoiaPage />); await screen.findByText('突破此前高点');
  fireEvent.click(screen.getByRole('button',{name:'开始分组选股'}));
  fireEvent.click(await screen.findByRole('button',{name:'查看 测试股票 600001.SH'}));
  expect(screen.getByRole('button',{name:'↑ 上一只'})).toBeDisabled();
  expect(screen.getByText('1 / 2')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button',{name:'↓ 下一只'}));
  expect(screen.getByRole('heading',{name:'第二只 600002.SH'})).toBeInTheDocument();
  expect(screen.getByRole('button',{name:'↓ 下一只'})).toBeDisabled();
  fireEvent.change(screen.getByLabelText('排序'),{target:{value:'change'}});
  expect(screen.getByText('1 / 2')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button',{name:'↓ 下一只'}));
  expect(screen.getByRole('heading',{name:'测试股票 600001.SH'})).toBeInTheDocument();
});

it('selects a minimum of two strategies and keeps JSON configuration aligned', async () => {
  render(<SequoiaPage />);
  await screen.findByText('突破此前高点');
  fireEvent.click(screen.getByLabelText('选择策略 RPS 强势'));
  fireEvent.change(screen.getByLabelText('同日最少命中策略数'), {target:{value:'2'}});
  fireEvent.click(screen.getByRole('button',{name:'开始分组选股'}));
  expect(sequoiaApi.start).toHaveBeenCalledWith(expect.objectContaining({strategies:['turtle','rps'], minimum_matches:2}));
  expect(() => parseConfig(JSON.stringify({...run.config,strategies:['turtle'],minimum_matches:2}),catalog)).toThrow();
});

it('uses named strategy legend to hide and restore one strategy without changing screening results', async () => {
  const multiple=structuredClone(run);
  const match=multiple.matches![0];
  const rpsMark={...mark,label:'RPS 强势 · 全市场 RPS 百分位',strategyId:'rps',strategyName:'RPS 强势'};
  match.groups.push({id:'rps',name:'RPS 强势',checks:[{label:'全市场 RPS 百分位',actual:100,expected:90,operator:'gte',result:'true',mark:rpsMark}]});
  match.source.marks=[{...mark,strategyId:'turtle'},rpsMark];
  vi.mocked(sequoiaApi.start).mockResolvedValue(multiple);
  render(<SequoiaPage />); await screen.findByText('突破此前高点');
  fireEvent.click(screen.getByRole('button',{name:'开始分组选股'}));
  fireEvent.click(await screen.findByRole('button',{name:'查看 测试股票 600001.SH'}));
  expect(await screen.findByTestId('chart-marks')).toHaveTextContent('RPS 强势');
  fireEvent.click(screen.getByRole('button',{name:'图例 RPS 强势'}));
  expect(screen.getByRole('button',{name:'图例 RPS 强势'})).toHaveAttribute('aria-pressed','false');
  expect(screen.getByTestId('chart-marks')).not.toHaveTextContent('RPS 强势');
  fireEvent.click(screen.getByRole('button',{name:'图例 RPS 强势'}));
  expect(screen.getByTestId('chart-marks')).toHaveTextContent('RPS 强势');
});
