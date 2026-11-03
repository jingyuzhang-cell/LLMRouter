"""Shared utilities for the capital-opinion pilot: metered GLM calls with hard budget stops.

Reuses the bigmodel coding-plan Anthropic-compatible endpoint. The API key is read
from the host provider config at runtime and never written to pilot outputs.
"""
import hashlib
import json
import re
import time
import urllib.request
import urllib.error
from pathlib import Path

PILOT_DIR = Path('/root/capital_opinion_pilot/v5_final_acceptance_20261022_v1/isolated')
LEDGER = PILOT_DIR / 'model_call_ledger.jsonl'

# Hard pilot envelope (per task spec): <=20 calls, cumulative actual+reserved tokens <=30,000.
# Reservation accounting: a call's reservation is outstanding only while in flight; on completion
# it settles to actual usage. Enforced: calls<=20; guaranteed-settled actual<=29,000
# (actual_before + max_tokens of the new call must stay under the cap); peak outstanding is
# bounded by the single in-flight max_tokens because calls are serial. The most conservative
# cumulative metric actual+sum(max_tokens over ALL calls) is tracked and disclosed, not enforced.
MAX_CALLS = 20
MAX_GUARANTEED_ACTUAL = 29000

ENDPOINT = 'https://open.bigmodel.cn/api/anthropic/v1/messages'
MODELS = {
    'glm53': 'GLM-5.3',
    'glm53flash': 'GLM-5.3-Flash',
}


def _api_key():
    cfg = json.load(open('/root/.zcode/v2/provider_config.json'))
    return next(r['config']['access']['apiKey']
                for r in cfg['config']['providerConfigRules']['providerRules']
                if r['providerId'] == 'bigmodel-api')


class BudgetExceeded(RuntimeError):
    pass


class Meter:
    """Metered model access with per-call persistence and hard budget stops.

    v2 changes (PILOT V2 fix list #2/#7):
    - ledger path is configurable (round-2 uses model_call_ledger_v2.jsonl; the round-1
      ledger stays frozen and read-only);
    - every call persists its raw response immediately (model_responses file), so a crash
      can never lose paid-for outputs again;
    - budget accounting tracks BOTH: settled actual tokens, and the conservative
      cumulative actual+sum(max_tokens); the enforced stop is
      actual_before + in_flight_max_tokens <= max_guaranteed_actual;
    - transport is injectable for zero-call dry-run tests.
    """

    def __init__(self, ledger_path=None, max_calls=20, max_guaranteed_actual=29000):
        self.ledger = Path(ledger_path or (PILOT_DIR / 'model_call_ledger_v2.jsonl'))
        self.responses_path = self.ledger.with_name(self.ledger.stem + '_responses.jsonl')
        self.max_calls = max_calls
        self.max_guaranteed_actual = max_guaranteed_actual
        self.calls = []
        if self.ledger.exists():
            for line in self.ledger.read_text().splitlines():
                if line.strip():
                    self.calls.append(json.loads(line))

    def _transport(self, alias, system, user, max_tokens, timeout_s):
        """Real HTTP transport. Overridden by FakeMeter in dry-run tests."""
        body = {'model': MODELS[alias], 'max_tokens': max_tokens,
                'thinking': {'type': 'disabled'},
                'system': system, 'messages': [{'role': 'user', 'content': user}]}
        req = urllib.request.Request(ENDPOINT, data=json.dumps(body).encode(), method='POST')
        key = _api_key()
        req.add_header('content-type', 'application/json')
        req.add_header('x-api-key', key)
        req.add_header('authorization', 'Bearer ' + key)
        req.add_header('anthropic-version', '2023-06-01')
        t0 = time.monotonic()
        with urllib.request.urlopen(req, timeout=timeout_s) as r:
            d = json.loads(r.read().decode())
        text = ''.join(b.get('text', '') for b in d.get('content', []) if b.get('type') == 'text')
        return {'usage': {'input_tokens': d['usage']['input_tokens'],
                          'output_tokens': d['usage']['output_tokens']},
                'text': text, 'latency_s': time.monotonic() - t0,
                'stop_reason': d.get('stop_reason')}

    @property
    def n_calls(self):
        return len(self.calls)

    @property
    def actual_tokens(self):
        return sum(c['usage']['input_tokens'] + c['usage']['output_tokens'] for c in self.calls)

    @property
    def conservative_tokens(self):
        return self.actual_tokens + sum(c['max_tokens'] for c in self.calls)

    def summary(self):
        per = {}
        for c in self.calls:
            s = per.setdefault(c['model_alias'], {'calls': 0, 'in': 0, 'out': 0, 'lat_s': 0.0})
            s['calls'] += 1
            s['in'] += c['usage']['input_tokens']
            s['out'] += c['usage']['output_tokens']
            s['lat_s'] += c['latency_s']
        return {'n_calls': self.n_calls, 'settled_actual_tokens': self.actual_tokens,
                'conservative_actual_plus_sum_max': self.conservative_tokens,
                'caps': {'calls': self.max_calls, 'guaranteed_settle': self.max_guaranteed_actual},
                'per_model': per}

    def call(self, alias, system, user, max_tokens=512, purpose='unspecified', timeout_s=60):
        """Metered call with crash-safe dedup and conservative reservation.

        V2.2 fixes (from the V2.1 overage post-mortem):
        - DEDUP: an existing ledger entry with the same (purpose, prompt_sha256) is returned
          as-is regardless of parse outcome — a crash-rerun can never silently re-pay the
          same attempt. Deliberate repeats must use a distinct purpose string.
        - CONSERVATIVE RESERVATION: reject unless actual + 1.5 x max_tokens <= cap, so a
          thinking model that settles above its nominal cap cannot breach the guarantee.
        """
        prompt_sha = hashlib.sha256((system + '\x00' + user).encode()).hexdigest()
        for c in self.calls:
            if c['purpose'] == purpose and c['prompt_sha256'] == prompt_sha:
                resp = self._load_response(c['call_id'])
                return c, (resp if resp is not None else '')
        if self.n_calls >= self.max_calls:
            raise BudgetExceeded(f'call cap reached ({self.max_calls})')
        # V3-repair lesson: reserve must cover the PROMPT too — repair prompts embed
        # prior plans and grew inputs ~2x, breaching a output-only reserve.
        # Conservative bound: ~0.9 tokens per prompt char + 1.5x output cap.
        input_reserve = int((len(system) + len(user)) * 0.9)
        reserve = input_reserve + int(max_tokens * 1.5)
        if self.actual_tokens + reserve > self.max_guaranteed_actual:
            raise BudgetExceeded(f'conservative token cap: actual={self.actual_tokens} + reserve={reserve} '
                                 f'(input~{input_reserve} + 1.5x{max_tokens}) > cap {self.max_guaranteed_actual}')
        r = self._transport(alias, system, user, max_tokens, timeout_s)
        rec = {'call_id': len(self.calls) + 1, 'ts': time.strftime('%Y-%m-%dT%H:%M:%S'),
               'model_alias': alias, 'model': MODELS[alias], 'purpose': purpose,
               'max_tokens': max_tokens, 'prompt_sha256': prompt_sha,
               'prompt_chars': len(system) + len(user), 'response_chars': len(r['text']),
               'usage': r['usage'], 'latency_s': round(r['latency_s'], 3),
               'stop_reason': r['stop_reason'],
               'cumulative_settled_actual': self.actual_tokens + r['usage']['input_tokens'] + r['usage']['output_tokens'],
               'cumulative_conservative': None}
        rec['cumulative_conservative'] = (rec['cumulative_settled_actual']
                                          + sum(c['max_tokens'] for c in self.calls) + max_tokens)
        self.calls.append(rec)
        with open(self.ledger, 'a') as f:
            f.write(json.dumps(rec, ensure_ascii=False) + '\n')
        with open(self.responses_path, 'a') as f:
            f.write(json.dumps({'call_id': rec['call_id'], 'purpose': purpose, 'model': MODELS[alias],
                                'usage': r['usage'], 'latency_s': rec['latency_s'],
                                'stop_reason': r['stop_reason'], 'text': r['text']},
                               ensure_ascii=False) + '\n')
        return rec, r['text']

    def _load_response(self, call_id):
        if not self.responses_path.exists():
            return None
        for line in self.responses_path.read_text().splitlines():
            if line.strip():
                d = json.loads(line)
                if d.get('call_id') == call_id:
                    return d.get('text')
        return None


