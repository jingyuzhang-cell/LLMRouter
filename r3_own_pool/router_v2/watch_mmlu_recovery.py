"""Read-only live view merging original, repair and resume journals by repeat key."""
import argparse,json,time,html
from pathlib import Path
from collections import Counter
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from .watch_utility_panel import read_records,load_json_safe
ROOT=Path(__file__).resolve().parents[1]
D=ROOT/'data/mmlu_utility_repeats_400';R=ROOT/'data/mmlu_utility_repair_20260911';S=ROOT/'data/mmlu_utility_resume_20260911b';P=ROOT/'router_v2/mmlu_utility_panel_400'
def snapshot():
 now=time.time();panel={r['query_id'] for r in read_records(P/'PANEL.jsonl')};slots={};allkeys={}
 for slot in ('large','reasoning'):
  sources=[D/(slot+'.jsonl')]+([R/'reasoning.jsonl',S/'reasoning.jsonl'] if slot=='reasoning' else [])
  records=[r for p in sources for r in read_records(p) if r.get('query_id') in panel and r.get('repeat_index') in range(5)]
  valid={};fail=set()
  for r in records:
   key=(r['query_id'],r['repeat_index'])
   if r.get('status') in ('ok','truncated','parse_failed') and not r.get('error') and r.get('quality') in (0,1) and all(r.get('cost',{}).get(k) is not None for k in ('tokens_input','tokens_output')) and r.get('latency',{}).get('total_ms') is not None:valid.setdefault(key,r)
   elif r.get('status')=='failed' or r.get('error'):fail.add(key)
  per=Counter(q for q,k in valid);latest=max((r.get('ts',0) for r in records),default=0);allkeys[slot]=set(valid)
  slots[slot]=dict(valid=len(valid),target=len(panel)*5,complete_queries=sum(n==5 for n in per.values()),unrepaired_failed_keys=len(fail-set(valid)),historical_failed_rows=sum(r.get('status')=='failed' or bool(r.get('error')) for r in records),new_valid_last_15_min=sum(0<=now-r.get('ts',0)<=900 for r in valid.values()),seconds_since_last_record=round(now-latest) if latest else None)
 stages={'Original':load_json_safe(D/'reasoning_STATUS.json',{}),'Repair':load_json_safe(R/'STATUS.json',{}),'Resume':load_json_safe(S/'STATUS.json',{})}
 return dict(updated_utc=time.strftime('%Y-%m-%d %H:%M:%S UTC',time.gmtime(now)),slots=slots,complete_pairs=sum(all((q,k) in allkeys[s] for s in allkeys for k in range(5)) for q in panel),stages=stages,note='Counts are unique query/repeat pairs with quality, tokens and latency. Stage files are not process-health proof; check last-record age. No quality-performance metrics on partial data.')
def render(s):
 lines=['MMLU 400 | '+s['updated_utc'],'Model      Valid      Complete queries  Unrepaired failures  New valid / 15min  Last record age']
 for model,v in s['slots'].items():lines.append(f"{model:10} {v['valid']:4}/2000  {v['complete_queries']:4}/400          {v['unrepaired_failed_keys']:4}                {v['new_valid_last_15_min']:4}              {v['seconds_since_last_record']}s")
 lines+=['Complete pairs: '+str(s['complete_pairs'])+'/400','']
 for name,v in s['stages'].items():lines.append(f"{name}: {v.get('phase','UNKNOWN')} | query: {v.get('query_id','-')}")
 lines+=['',s['note']];return '\n'.join(lines)
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--interval',type=int,default=0);ap.add_argument('--http',type=int,default=0);a=ap.parse_args()
 if a.http:
  class Handler(BaseHTTPRequestHandler):
   def do_GET(self):
    s=snapshot()
    if self.path=='/api/status':body=json.dumps(s).encode();kind='application/json'
    else:body=('<!doctype html><meta charset="utf-8"><meta http-equiv="refresh" content="10"><title>MMLU实时采集</title><style>body{background:#101827;color:#e5edf5;font:16px monospace;padding:28px}pre{line-height:1.9;white-space:pre-wrap}a{color:#7dd3fc}</style><h1>MMLU 400 实时进度</h1><p>每10秒刷新 · 原采集、修复、续采合并去重</p><pre>'+html.escape(render(s))+'</pre><a href="/api/status">JSON 数据</a>').encode();kind='text/html; charset=utf-8'
    self.send_response(200);self.send_header('Content-Type',kind);self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
   def log_message(self,*args):pass
  ThreadingHTTPServer(('127.0.0.1',a.http),Handler).serve_forever()
 else:
  while True:
   print(('\033[2J\033[H' if a.interval else '')+render(snapshot()),flush=True)
   if not a.interval:break
   time.sleep(max(1,a.interval))
if __name__=='__main__':main()
