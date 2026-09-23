import { expect, test } from '@playwright/test';

test('后到的指标保留用户缩放及拖动视角', async ({ page }) => {
  let release!: () => void;
  const indicatorsReady = new Promise<void>(resolve => { release = resolve; });
  const bars = Array.from({length:240}, (_, i) => ({
    symbol:'600519.SH', timestamp:new Date(Date.UTC(2026,0,i+1,7)).toISOString(),
    open:20+i*.01, high:21+i*.01, low:19+i*.01, close:20.5+i*.01,
    volume_shares:1000, amount_cny:20000,
  }));
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname;
    let json: unknown = [];
    if (path.endsWith('/bars')) json = bars;
    if (path.endsWith('/overview')) json = {symbol:'600519.SH', name:'测试股票', fundamentals:null};
    if (path.endsWith('/indicators')) {
      await indicatorsReady;
      json = bars.map(bar => ({timestamp:bar.timestamp, ma_120:18, ma_250:17}));
    }
    await route.fulfill({json});
  });
  await page.goto('/');
  await page.getByRole('button',{name:'K 线研究',exact:true}).click();
  const element = page.getByRole('img',{name:'K 线与成交量图'});
  await element.scrollIntoViewIfNeeded();
  const state = async (move = false) => element.evaluate(async (target, move) => {
    const moduleUrl = performance.getEntriesByType('resource').map(r=>r.name).find(name=>name.includes('/echarts_core.js'))!;
    const echarts = await import(moduleUrl);
    const chart = echarts.getInstanceByDom(target);
    if (move) chart.dispatchAction({type:'dataZoom',start:15,end:40});
    const option = chart.getOption();
    return {id:chart.id, start:option.dataZoom[0].start, end:option.dataZoom[0].end,
      ma120:option.series.find((s: {name:string})=>s.name==='MA120')?.data[0]};
  }, move);
  const before = await state(true);
  expect(before).toMatchObject({start:15,end:40});
  release();
  await expect.poll(()=>state()).toMatchObject({...before, ma120:18});
  await page.setViewportSize({width:1000,height:900});
  await expect.poll(()=>state()).toMatchObject({...before, ma120:18});
});
