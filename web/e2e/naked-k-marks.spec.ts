import { expect, test } from '@playwright/test';

test('筛选结果打开完整K线保留一年内多次裸K标记', async ({page}) => {
  const tree = {kind:'condition',metric:'pa_bull_pinbar',timeframe:'1d',operator:'eq',right:{kind:'constant',value:true,unit:'boolean'}};
  const explanation={result:'true',actual:true,expected:true,data_time:'2026-09-04',children:[]};
  const match={symbol:'000012.SZ',features:{name:'测试股票',close:10,feature_date:'2026-09-04'},explanation};
  const source={run_id:'r1',as_of:'2026-09-05',mode:'close',tree,explanation,marks:[{metric:'close',timeframe:'1d',date:'2026-09-04',periods:1,label:'裸K：看涨Pinbar（下影占比>2/3）：True'},{metric:'close',timeframe:'1d',date:'2026-03-04',periods:1,label:'裸K：看涨Pinbar · 2026-03-04'}]};
  await page.addInitScript(({match,tree})=>localStorage.setItem('astock.screener.workspace.v2',JSON.stringify({result:{run_id:'r1',matches:[match],match_count:1,universe_size:1,realtime_covered:0,failed_batches:0,diagnostics:{conditions:{},warnings:[],data_dates:{}}},runTree:tree})),{match,tree});
  await page.route('**/api/**',async route=>{
    const path=new URL(route.request().url()).pathname;
    let json:unknown=[];
    if(path==='/api/catalog') json=[{key:'pa_bull_pinbar',label:'裸K看涨Pinbar',unit:'boolean',timeframes:['1d'],operators:['eq'],group:'candlestick'}];
    if(path.includes('/detail/')) json={symbol:match.symbol,features:match.features,source,recent:[]};
    if(path.endsWith('/overview')) json={symbol:match.symbol,name:'测试股票',fundamentals:null};
    if(path.endsWith('/bars')) json=['2026-03-04','2026-09-04'].map(date=>({symbol:match.symbol,timestamp:date+'T15:00:00+08:00',open:10,close:10.1,low:8,high:10.2,volume_shares:1000,amount_cny:10000}));
    await route.fulfill({json});
  });
  await page.goto('/');
  await page.getByRole('button',{name:'查看 000012.SZ K 线',exact:true}).click();
  const chart=page.getByRole('img',{name:'K 线与成交量图'});
  await expect(chart).toBeVisible();
  const overview = page.getByRole('region', {name:'股票行情与估值'});
  await expect(overview).toBeAttached();
  expect(await chart.evaluate(target => Boolean(target.compareDocumentPosition(document.querySelector('[aria-label="股票行情与估值"]')!) & Node.DOCUMENT_POSITION_FOLLOWING))).toBe(true);
  await expect.poll(()=>chart.evaluate(async target=>{
    const url=performance.getEntriesByType('resource').map(x=>x.name).find(x=>x.includes('/echarts_core.js'))!;
    const echarts=await import(url);
    const series=echarts.getInstanceByDom(target)?.getOption().series ?? [];
    return series.flatMap((s:{markPoint?:{data?:Array<{name:string}>}})=>s.markPoint?.data??[]).map((p:{name:string})=>p.name);
  })).toEqual(['看涨Pinbar','看涨Pinbar']);
});
