import csv, json, os
from collections import defaultdict
from datetime import datetime

ROOT = os.path.dirname(__file__)

def load(path):
    rows=[]
    with open(path, newline='', encoding='utf-8') as f:
        for r in csv.DictReader(f):
            ts=r.get('Timestamp') or (r.get('Date')+'T'+r.get('Time'))
            dt=datetime.fromisoformat(ts)
            if dt.hour < 9 or (dt.hour == 9 and dt.minute < 15) or dt.hour > 15 or (dt.hour==15 and dt.minute > 29):
                continue
            rows.append((dt, float(r['Open']), float(r['High']), float(r['Low']), float(r['Close'])))
    return rows

def bars5(rows):
    groups={}
    for dt,o,h,l,c in rows:
        # session-aligned five-minute bucket beginning 09:15
        mins=(dt.hour*60+dt.minute)-(9*60+15)
        key=(dt.date(), mins//5)
        if key not in groups: groups[key]=[dt,o,h,l,c]
        else:
            g=groups[key]; g[2]=max(g[2],h); g[3]=min(g[3],l); g[4]=c
    return [tuple(v) for _,v in sorted(groups.items())]

def test(rows, target=50, stop=30):
    b=bars5(rows); days=defaultdict(list)
    for x in b: days[x[0].date()].append(x)
    dates=sorted(days)[-30:]
    trades=[]
    for i, d in enumerate(dates[1:]):
        prev=days[dates[i]]
        ph=max(x[2] for x in prev); pl=min(x[3] for x in prev)
        day=days[d]; trade=None
        for j in range(len(day)-1):
            dt,o,h,l,c=day[j]
            side='LONG' if c>ph else ('SHORT' if c<pl else None)
            if not side: continue
            en=day[j+1][1]
            tp=en+target if side=='LONG' else en-target
            sl=en-stop if side=='LONG' else en+stop
            exit_px=day[-1][4]; result='TIME'; exit_dt=day[-1][0]
            for k in range(j+1,len(day)):
                xdt,xo,xh,xl,xc=day[k]
                hit_tp=(xh>=tp) if side=='LONG' else (xl<=tp)
                hit_sl=(xl<=sl) if side=='LONG' else (xh>=sl)
                if hit_sl: exit_px=sl; result='SL'; exit_dt=xdt; break
                if hit_tp: exit_px=tp; result='TP'; exit_dt=xdt; break
            pts=(exit_px-en) if side=='LONG' else (en-exit_px)
            trade={'date':str(d),'side':side,'prev_high':round(ph,2),'prev_low':round(pl,2),'entry':round(en,2),'exit':round(exit_px,2),'points':round(pts,2),'result':result,'entry_time':str(day[j+1][0].time()),'exit_time':str(exit_dt.time())}
            trades.append(trade); break
    wins=sum(t['points']>0 for t in trades); losses=sum(t['points']<0 for t in trades)
    return {'sessions':len(dates),'trades':len(trades),'wins':wins,'losses':losses,'win_rate_pct':round(100*wins/len(trades),1) if trades else 0,'net_points':round(sum(t['points'] for t in trades),2),'avg_points':round(sum(t['points'] for t in trades)/len(trades),2) if trades else 0,'trades_detail':trades}

for name, files, stop in [
    ('NIFTY50',['NIFTY50_1min_2026-09.csv','NIFTY50_1min_2026-10.csv'],30),
    ('SENSEX',['SENSEX_1min_2026-09.csv','SENSEX_1min_2026-10.csv'],40)]:
    rows=[]
    for f in files: rows += load(os.path.join(ROOT,f))
    out=test(rows,50,stop)
    with open(os.path.join(ROOT,name+'_backtest.json'),'w') as f: json.dump(out,f,indent=2)
    print(name, json.dumps({k:v for k,v in out.items() if k!='trades_detail'}))
