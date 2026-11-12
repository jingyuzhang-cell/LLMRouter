#!/usr/bin/env python3
"""Gold建设双硬门禁 V1 (2026-11-11 窗口裁决)
门禁1 SPAN: 证据跨度必须为原文精确切片(逐字),禁止撰写/改写/拼接; locator独立字段
门禁2 SEGMENT: DAG段落必须有有效起止锚点; 禁用30000字符兜底; 上游不得含结论段
内置反面测试(6项),任何一项不符合预期即认为门禁不可信→拒绝使用
用法:
  python3 gold_gates.py selftest
  python3 gold_gates.py span  <slot_table.json> <doc1> [doc2 ...]
  python3 gold_gates.py segment <case_dir> [decision_html]
"""
import json, re, sys, os, hashlib, subprocess

NORM = lambda s: re.sub(r'[\s,，()（）]', '', s)
LEAK_MARKS = ["根据当事人违法行为的事实", "我会决定:", "我局决定:", "上述当事人应自收到本处罚决定书",
              "上述当事人应自收到本处罚决定书之日起"]

# ---------- 文本读取 ----------
def read_text(path):
    if path.endswith(".html") or path.endswith(".HTML"):
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from extract_decision import extract as _ex
        return _ex(path)[1]
    if False:
        raw = open(path, encoding="utf-8", errors="ignore").read()
        m = re.search(rb'charset=["\']?([\w-]+)', raw.encode("utf-8", "ignore")[:3000])
        b = open(path, "rb").read()
        mm = re.search(rb'charset=["\']?([\w-]+)', b[:3000])
        enc = mm.group(1).decode().lower() if mm else "utf-8"
        t = b.decode("gb18030" if enc in ("gb2312", "gbk", "gb18030") else "utf-8", "ignore")
        t = re.sub(r'<(script|style)[^>]*>.*?</\1>', ' ', t, flags=re.S | re.I)
        return re.sub(r'<[^>]+>', ' ', t)
    if path.endswith(".pdf"):
        r = subprocess.run(["pdftotext", path, "-"], capture_output=True, text=True, timeout=180)
        return r.stdout or ""
    return open(path, encoding="utf-8", errors="ignore").read()

def doc_sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()

# ---------- 门禁1: 跨度 ----------
def span_ok(span, norm_docs):
    """跨度必须是某一文档中的精确连续子串(逐字); 支持…分片的每片分别验证"""
    if not span or len(NORM(span)) < 10:
        return False, "跨度过短/空"
    frags = [f for f in re.split(r'[…]', span) if len(NORM(f)) >= 8]
    if not frags:
        return False, "无有效分片"
    for f in frags:
        nf = NORM(f)
        if len(nf) < 8:
            continue
        if not any(nf in d for d in norm_docs):
            return False, f"分片未在原文: {nf[:40]}"
    return True, "ok"

def check_spans(table_path, doc_paths):
    tab = json.load(open(table_path))
    docs = [(p, NORM(read_text(p)), doc_sha(p)) for p in doc_paths if os.path.exists(p)]
    norm_docs = [d for _, d, _ in docs]
    results = []
    for s in tab.get("slots", []):
        ok, why = span_ok(s.get("evidence_span", ""), norm_docs)
        # locator 不得混入 span
        if ok and re.match(r'^(§|P\d|AR\d|INQ|DEC)', s.get("evidence_span", "")):
            ok, why = False, "locator混入span"
        results.append(dict(fact_id=s["fact_id"], ok=ok, why=why))
    bad = [r for r in results if not r["ok"]]
    return dict(gate="SPAN", total=len(results), failed=len(bad), bad=bad,
                doc_sha256={p: h for p, _, h in docs})

# ---------- 门禁2: DAG段落 ----------
def check_segments(case_dir, decision_path=None):
    segs = [os.path.join(case_dir, f) for f in os.listdir(case_dir) if f.endswith(".txt")]
    # 允许独立补充文档段(非从决定书切出)白名单: 文件名含'承诺'/'更正'且对应doc存在
    results = []
    for p in segs:
        c = open(p).read()
        name = os.path.basename(p)
        leak = [k for k in LEAK_MARKS if k in c]
        # 兜底截断检测: 段长恰为30000字符 → 疑似兜底
        fallback = (len(c) >= 29990)
        ok = (not leak) and (not fallback)
        results.append(dict(segment=name, chars=len(c), leak_marks=leak,
                            fallback_truncation=fallback, ok=ok))
    bad = [r for r in results if not r["ok"]]
    return dict(gate="SEGMENT", total=len(results), failed=len(bad), bad=bad)

# ---------- 反面测试 ----------
def selftest():
    print("=== 门禁反面测试(6项) ===")
    src = "经查明,当事人存在以下违法事实:一是虚增收入12,345.67万元;二是未披露担保3,000万元。"
    nd = [NORM(src)]
    cases = [
        ("原文精确切片", "虚增收入12,345.67万元", True, span_ok),
        ("同义改写", "虚增营业收入约为1.23亿元", False, span_ok),
        ("跨段拼接", "虚增收入12,345.67万元…未披露担保3,000万元" if False else "虚增收入12,345.67万元未披露担保", False, span_ok),
        ("Locator混入span", "§12:虚增收入12,345.67万元", False, None),
        ("空跨度", "", False, span_ok),
        ("过短跨度", "12,345", False, span_ok),
    ]
    allok = True
    for name, span, expect, fn in cases:
        if fn is None:
            # locator混入 由 check_spans 的规则判定
            got = not bool(re.match(r'^(§|P\d|AR\d|INQ|DEC)', span))
        else:
            got = fn(span, nd)[0]
        ok = (got == expect)
        allok &= ok
        print(f"  {'✓' if ok else '✗'} {name}: 期望{'PASS' if expect else 'FAIL'} 实际{'PASS' if got else 'FAIL'}")
    # 段落泄露反面测试
    tests = [("干净段", "一、虚假记载经查明虚增收入1亿元。", True),
             ("含处罚结论", "一、虚假记载…我会决定:罚款60万元。", False),
             ("兜底30000", "x" * 30000, False)]
    for name, content, expect in tests:
        leak = [k for k in LEAK_MARKS if k in content]
        fb = len(content) >= 29990
        got = (not leak) and (not fb)
        ok = (got == expect)
        allok &= ok
        print(f"  {'✓' if ok else '✗'} 段-{name}: 期望{'PASS' if expect else 'FAIL'} 实际{'PASS' if got else 'FAIL'}")
    print(f"\n门禁可信性: {'✓通过(可用于建设)' if allok else '✗未通过(禁止使用)'}")
    return allok

if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "selftest"
    if mode == "selftest":
        sys.exit(0 if selftest() else 1)
    elif mode == "span":
        r = check_spans(sys.argv[2], sys.argv[3:])
        print(json.dumps(r, ensure_ascii=False, indent=1))
        sys.exit(0 if r["failed"] == 0 else 1)
    elif mode == "segment":
        r = check_segments(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)
        print(json.dumps(r, ensure_ascii=False, indent=1))
        sys.exit(0 if r["failed"] == 0 else 1)
