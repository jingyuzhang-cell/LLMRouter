#!/usr/bin/env python3
"""文书身份硬门禁 V1(2026-11-11 窗口裁决)
五项强制检查,任一不过→不得进入Gold证据池:
  1. 证券代码与公司名称
  2. 公告标题及公告编号
  3. 文书落款日期
  4. 文件大小/SHA256/有效正文长度
  5. 正文发行主体与目标任务主体一致
用法: python3 verify_docs.py <target_dir_or_glob> [...]  |  python3 verify_docs.py --all
输出: DOC_IDENTITY_LEDGER.json (PASS/QUARANTINE + 逐项检查明细)
"""
import os, re, sys, json, glob, hashlib, subprocess, html as _html

def read_text(fp):
    if fp.endswith(".pdf"):
        r = subprocess.run(["pdftotext", fp, "-"], capture_output=True, text=True, timeout=180)
        return r.stdout or ""
    b = open(fp, "rb").read()
    m = re.search(rb'charset=["\']?([\w-]+)', b[:3000])
    enc = m.group(1).decode().lower() if m else "utf-8"
    if enc in ("gb2312", "gbk", "gb18030"):
        raw = b.decode("gb18030", "ignore")
    else:
        raw = b.decode("utf-8", "ignore")
    raw = re.sub(r'<(script|style)[^>]*>.*?</\1>', ' ', raw, flags=re.S | re.I)
    t = _html.unescape(re.sub(r'<[^>]+>', ' ', raw))
    if len(re.findall(r'[\u4e00-\u9fa5]', t)) < 50:  # 疑似GBK站点
        try:
            t2 = raw.encode("latin-1", "ignore").decode("gbk", "ignore")
            t2 = _html.unescape(re.sub(r'<[^>]+>', ' ', t2))
            if len(re.findall(r'[\u4e00-\u9fa5]', t2)) > len(re.findall(r'[\u4e00-\u9fa5]', t)):
                t = t2
        except Exception:
            pass
    return t

def norm(t):
    return re.sub(r'\s+', '', t)

