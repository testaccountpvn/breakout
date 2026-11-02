import csv, os, json
from collections import defaultdict
from datetime import datetime

ROOT=os.path.dirname(__file__)

def load(path):
    out=[]
    with open(path,encoding='utf-8',newline='') as f:
        for r in csv.DictReader(f):
            dt=datetime.fromisoformat(r['Timestamp'])
            if not (dt.hour>9 or (dt.hour==9 and dt.minute>=15)) or dt.hour>15 or (dt.hour==15 and dt.minute>29): continue
            out.append((dt,float(r['Open']),float(r['High']),float(r['Low']),float(r['Close']),float(r.get('Volume') or 0)))
    return out

def bars5(rows):
    g={}
    for dt,o,h,l,c,v in rows:
        m=(dt.hour*60+dt.minute)-(9*60+15); k=(dt.date(),m//5)
        if k not in g:g[k]=[dt,o,h,l,c,v]
        else:
            x=g[k];x[2]=max(x[2],h);x[3]=min(x[3],l);x[4]=c;x[5]+=v
    return [tuple(x) for _,x in sorted(g.items())]

def ema(vals,n):
    a=2/(n+1); out=[]; e=None
    for v in vals:e=v if e is None else a*v+(1-a)*e;out.append(e)
    return out

def run(rows, orb=15, target=50, stop=30, trend=True, vwap=True):
    b=bars5(rows); days=defaultdict(list)
    for x in b:days[x[0].date()].append(x)
    dates=sorted(days); trades=[]
    for d in dates:
        day=days[d]; n=orb//5
        if len(day)<=n+2:continue
        oh=max(x[2] for x in day[:n]);ol=min(x[3] for x in day[:n])
        closes=[x[4] for x in day]; es=ema(closes,20)
        cumv=cump=0; sig=None
        for j,x in enumerate(day):
            dt,o,h,l,c,v=x;cumv+=v;cump+=c*v;vw=cump/cumv if cumv else c
            if j<n or j>=len(day)-1:continue
            long=c>oh and (not trend or c>es[j]) and (not vwap or c>vw)
            short=c<ol and (not trend or c<es[j]) and (not vwap or c<vw)
            if long or short:sig=('L' if long else 'S',j);break
        if not sig:continue
        side,j=sig;en=day[j+1][1];tp=en+target if side=='L' else en-target;sl=en-stop if side=='L' else en+stop
        ex=day[-1][4];res='TIME';
        for k in range(j+1,len(day)):
            _,_,hh,ll,_c,_v=day[k]
            hit_sl=ll<=sl if side=='L' else hh>=sl;hit_tp=hh>=tp if side=='L' else ll<=tp
            if hit_sl:ex=sl;res='SL';break
            if hit_tp:ex=tp;res='TP';break
        pts=(ex-en) if side=='L' else (en-ex);trades.append(pts)
    wins=sum(x>0 for x in trades); return {'trades':len(trades),'wins':wins,'losses':sum(x<=0 for x in trades),'win_rate':round(100*wins/len(trades),1) if trades else 0,'net':round(sum(trades),2),'avg':round(sum(trades)/len(trades),2) if trades else 0}

datasets={
 'NIFTY50':[load(os.path.join(ROOT,'NIFTY50_1min_2026-09.csv')),load(os.path.join(ROOT,'NIFTY50_1min_2026-10.csv'))],
 'SENSEX':[load(os.path.join(ROOT,'SENSEX_1min_2026-09.csv')),load(os.path.join(ROOT,'SENSEX_1min_2026-10.csv'))]}
results={}
for name,parts in datasets.items():
    rows=sum(parts,[]); allbars=bars5(rows); dates=sorted({x[0].date() for x in allbars})[-30:]
    rows=[x for x in rows if x[0].date() in dates]
    days=sorted(dates); train=set(days[:20]);test=set(days[20:])
    candidates=[]
    for orb in (15,30):
      for stop in (20,25,30,35,40):
       for trend in (False,True):
        for vw in (False,True):
         cfg={'orb':orb,'target':50,'stop':stop,'trend':trend,'vwap':vw}
         tr=run([x for x in rows if x[0].date() in train],**cfg);te=run([x for x in rows if x[0].date() in test],**cfg)
         candidates.append({'cfg':cfg,'train':tr,'test':te})
    candidates.sort(key=lambda x:(x['train']['win_rate'],x['train']['net']),reverse=True)
    results[name]={'development_best':candidates[:5],'holdout_of_best':candidates[0]}
with open(os.path.join(ROOT,'strategy_compare.json'),'w') as f:json.dump(results,f,indent=2)
for n,r in results.items():
 print('\n'+n)
 for x in r['development_best'][:5]:print(x)
