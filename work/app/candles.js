/* Read-only monitor: refreshing this view never triggers market capture or trading. */
(() => {
  let selected = 'RELIANCE', snapshot = null, busy = false, error = '', requested = '';
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const money = value => value == null ? '—' : Number(value).toLocaleString('en-IN', {minimumFractionDigits:2, maximumFractionDigits:2});
  const clock = value => value ? new Intl.DateTimeFormat('en-IN', {timeZone:'Asia/Kolkata',hour:'2-digit',minute:'2-digit',hour12:false}).format(new Date(value)) : '—';
  const visible = () => ['scanner','quotes'].includes(state.screen);
  function feedStatus(data, quote) {
    if (error) return ['fail','API unavailable',error];
    if (!data) return ['review','Connecting','Reading today’s capture status…'];
    if (data.verification?.state !== 'VERIFIED') return ['fail','Token required','Update and verify your Groww token in Connections.'];
    if (!data.scheduler_running) return ['fail','Capture stopped','Backend scheduler is not running.'];
    if (data.phase === 'BEFORE_OPEN') return ['review','Ready for 09:15','Capture is waiting for the 09:15 IST market window.'];
    if (data.phase !== 'MARKET_WINDOW') return ['review','Outside capture window','Showing today’s stored data. Capture window: weekdays 09:15–15:30 IST.'];
    const age = quote ? (new Date(data.server_now)-new Date(quote.received_at))/1000 : Infinity;
    return age >= 0 && age <= 120 ? ['pass','Receiving prices','Backend capture is running. This view checks stored data every 5 seconds.'] : ['fail','Feed delayed','No fresh price received in the last 2 minutes. Check Groww and backend status.'];
  }
  function candleChart(bars) {
    if (!bars.length) return `<div class="candle-empty"><span class="candle-empty-icon">▥</span><h3>Waiting for the first market candle</h3><p>Today’s chart begins when prices are captured from 09:15 IST.<br>The current minute appears as forming; completed minutes are saved in SQLite.</p><span>09:15 open <i>→</i> 09:30 opening range complete</span></div>`;
    const shown = bars.slice(-90), W=1000, H=310, L=20, R=94, T=28, B=35;
    let lo = Math.min(...shown.map(b=>b.low)), hi=Math.max(...shown.map(b=>b.high));
    const pad=Math.max((hi-lo)*.12, hi*.0003, .05); lo-=pad;hi+=pad;
    const y=p=>T+(hi-p)/(hi-lo)*(H-T-B), step=(W-L-R)/Math.max(shown.length,20), width=Math.min(13,step*.58);
    const grid=Array.from({length:5},(_,i)=>{const p=hi-(hi-lo)*i/4;return `<line x1="${L}" x2="${W-R}" y1="${y(p)}" y2="${y(p)}" class="candle-grid"/><text x="${W-R+12}" y="${y(p)+4}">${money(p)}</text>`}).join('');
    const bodies=shown.map((b,i)=>{const x=L+(i+.5)*step, up=b.close>=b.open;return `<g class="${up?'candle-up':'candle-down'} ${b.completed?'':'candle-forming'}"><title>${esc(clock(b.ts))} IST · ${b.completed?'Completed':'Forming'} · O ${money(b.open)} H ${money(b.high)} L ${money(b.low)} C ${money(b.close)}</title><line x1="${x}" x2="${x}" y1="${y(b.high)}" y2="${y(b.low)}"/><rect x="${x-width/2}" y="${Math.min(y(b.open),y(b.close))}" width="${width}" height="${Math.max(2,Math.abs(y(b.open)-y(b.close)))}" rx="1"/></g>`}).join('');
    const labels=shown.map((b,i)=>i%Math.max(1,Math.ceil(shown.length/7))===0?`<text x="${L+(i+.5)*step}" y="${H-10}" text-anchor="middle">${clock(b.ts)}</text>`:'').join('');
    const last=shown.at(-1);
    return `<svg class="candle-chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(selected)} sampled one minute candle chart in India time"><desc>Groww prices sampled every 60 seconds. Hover a candle for its captured OHLC values.</desc>${grid}${bodies}${labels}<line class="candle-price-line" x1="${L}" x2="${W-R}" y1="${y(last.close)}" y2="${y(last.close)}"/><rect class="candle-price-tag" x="${W-R+2}" y="${y(last.close)-11}" width="90" height="22" rx="4"/><text class="candle-price-text" x="${W-R+47}" y="${y(last.close)+4}" text-anchor="middle">${money(last.close)}</text></svg>`;
  }
  function panel() {
    const d=snapshot, rows=d?.summaries||[], current=rows.find(r=>r.symbol===selected), q=current?.quote;
    const [tone,label,description]=feedStatus(d,q), bars=[...(d?.candles||[]),...(d?.forming?[d.forming]:[])], last=bars.at(-1);
    const metrics=[['Completed 1m',current?.completed_1m??0,'Saved candles today'],['Completed 5m',current?.completed_5m??0,'Strategy timeframe'],['Opening range',`${d?.opening_minutes||0} / 15`,'Captured minutes · 09:15–09:30'],['Captured samples',current?.samples??0,`${d?.missing_minutes||0} gaps between saved minutes`]];
    return `<div class="capture-hero"><div><div class="eyebrow">LIVE CAPTURE MONITOR · ${esc(d?.date||'TODAY')} · IST</div><h2>Watch the market take shape</h2><p>One-minute candles from your Groww price capture.</p></div><div class="capture-state ${tone}" role="status"><i></i>${esc(label)}</div></div><div class="capture-status ${tone}" role="status"><span>${esc(description)}</span><span>Last received: <b>${q?esc(formatIndiaTime(q.received_at)):'—'}</b></span></div><div class="capture-stats">${metrics.map(m=>`<div><span>${m[0]}</span><strong>${m[1]}</strong><small>${m[2]}</small></div>`).join('')}</div><div class="capture-layout"><div class="card candle-main"><div class="split"><div><div class="eyebrow">${esc(selected)} · NSE CASH</div><h2>₹${money(q?.last_price)}</h2></div><div class="candle-toolbar"><span class="candle-interval">1m</span><button class="btn compact" data-candle-refresh>↻ Refresh view</button><button class="btn compact" data-action="poll-market">Poll now</button></div></div><div class="candle-ohlc">${['open','high','low','close'].map(k=>`<span>${k[0].toUpperCase()} <b>${money(last?.[k])}</b></span>`).join('')}<span class="status ${d?.forming?'review':''}">${d?.forming?'FORMING':last?'COMPLETED':'WAITING'}</span></div>${candleChart(bars)}<div class="candle-chart-footer"><span><i class="legend-up"></i> Up <i class="legend-down"></i> Down · Hover for OHLC</span><span>India time · latest 90 candles</span></div><p class="candle-quality">ⓘ ${esc(d?.quality_note||'Sampled Groww prices. Exchange OHLCV and volume are not available from this feed.')}</p></div><div class="card capture-watch"><div class="eyebrow">CAPTURE UNIVERSE</div><h3>Follow a symbol</h3><p class="intro">Select to inspect its candles</p>${(rows.length?rows:(d?.symbols||['RELIANCE','SBIN','LT','MARUTI','SUNPHARMA','HEROMOTOCO']).map(symbol=>({symbol}))).map(r=>`<button class="capture-symbol ${r.symbol===selected?'selected':''}" data-candle-symbol="${esc(r.symbol)}"><span><b>${esc(r.symbol)}</b><small>${r.completed_1m||0} × 1m · ${r.completed_5m||0} × 5m saved</small></span><strong>₹${money(r.quote?.last_price)}</strong></button>`).join('')}<div class="capture-watch-note">Backend capture continues when you leave this page. Keep the laptop awake and server running.</div></div></div><div class="card candle-history"><div class="split"><div><h3>Latest captured minutes</h3><p class="intro">${esc(selected)} · ${esc(d?.date||'Today')} · India time</p></div><span class="detail-label">Updates every 5 seconds</span></div><div class="candle-table-wrap"><table class="table"><thead><tr><th>Time (IST)</th><th>Open</th><th>High</th><th>Low</th><th>Close</th><th>Volume</th><th>State</th></tr></thead><tbody>${bars.slice(-8).reverse().map(b=>`<tr><td>${clock(b.ts)}</td>${['open','high','low','close'].map(k=>`<td>${money(b[k])}</td>`).join('')}<td>Unavailable</td><td><span class="status ${b.completed?'pass':'review'}">${b.completed?'SAVED':'FORMING'}</span></td></tr>`).join('')||'<tr><td colspan="7" class="empty">No market-window candles captured today yet.</td></tr>'}</tbody></table></div></div>`;
  }
  function render() {
    const root=document.querySelector('#candle-monitor');
    if (!root) return;
    root.innerHTML=panel()+liveEvaluationPanel();
    root.querySelector('[data-candle-refresh]')?.addEventListener('click',()=>refresh());
    root.querySelector('[data-action="poll-market"]')?.addEventListener('click',async()=>{await pollMarket();await refresh()});
    root.querySelectorAll('[data-candle-symbol]').forEach(button=>button.addEventListener('click',()=>{selected=button.dataset.candleSymbol;snapshot=null;render();refresh()}));
  }
  async function refresh() {
    if (busy) return;
    busy=true;requested=selected;
    try {
      const response=await fetch(`/api/live-data/candles?symbol=${encodeURIComponent(requested)}`,{cache:'no-store'});
      const data=await response.json();
      if (!response.ok) throw new Error(data.error||`API returned ${response.status}`);
      if (requested===selected) {snapshot=data;liveData.liveEvaluation=data.evaluation;error='';}
    } catch(e) {error=`Unable to refresh candle data: ${e.message}`;}
    finally {busy=false;if(visible())render();if(requested!==selected)refresh();}
  }
  const priorScreen=screen;
  screen=function(s){return ['scanner','quotes'].includes(s)?'<div id="candle-monitor"></div>':priorScreen(s)};
  const priorApp=app;
  app=function(){priorApp();if(visible()){render();if(!snapshot&&!busy)refresh();}};
  setInterval(()=>{if(visible()&&!document.hidden)refresh()},5000);
  document.addEventListener('visibilitychange',()=>{if(!document.hidden&&visible())refresh()});
  app();
})();