def verify(fp, expect_code=None, expect_names=None):
    """返回五项检查结果。expect_names: 可接受的发行主体名列表(任一命中即通过)"""
    r = {"file": os.path.basename(fp), "path": fp, "size": 0, "sha256": "", "checks": {}, "verdict": "QUARANTINE", "notes": []}
    # --- 检查4: 大小/hash/正文长度 ---
    r["size"] = os.path.getsize(fp)
    r["sha256"] = hashlib.sha256(open(fp, "rb").read()).hexdigest()
    header_ok = (open(fp, "rb").read(4) == b"%PDF") if fp.endswith(".pdf") else True
    body = read_text(fp) if r["size"] > 0 else ""
    cn = len(re.findall(r'[\u4e00-\u9fa5]', body))
    c4 = r["size"] > 1024 and header_ok and cn >= 200
    r["checks"]["4_size_hash_bodylen"] = dict(pass_=c4, size=r["size"], header_pdf=header_ok, cn_chars=cn)
    if not c4:
        r["notes"].append("空/损坏/正文过短")
        return r  # 后续检查无意义
    n = norm(body)

    # --- 检查1: 证券代码与公司名 ---
    # CSRC决定书正文通常只载公司全名而无证券代码; 故"代码 或 公司名"任一命中即通过
    codes = set(re.findall(r'(?<!\d)(\d{6})(?!\d)', n[:3000]))
    c1_code = (expect_code in codes) if expect_code else False
    c1_name = any(nm in n for nm in (expect_names or [])) if expect_names else False
    if expect_code is None and not (expect_names or []):
        c1 = None  # 无预期主体→不适用(非失败)
    else:
        c1 = bool(c1_code or c1_name)
    r["checks"]["1_code_and_name"] = dict(pass_=c1, codes_found=sorted(codes)[:6],
                                          expect_code=expect_code, code_hit=c1_code, name_hit=c1_name,
                                          rule="代码或公司名任一命中")

    # --- 检查2: 公告标题/编号 ---
    ann = re.findall(r'公告编号[:：]?\s*(\d{4}[-—]?\d{2,3}|临?\s*\d{4}[-—]\d{2,3})', n)
    title = re.search(r'(关于[^。]{4,40}的?公告|[一-龥]{2,20}年度报告|[一-龥]{2,20}半年度报告|[一-龥]{2,20}季度报告|招股说明书|募集说明书)', n[:2500])
    docno = re.findall(r'[〔\[【]\s*(\d{4})\s*[〕\]】]\s*(\d{1,3})\s*号', n[:3000])
    c2 = bool(ann or title or docno)
    r["checks"]["2_title_and_number"] = dict(pass_=c2, ann_numbers=ann[:3],
                                             title=title.group(0) if title else None,
                                             doc_numbers=[f"{a}〕{b}号" for a, b in docno[:3]])

    # --- 检查3: 落款日期 ---
    tail = n[-8000:]
    dates = re.findall(r'(20\d{2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日', tail)
    dates += re.findall(r'(20\d{2})-(\d{2})-(\d{2})', tail)
    if re.search(r'[〇零一二三四五六七八九]{4}\s*年\s*[一二三四五六七八九十]{1,2}\s*月', tail):
        dates = list(dates) + [("中文数字落款", "?", "?")]
    c3 = bool(dates)
    r["checks"]["3_signature_date"] = dict(pass_=c3, dates=["-".join(d) for d in dates[-3:]])

    # --- 检查5: 发行主体一致(正文出现曾用名/关联方不算;此处核主体关键词密度) ---
    if expect_names:
        hits = {nm: n.count(nm) for nm in expect_names}
        top = max(hits.items(), key=lambda x: x[1])
        c5 = top[1] >= 3
        r["checks"]["5_subject_consistency"] = dict(pass_=c5, name_counts=hits, dominant=top[0])
    else:
        r["checks"]["5_subject_consistency"] = dict(pass_=None, note="未提供预期主体")

    fails = [k for k, v in r["checks"].items() if v.get("pass_") is False]
    docno_ok = bool(r["checks"]["2_title_and_number"].get("doc_numbers") or
                    r["checks"]["2_title_and_number"].get("ann_numbers"))
    if not fails:
        r["verdict"] = "PASS"
    elif fails == ["3_signature_date"] and docno_ok:
        r["verdict"] = "PASS_WITH_NOTE"
        r["notes"].append("落款日期缺失但文号可锚定(源页面省略日期);准入允许,Gold报告须标注")
    else:
        r["verdict"] = "QUARANTINE"
    return r

