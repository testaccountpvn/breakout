// Browser smoke checks use isolated responses; fixtures never enter SQLite.
const assert = require('node:assert/strict');
const path = require('node:path');
const { chromium } = require('C:/Users/Sony/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
(async () => {
  const browser = await chromium.launch({headless:true, channel:'msedge'});
  try {
    const page=await browser.newPage({viewport:{width:1440,height:1100}}), errors=[];
    page.on('pageerror',e=>errors.push(e.message));
    await page.goto('http://127.0.0.1:8765/work/app/index.html');
    await page.locator('[data-screen="scanner"]').first().click();
    await page.locator('[data-candle-symbol="SBIN"]').waitFor();
    await page.waitForFunction(()=>document.querySelector('.capture-status')?.textContent.includes('Last received'));
    await page.screenshot({path:path.join(__dirname,'candle-monitor-desktop.png'),fullPage:true});
    const today=await page.request.get('http://127.0.0.1:8765/api/live-data/candles');
    assert.equal(today.status(),200);
    const invalid=await page.request.get('http://127.0.0.1:8765/api/live-data/candles?symbol=INVALID');
    assert.equal(invalid.status(),400);
    const real=await today.json();
    assert.equal(real.timezone,'Asia/Kolkata');
    let reads=0;
    await page.route('**/api/live-data/candles?**',async route=>{
      reads++;
      const symbol=new URL(route.request().url()).searchParams.get('symbol');
      const fixture={...real,symbol,phase:'MARKET_WINDOW',server_now:'2026-11-02T09:17:30+05:30',scheduler_running:true,verification:{state:'VERIFIED'},evaluation:null,
        candles:[{ts:'2026-11-02T09:15:00+05:30',open:100,high:104,low:98,close:102,completed:1},{ts:'2026-11-02T09:16:00+05:30',open:102,high:103,low:99,close:100,completed:1}],
        forming:{ts:'2026-11-02T09:17:00+05:30',open:100,high:101,low:100,close:101,completed:false},opening_minutes:2,missing_minutes:0,
        summaries:real.symbols.map(s=>({symbol:s,completed_1m:2,completed_5m:0,samples:3,quote:{last_price:101,received_at:'2026-11-02T03:47:00Z'}}))};
      await route.fulfill({json:fixture});
    });
    await page.locator('[data-candle-refresh]').click();
    await page.locator('.candle-chart').waitFor();
    assert.equal(await page.locator('.candle-chart g').count(),3);
    assert.match(await page.locator('.capture-state').innerText(),/Receiving prices/);
    assert.equal(await page.locator('.candle-history tbody tr').count(),3);
    await page.locator('[data-candle-symbol="SBIN"]').click();
    await page.waitForFunction(()=>document.querySelector('.candle-main .eyebrow')?.textContent.includes('SBIN'));
    await page.waitForFunction(()=>document.querySelectorAll('.candle-chart g').length===3);
    const initialReads=reads;
    await page.waitForTimeout(5500);
    assert.ok(reads>initialReads,'Stored data must auto-refresh without manual polling');
    await page.locator('[data-screen="orders"]').first().click();
    assert.match(await page.locator('.content').innerText(),/Paper positions/);
    await page.locator('[data-screen="quotes"]').first().click();
    await page.locator('.candle-chart').waitFor();
    await page.setViewportSize({width:390,height:844});
    await page.screenshot({path:path.join(__dirname,'candle-monitor-mobile.png'),fullPage:true});
    assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth),'Mobile view must fit viewport');
    assert.deepEqual(errors,[]);
    console.log('PASS: live endpoint, invalid symbol, chart OHLC/forming, symbol switching, 5-second refresh, orders navigation, mobile fit, no JS errors');
  } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