def fenced_json(text):
    """Parse a fenced or bare JSON object/array from a model response."""
    t = text.strip()
    m = re.search(r'```(?:json)?\s*(.+?)```', t, re.S)
    if m:
        t = m.group(1).strip()
    start = min([i for i in (t.find('['), t.find('{')) if i >= 0], default=-1)
    if start > 0:
        t = t[start:]
    return json.loads(t)


# ---- text normalisation helpers shared by facts building and scoring ----

_CN_NUM = {'零': 0, '〇': 0, '一': 1, '二': 2, '三': 3, '四': 4, '五': 5,
           '六': 6, '七': 7, '八': 8, '九': 9}


def cn_year(s):
    return int(''.join(str(_CN_NUM[c]) for c in s))


def cn_num(s):
    """Chinese numeral below 100, e.g. 六->6, 二十八->28, 十二->12, 二十->20."""
    if s.isdigit():
        return int(s)
    if s == '十':
        return 10
    if '十' in s:
        a, _, b = s.partition('十')
        return (cn_num(a) if a else 1) * 10 + (cn_num(b) if b else 0)
    return _CN_NUM[s]


def chinese_date_to_iso(text):
    """Find '二〇二四年六月二十八日' style dates and return ISO strings."""
    out = []
    for m in re.finditer(r'([〇零一二三四五六七八九]{4})年([一二三四五六七八九十]{1,3})月([一二三四五六七八九十]{1,3})日', text):
        try:
            out.append(f'{cn_year(m.group(1)):04d}-{cn_num(m.group(2)):02d}-{cn_num(m.group(3)):02d}')
        except Exception:
            pass
    return out


def all_dates(text):
    """All explicit dates (ISO or 2024年7月6日 style) as ISO strings, order preserved."""
    dates = re.findall(r'(20\d{2})[-/年.](\d{1,2})[-/月.](\d{1,2})日?', text)
    iso = [f'{int(a):04d}-{int(b):02d}-{int(c):02d}' for a, b, c in dates]
    seen, uniq = set(), []
    for d in iso + chinese_date_to_iso(text):
        if d not in seen:
            seen.add(d)
            uniq.append(d)
    return uniq


def norm(s):
    """Normalise Chinese text for quote matching: collapse whitespace/punctuation."""
    return re.sub(r'[\s,，。;；:：、"\'\u201c\u201d『』()\[\]（）<>《》\-—_·]+', '', s)