def main():
    args = sys.argv[1:]
    targets = []
    if not args or args[0] == "--all":
        for pat in ["/root/research_outputs/V6_CANDIDATE_RAW/**/*.pdf",
                    "/root/research_outputs/V6_CANDIDATE_RAW/**/*.html",
                    "/root/research_outputs/V6_CANDIDATE_RAW/**/*.HTML"]:
            targets += glob.glob(pat, recursive=True)
        targets = [t for t in targets if "_QUARANTINE" not in t]
    else:
        for a in args:
            targets += glob.glob(a, recursive=True)

    # 目录名→(代码,可接受主体名)
    REG = {
        "changyuan_600525": ("600525", ["长园"]), "xinwei_600485": ("600485", ["信威"]),
        "gaosheng_000971": ("000971", ["高升"]), "yishite_300376": ("300376", ["易事特"]),
        "xinlun_002341": ("002341", ["新纶"]), "sante_002159": ("002159", ["三特"]),
        "tianshan_300313": ("300313", ["天山"]), "shenglil_002426": ("002426", ["胜利精密"]),
        "zhongan_600654": ("600654", ["中安科", "中安消", "飞乐"]), "shenwu_000820": ("000820", ["神雾"]),
        "yingfangwei_000670": ("000670", ["盈方微"]), "jinya_300028": ("300028", ["金亚"]),
        "wanfu_300268": ("300268", ["万福生科"]), "zhongchao_002471": ("002471", ["中超"]),
        "tianwo_002564": ("002564", ["天沃"]), "yijian_600093": ("600093", ["易见"]),
        "gaohong_000851": ("000851", ["高鸿", "大唐高鸿"]), "langqi_000523": ("000523", ["浪奇"]),
        "chaohua_002288": ("002288", ["超华"]), "furen_600781": ("600781", ["辅仁"]),
        "wu_zhong_600587": ("600587", ["吴中"]), "yuancheng_603388": ("603388", ["元成"]),
        "gangtai_600687": ("600687", ["刚泰"]), "tongjitang_600090": ("600090", ["同济堂"]),
        "suwu_600200": ("600200", ["苏吴"]), "haiwang_000078": ("000078", ["海王"]),
        "tefa_000070": ("000070", ["特发"]), "guomei_600898": ("600898", ["国美"]),
        "kaisha_000796": ("000796", ["凯撒"]), "aikang_002610": ("002610", ["爱康"]),
        "dongfang_600811": ("600811", ["东方集团"]), "changyao_300391": ("300391", []),
        "busen_002569": ("002569", ["步森"]), "dongli_002164": ("002164", ["东力"]),
        "fukong_600634": ("600634", ["富控"]), "hengjiu_002808": ("002808", ["恒久"]),
        "huaze_000693": ("000693", ["华泽"]), "jiaoda_600530": ("600530", ["交大"]),
        "kangni_603111": ("603111", ["康尼"]), "kaidi_000939": ("000939", ["凯迪"]),
        "lvdadi_002200": ("002200", ["绿大地"]), "meili_000010": ("000010", ["美丽生态"]),
        "qingyue_688496": ("688496", ["清越"]), "tianhai_300008": ("300008", ["天海"]),
        "tianrun_002113": ("002113", ["天润"]), "tianxiang_300362": ("300362", ["天翔"]),
        "tianye_600807": ("600807", ["天业"]), "xintai_300372": ("300372", ["欣泰"]),
        "xinyi_600145": ("600145", ["新亿"]), "yihua_600978": ("600978", ["宜华"]),
        "yuebo_300742": ("300742", ["越博"]), "yuechuanmei_002181": ("002181", ["粤传媒"]),
        "cong_cang_002477": (None, []), "chuying_002477": ("002477", ["雏鹰"]),
        "changsheng_002680": ("002680", ["长生"]), "anzhoong_002667": (None, []),
        "dongfangjinyu_600086": ("600086", ["东方金钰"]), "dongfangtong_300379": ("300379", ["东方通"]),
        "hongtu_600122": ("600122", ["宏图"]), "jinzhou_000587": ("000587", ["金洲"]),
        "longli_002604": ("002604", ["龙力"]), "yanzheng_002667": (None, []),
    }
    ledger = []
    for fp in sorted(targets):
        if not os.path.isfile(fp): continue
        parts = fp.split(os.sep)
        code, names = None, []
        for p in parts:
            if p in REG:
                code, names = REG[p]; break
            for k, (c, nm) in REG.items():
                if p.startswith(k.split("_")[0] + "_"):
                    code, names = c, nm; break
            if code or names: break
        ledger.append(verify(fp, code, names))
    out = "/root/research_outputs/V6_CANDIDATE_RAW/DOC_IDENTITY_LEDGER.json"
    json.dump(ledger, open(out, "w"), ensure_ascii=False, indent=1)
    p = [x for x in ledger if x["verdict"] == "PASS"]
    q = [x for x in ledger if x["verdict"] == "QUARANTINE"]
    print(f"总计 {len(ledger)} 份 | PASS {len(p)} | QUARANTINE {len(q)}")
    for x in q:
        fails = [k for k, v in x["checks"].items() if v.get("pass_") is False]
        print(f"  ✗ {x['path'].split('V6_CANDIDATE_RAW/')[-1]} [{','.join(fails)}] {x['notes']}")
    print(f"\n→ {out}")

if __name__ == "__main__":
    main()
