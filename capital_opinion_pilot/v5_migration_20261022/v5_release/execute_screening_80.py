"""Execution script for the 80-call screening matrix (68 new calls upon authorization).
Runs 4 node types × samples × 4 models through the unified metered path.
Fact extraction 12 calls are REUSED from pilot (no new calls).
Zero-pay dry-run mode: --dry-run (FakeMeter, no HTTP)."""
import json, os, sys, time, hashlib, argparse
import urllib.request
sys.path.insert(0, str(__import__('pathlib').Path(__file__).parent))
from pathlib import Path
from pilot_common import PILOT_DIR, fenced_json, norm

P = PILOT_DIR

def load_frozen():
    return json.loads((P/'screening_full_80_frozen.json').read_text())

def load_env():
    for line in open('/root/.env.modelpool'):
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            k, v = line.split('=', 1)
            os.environ[k] = v.strip()

class ScreeningRunner:
    def __init__(self, dry_run=False):
        self.dry_run = dry_run
        self.frozen = load_frozen()
        self.models = {m['alias']: m for m in self.frozen['models']}
        self.responses = []
        self.ledger = []
        self.calls = 0
        self.tokens_in = 0
        self.tokens_out = 0
        self.cash = 0.0
        self.resp_file = P / 'screening_full80_responses.jsonl'
        self.ledger_file = P / 'screening_full80_ledger.jsonl'

    def check_caps(self, max_calls=72, max_tokens=100000, max_cash=0.25):
        assert self.calls <= max_calls, f'CALL CAP {self.calls}'
        assert self.tokens_in + self.tokens_out <= max_tokens, f'TOKEN CAP'
        assert self.cash <= max_cash, f'CASH CAP {self.cash}'

    def call_model(self, alias, system, user, output_cap=2048):
        m = self.models[alias]
        if self.dry_run:
            return {'text': '{"timeline":[{"date":"2026-01-01","event":"test","doc_id":"D1"}]}',
                    'in': 400, 'out': 300, 'stop': 'stop', 'lat': 1.0,
                    'model': m['model_id']}
        if m['endpoint'] == 'subscription':
            from pilot_common import Meter
            met = Meter.__new__(Meter)
            met.calls = []; met.max_calls = 72; met.max_guaranteed_actual = 100000
            met.ledger = P/'screening_full80_glm_ledger.jsonl'
            met.responses_path = P/'screening_full80_glm_responses.jsonl'
            rec, txt = met.call(alias, system, user, max_tokens=output_cap,
                                purpose=f's80:{self.calls+1}:{alias}', timeout_s=120)
            return {'text': txt, 'in': rec['usage']['input_tokens'],
                    'out': rec['usage']['output_tokens'],
                    'stop': rec['stop_reason'], 'lat': rec['latency_s'],
                    'model': rec['model']}
        # OpenAI-compatible endpoints
        body = {'model': m['model_id'], 'max_tokens': output_cap,
                'messages': [{'role': 'system', 'content': system},
                             {'role': 'user', 'content': user}],
                'response_format': {'type': 'json_object'}}
        if m.get('thinking') == 'disabled':
            body['thinking'] = {'type': 'disabled'}
        key = os.environ.get('DEEPSEEK_API_KEY' if 'deepseek' in m['model_id'] else 'DASHSCOPE_API_KEY', '')
        base = 'https://api.deepseek.com' if 'deepseek' in m['model_id'] \
               else 'https://dashscope.aliyuncs.com/compatible-mode/v1'
        req = urllib.request.Request(base + '/chat/completions',
                                     data=json.dumps(body).encode(), method='POST')
        req.add_header('Content-Type', 'application/json')
        req.add_header('Authorization', 'Bearer ' + key)
        t0 = time.time()
        with urllib.request.urlopen(req, timeout=120) as r:
            d = json.loads(r.read().decode())
        lat = round(time.time() - t0, 2)
        content = d['choices'][0]['message'].get('content', '')
        if isinstance(content, list):
            content = ''.join(c.get('text', '') for c in content if isinstance(c, dict))
        u = d['usage']
        return {'text': content, 'in': u['prompt_tokens'], 'out': u['completion_tokens'],
                'stop': d['choices'][0].get('finish_reason', ''), 'lat': lat,
                'model': d.get('model', m['model_id'])}

    def evaluate(self, text, node_type, input_text):
        """Type-specific evaluation."""
        try:
            obj = fenced_json(text)
            if not isinstance(obj, dict):
                return {'json_valid': False, 'count': 0, 'details': []}
            if node_type == 'fact_extraction':
                items = obj.get('facts', [])
                flat_input = norm(input_text)
                supported = sum(1 for f in items if norm(f.get('quote', '')) in flat_input and f.get('quote'))
                return {'json_valid': True, 'count': len(items),
                        'supported': supported, 'details': items}
            elif node_type == 'timeline':
                items = obj.get('timeline', [])
                dates = [t.get('date', '') for t in items]
                violations = sum(1 for a, b in zip(dates, dates[1:]) if a > b)
                return {'json_valid': True, 'count': len(items),
                        'order_violations': violations, 'details': items}
            elif node_type == 'entity_relations':
                items = obj.get('relations', [])
                return {'json_valid': True, 'count': len(items), 'details': items}
            elif node_type == 'crosssource_check':
                items = obj.get('verdicts', [])
                from collections import Counter
                vc = Counter(v.get('verdict', 'unknown') for v in items)
                return {'json_valid': True, 'count': len(items),
                        'verdict_distribution': dict(vc), 'details': items}
            return {'json_valid': True, 'count': 0, 'details': []}
        except Exception:
            return {'json_valid': False, 'count': 0, 'details': []}

    def record(self, node_type, sample_id, alias, raw, eval_result, input_hash):
        m = self.models[alias]
        self.calls += 1
        self.tokens_in += raw['in']
        self.tokens_out += raw['out']
        if 'deepseek' in m['model_id']:
            cash = (raw['in'] * 0.30 + raw['out'] * 1.20) / 1e6 * 7.1
        elif 'qwen' in m['model_id']:
            cash = (raw['in'] * 0.8 + raw['out'] * 2) / 1e6
        else:
            cash = 0.0
        self.cash += cash
        self.check_caps()
        rec = {
            'call_id': self.calls, 'node_type': node_type, 'sample_id': sample_id,
            'model_alias': alias, 'model_id': m['model_id'], 'family': m['family'],
            'input_hash': input_hash, 'prompt_tokens': raw['in'],
            'completion_tokens': raw['out'], 'stop_reason': raw['stop'],
            'truncated': raw['stop'] in ('length', 'max_tokens'),
            'json_valid': eval_result['json_valid'], 'count': eval_result['count'],
            'latency_s': raw['lat'], 'cost_cash': round(cash, 6),
            'timestamp': time.strftime('%Y-%m-%dT%H:%M:%S')
        }
        # Add type-specific metrics
        for k in ('supported', 'order_violations', 'verdict_distribution'):
            if k in eval_result:
                rec[k] = eval_result[k]
        self.ledger.append(rec)
        self.responses.append({'call_id': self.calls, 'raw_response': raw['text'],
                               'parsed': eval_result.get('details', [])})
        if not self.dry_run:
            with open(self.ledger_file, 'a') as f:
                f.write(json.dumps(rec, ensure_ascii=False) + '\n')
            with open(self.resp_file, 'a') as f:
                f.write(json.dumps({'call_id': self.calls, 'raw_response': raw['text'],
                                    'parsed': eval_result.get('details', [])},
                                   ensure_ascii=False) + '\n')
        return rec

    def run(self):
        """Execute all node types (skip fact_extraction which is reused from pilot)."""
        if not self.dry_run:
            load_env()
        print(f"Mode: {'DRY-RUN (FakeMeter)' if self.dry_run else 'REAL EXECUTION'}")
        print(f"Models: {list(self.models.keys())}")
        for nt_name, nt in self.frozen['node_types'].items():
            if nt.get('pilot_completed', 0) > 0:
                print(f"\n=== {nt_name}: SKIPPED (reuse {nt['pilot_completed']} pilot calls) ===")
                continue
            print(f"\n=== {nt_name}: {len(nt['samples'])} samples × {len(self.models)} models ===")
            system = nt['system_prompt']
            for sample in nt['samples']:
                user = f"输入数据：\n{sample['input']}\n\n只输出JSON。"
                input_hash = hashlib.sha256((system + '\x00' + user).encode()).hexdigest()[:16]
                for alias in self.models:
                    try:
                        raw = self.call_model(alias, system, user)
                        ev = self.evaluate(raw['text'], nt_name, sample['input'])
                        rec = self.record(nt_name, sample['sample_id'], alias, raw, ev, input_hash)
                        print(f"  [{self.calls:2d}] {sample['sample_id']}/{alias:12s} "
                              f"in={raw['in']:4d} out={raw['out']:4d} "
                              f"json={'Y' if ev['json_valid'] else 'N'} "
                              f"count={ev['count']:3d} lat={raw['lat']:5.1f}s")
                    except Exception as e:
                        print(f"  [{self.calls+1}] {sample['sample_id']}/{alias} "
                              f"FAILED: {type(e).__name__}: {str(e)[:80]}")
                        self.calls += 1
                        self.check_caps()
        print(f"\n{'='*60}")
        print(f"TOTAL: {self.calls} calls, {self.tokens_in}+{self.tokens_out}="
              f"{self.tokens_in+self.tokens_out} tokens, ¥{self.cash:.4f}")
        if self.dry_run:
            print("(DRY-RUN — no real API calls made)")
        # Summary
        from collections import defaultdict
        by_nt = defaultdict(lambda: defaultdict(list))
        for r in self.ledger:
            by_nt[r['node_type']][r['model_alias']].append(r)
        print(f"\n{'NodeType':>18s} {'Model':>12s} {'JSON':>5s} {'AvgCount':>8s} {'AvgLat':>7s}")
        for nt in by_nt:
            for alias in by_nt[nt]:
                rs = by_nt[nt][alias]
                jr = sum(1 for r in rs if r['json_valid']) / len(rs)
                ac = sum(r['count'] for r in rs) / len(rs)
                al = sum(r['latency_s'] for r in rs) / len(rs)
                print(f"{nt:>18s} {alias:>12s} {jr:>5.0%} {ac:>8.1f} {al:>6.1f}s")


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    runner = ScreeningRunner(dry_run=args.dry_run)
    runner.run()
