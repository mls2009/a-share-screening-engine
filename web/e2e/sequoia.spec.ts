import { expect, test } from '@playwright/test';

test('Sequoia grouped evidence, chart marks, dark controls, JSON and target watch group', async ({ page }) => {
  const mark = {metric:'close',timeframe:'1d',date:'2026-09-04',startDate:'2026-08-19',periods:13,label:'海龟突破 · 收盘突破前高'};
  const volume = {...mark,metric:'volume',label:'海龟突破 · 成交量依据'};
  const config = {as_of:'2026-09-04',scope:'market',group_id:null,strategies:['turtle'],parameters:{}};
  const checks = [{label:'收盘突破前高',actual:12,expected:11,operator:'gt',result:'true',mark},{label:'成交量依据',actual:1000,expected:500,operator:'gt',result:'true',mark:volume}];
  const run = {run_id:'test',status:'completed',config,progress:100,message:'完成',data_date:'2026-09-04',universe_size:1,match_count:1,groups:[{id:'turtle',name:'海龟突破',matched:1,rejected:0,unknown:0,examples:[]}],matches:[{symbol:'600001.SH',name:'测试股票',close:12,change_percent:4,groups:[{id:'turtle',name:'海龟突破',checks}],source:{run_id:'test',as_of:'2026-09-04',mode:'sequoia',tree:{kind:'group'},explanation:{path:'root',result:'true',children:[]},marks:[mark,volume]}}]};
  let added: unknown;
  const bars = Array.from({length:13},(_,i)=>({symbol:'600001.SH',timestamp:`2026-${i<9?'08':'09'}-${String(i<9?19+i:i-8).padStart(2,'0')}T15:00:00+08:00`,open:10+i*.1,close:10.5+i*.1,high:11+i*.1,low:9+i*.1,volume_shares:1000+i*50,amount_cny:10000}));
  const indicators = bars.map(b=>({timestamp:b.timestamp,volume:b.volume_shares,ma_5:b.close,ma_20:b.close-.3}));
  await page.route('**/api/**',async route=>{
    const path = new URL(route.request().url()).pathname;
    let json: unknown = [];
    if(path==='/api/sequoia/catalog') json=[{id:'turtle',name:'海龟突破',description:'收盘突破此前高点',parameters:{window:{label:'前高窗口',default:20,min:2,max:250,integer:true}}}];
    else if(path==='/api/watchlist/groups') json=[{id:'g1',name:'长期观察'}];
    else if(path==='/api/sequoia/runs/test/watchlist') {added=route.request().postDataJSON();json={added:1};}
    else if(path==='/api/sequoia/runs') json=route.request().method()==='POST'?run:[run];
    else if(path==='/api/sequoia/runs/test') json=run;
    else if(path.endsWith('/bars')) json=bars;
    else if(path.endsWith('/indicators')) json=indicators;
    else if(path.endsWith('/overview')) json={symbol:'600001.SH',name:'测试股票',fundamentals:null};
    await route.fulfill({json});
  });
  await page.goto('/');
  await page.getByRole('button',{name:'Sequoia 选股',exact:true}).click();
  await expect(page.getByRole('heading',{name:'Sequoia 选股'})).toBeVisible();
  await page.getByText('JSON 配置导入 / 导出',{exact:true}).click();
  await page.getByLabel('选择 JSON 文件').setInputFiles({name:'sequoia.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(config))});
  await expect(page.getByLabel('截至日期',{exact:true})).toHaveValue('2026-09-04');
  await page.getByRole('button',{name:'开始分组选股'}).click();
  await page.getByLabel('选择当前分组全部股票').check();
  await page.getByLabel('添加到自选分组').selectOption('g1');
  await page.getByRole('button',{name:'批量加入自选（1）'}).click();
  await expect.poll(()=>added).toEqual({symbols:['600001.SH'],group_id:'g1',by_strategy:false});
  await page.getByRole('button',{name:'查看 测试股票 600001.SH'}).click();
  await expect(page.getByRole('heading',{name:'海龟突破',exact:true})).toBeVisible();
  await expect(page.getByRole('img',{name:'K 线与成交量图'})).toBeVisible();
  await page.getByRole('button',{name:/✓ 成交量依据/}).click();
  await expect(page.locator('.sq-detail canvas').first()).toBeVisible();
  const lightButtons = await page.locator('.sequoia-page button').evaluateAll(elements=>elements.filter(el=>{
    const c=getComputedStyle(el).backgroundColor.match(/\d+/g)?.map(Number);return c && c[0]>220 && c[1]>220 && c[2]>220 && (c.length<4 || c[3]>0);
  }).map(el=>el.textContent));
  expect(lightButtons).toEqual([]);
  const layout = await page.locator('.sq-detail .chart-page').evaluate(el => {
    const style = (selector: string) => getComputedStyle(el.querySelector(selector)!);
    const rect = (selector: string) => el.querySelector(selector)!.getBoundingClientRect();
    return {
      timeframePadding: style('.timeframe-toolbar button').paddingTop,
      timeframeFont: style('.timeframe-toolbar button').fontSize,
      indicatorPadding: style('.indicator-toolbar button').paddingTop,
      searchInputHeight: rect('.chart-heading input').height,
      searchHeight: rect('.chart-heading form').height,
      headingLeft: rect('.chart-heading').left,
      deskLeft: rect('.chart-desk').left,
    };
  });
  expect(parseFloat(layout.timeframePadding)).toBeLessThanOrEqual(2);
  expect(layout.timeframeFont).toBe('10px');
  expect(layout.indicatorPadding).toBe('0px');
  expect(layout.searchInputHeight).toBeLessThanOrEqual(layout.searchHeight);
  expect(Math.abs(layout.headingLeft-layout.deskLeft)).toBeLessThanOrEqual(1);
  await page.screenshot({path:'/tmp/astock-sequoia-desktop.png',fullPage:true});
  await page.setViewportSize({width:390,height:844});
  await expect(page.getByRole('button',{name:'Sequoia 选股',exact:true})).toBeVisible();
  await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  await page.locator(".sq-detail .chart-heading").scrollIntoViewIfNeeded();
  await page.screenshot({path:"/tmp/astock-sequoia-mobile-alignment.png"});
});

test('two strategies show separate colored signals and toggled legend', async ({ page }) => {
  const day='2026-09-04';
  const check=(name:string)=>({label:name,actual:2,expected:1,operator:'gte',result:'true',mark:{metric:'close',timeframe:'1d',date:day,startDate:day,periods:1,label:name}});
  const groups=[{id:'turtle',name:'海龟突破',checks:[check('收盘突破前高')]},{id:'rps',name:'RPS 强势近高点',checks:[check('全市场 RPS 百分位')]}];
  const config={as_of:day,period:'latest',scope:'market',group_id:null,strategies:['turtle','rps'],minimum_matches:2,parameters:{}};
  const run={run_id:'two',status:'completed',config,progress:100,message:'完成',data_date:day,universe_size:1,rps_universe_size:1,turtle_rule:'relative_volume_limit_close_fixed_level_v2',match_count:1,groups:groups.map(g=>({id:g.id,name:g.name,matched:1,rejected:0,unknown:0,examples:[]})),matches:[{symbol:'600001.SH',name:'测试股票',close:12,change_percent:4,groups,source:{run_id:'two',as_of:day,mode:'sequoia',tree:{kind:'group'},explanation:{path:'root',result:'true',children:[]},marks:groups.flatMap(g=>g.checks.map(c=>c.mark))}}]};
  const bars=Array.from({length:30},(_,i)=>({symbol:'600001.SH',timestamp:new Date(Date.UTC(2026,7,4+i)).toISOString(),open:10,close:11,high:12,low:9,volume_shares:1000,amount_cny:10000}));
  bars.push({...bars.at(-1)!,timestamp:`${day}T15:00:00+08:00`,close:12,high:12});
  await page.route('**/api/**',async route=>{
    const path=new URL(route.request().url()).pathname;
    let json:unknown=[];
    if(path==='/api/sequoia/catalog') json=groups.map(g=>({id:g.id,name:g.name,description:g.name,parameters:{}}));
    else if(path==='/api/sequoia/runs') json=route.request().method()==='POST'?run:[run];
    else if(path==='/api/sequoia/runs/two') json=run;
    else if(path.endsWith('/bars')) json=bars;
    else if(path.endsWith('/indicators')) json=bars.map(b=>({timestamp:b.timestamp,volume:b.volume_shares}));
    else if(path.endsWith('/overview')) json={symbol:'600001.SH',name:'测试股票',fundamentals:null};
    await route.fulfill({json});
  });
  await page.goto('/');
  await page.getByRole('button',{name:'Sequoia 选股',exact:true}).click();
  await page.getByLabel('选择策略 RPS 强势近高点').check();
  await page.getByLabel('同日最少命中策略数').selectOption('2');
  await page.getByRole('button',{name:'开始分组选股'}).click();
  await page.getByRole('button',{name:'查看 测试股票 600001.SH'}).click();
  const turtle=page.getByRole('button',{name:'图例 海龟突破'});
  const rps=page.getByRole('button',{name:'图例 RPS 强势近高点'});
  await expect(turtle).toHaveAttribute('aria-pressed','true');
  await expect(rps).toHaveAttribute('aria-pressed','true');
  expect(await turtle.locator('i').evaluate(el=>getComputedStyle(el).backgroundColor)).not.toBe(await rps.locator('i').evaluate(el=>getComputedStyle(el).backgroundColor));
  await expect(page.locator('.sq-detail canvas').first()).toBeVisible();
  await page.screenshot({path:'/tmp/astock-sequoia-two-strategies.png',fullPage:true});
  await rps.click();
  await expect(rps).toHaveAttribute('aria-pressed','false');
  await turtle.click();
  await expect(turtle).toHaveAttribute('aria-pressed','false');
});
