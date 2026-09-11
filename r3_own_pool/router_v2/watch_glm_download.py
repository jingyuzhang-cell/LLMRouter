"""Read-only download progress; byte growth is local file growth, not network throughput."""
import argparse,json,time,threading
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import html
MODEL=Path('/root/autodl-tmp/models/glm-4-9b-chat-hf');TOTAL=18799953696
samples=[];lock=threading.Lock()
def snapshot():
 now=time.time();files=[p for p in MODEL.rglob('*') if p.is_file() and (p.name.endswith('.safetensors') or p.name.endswith('.incomplete'))];sizes=[]
 for p in files:
  try:sizes.append((p,p.stat()))
  except FileNotFoundError:pass
 size=sum(s.st_size for p,s in sizes)
 with lock:
  samples.append((now,size))
  while len(samples)>1 and now-samples[0][0]>60:samples.pop(0)
  dt=now-samples[0][0];rate=max(0,(size-samples[0][1])/dt) if dt>=1 else None
 state=Path('/root/r3_own_pool/data/pool4_glm_pilot_120/STATUS.json')
 try:phase=json.loads(state.read_text()).get('phase','unknown')
 except Exception:phase='unknown'
 return dict(time=time.strftime('%H:%M:%S'),phase=phase,local_bytes=size,total_weight_bytes=TOTAL,approx_percent=min(100,100*size/TOTAL),growth_MiB_s=rate/1024**2 if rate is not None else None,completed_shards=sum(p.name.endswith('.safetensors') for p,s in sizes),files=[dict(name=p.name,GiB=round(s.st_size/1024**3,3),seconds_since_write=round(now-s.st_mtime)) for p,s in sizes])
def render(s):
 speed='sampling...' if s['growth_MiB_s'] is None else f"{s['growth_MiB_s']:.2f} MiB/s"
 return f"GLM download | {s['time']} | {s['phase']}\nLocal bytes: {s['local_bytes']/1024**3:.2f} / {TOTAL/1024**3:.2f} GiB (~{s['approx_percent']:.1f}%)\nRecent local growth: {speed}\nCompleted weight shards: {s['completed_shards']}\n\n"+'\n'.join(f"{r['GiB']:.3f} GiB | last write {r['seconds_since_write']}s ago | {r['name']}" for r in s['files'])+'\n\nApproximate local file progress; incomplete/preallocated files are not verified downloads. Zero growth may indicate buffering or a stall.'
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--http',type=int,default=0);ap.add_argument('--interval',type=int,default=5);ap.add_argument('--once',action='store_true');a=ap.parse_args()
 if a.http:
  class Handler(BaseHTTPRequestHandler):
   def do_GET(self):
    s=snapshot();body=(json.dumps(s) if self.path=='/api/status' else '<meta charset="utf-8"><meta http-equiv="refresh" content="5"><title>GLM下载进度</title><h2>GLM下载进度 · 每5秒刷新</h2><pre>'+html.escape(render(s))+'</pre>').encode();self.send_response(200);self.send_header('Content-Type','application/json' if self.path=='/api/status' else 'text/html; charset=utf-8');self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(body)
   def log_message(self,*args):pass
  ThreadingHTTPServer(('127.0.0.1',8901 if a.http==1 else a.http),Handler).serve_forever()
 else:
  while True:
   print(('' if a.once else '\033[2J\033[H')+render(snapshot()),flush=True)
   if a.once:return
   time.sleep(max(1,a.interval))
if __name__=='__main__':main()
