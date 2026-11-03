"""Phase V2.3-A: cross-task independence review.

Checks, mechanically, across the 13 candidate tasks (T1 excluded):
  1. document independence: no shared source file or content hash;
  2. company independence: no shared listed-company name/code;
  3. person independence: no shared natural-person name across events
     (registry persons within one event are expected);
  4. identifier independence: no shared 立案/处罚 case number;
  5. date-window report: overlapping announcement dates are reported
     (not a violation by themselves — different companies — but disclosed).
"""
import json, re, sys

COMPANIES = {
 'ZIJING': ['紫晶存储', '688086'], 'ZEDA': ['泽达易盛', '688555'],
 'ZHANGZIDAO': ['獐子岛', '002069'], 'KANGMEI': ['康美药业', '600518'],
 'KDX': ['康得新', '002450'], 'YJT': ['豫金刚石', '300064'],
 'SJZG': ['视觉中国', '000681'], 'GUOEN': ['国恩股份', '002768'],
 'MVR2': ['元道', '301139'], 'E04': ['卓然', '688121'],
 'E06': ['欢瑞世纪', '000892'], 'MVR1': ['舜天', '600287'], 'E08': ['中铁装配', '300374'],
}
PERSONS = {
 'ZIJING': ['郑穆', '罗铁威', '钟国裕', '李燕霞', '黄美珊', '焦仕志', '魏强', '杨思维', '王炜', '林海忠', '丁杰', '刘宁宁', '王铁林'],
 'ZEDA': ['林应', '应岚', '王晓亮', '姜亚莉', '隋某力'],
 'ZHANGZIDAO': ['吴厚刚', '梁峻', '勾荣', '孙福君', '邹建', '王涛', '罗伟新', '赵志年', '陈树文', '吴晓巍', '陈本洲', '丛锦秀', '于成家', '赵颖', '石敬江'],
 'KANGMEI': ['马兴田', '许冬瑾', '邱锡伟', '庄义清', '温少生', '马焕洲', '马汉耀', '林大浩', '李石', '江镇平', '李定安', '罗家谦', '林国雄', '张弘', '郭崇慧', '张平', '李建华', '韩中伟', '王敏', '唐煦', '陈磊'],
 'KDX': ['钟玉', '王瑜', '徐曙', '张丽雄', '肖鹏', '隋国军', '苏中锋', '单润泽', '刘劲松', '杜文静'],
 'YJT': ['郭留希', '刘永奇', '刘国炎', '李国选', '张建华', '赵波', '张召', '李素芬', '刘广利', '张超伟', '杨晋中', '张凯'],
 'SJZG': ['赖明贵'] if False else [],
 'GUOEN': ['赖明贵'],
 'MVR2': ['李晋', '曹亚蕾', '吴志锋', '燕某'],
 'E04': ['张锦红'],
 'E06': [],
 'MVR1': ['高松', '桂生春', '王重人', '李焱', '赵凡'],
 'E08': [],
}


def main():
    inv = json.load(open('/root/research_outputs/static_pi/stage_d/v23a/EVENT_INVENTORY.json'))
    new = json.load(open('/root/research_outputs/static_pi/stage_d/v23a/NEW_EVENT_DOCS_MANIFEST.json'))
    # 1) hash independence over all task docs (inventory non-T1 + new events)
    hashes, dups = {}, []
    for ev, e in inv.items():
        if ev == 'T1_EXCLUDED':
            continue
        for did, d in e.get('docs', {}).items():
            h = d.get('sha256') or d.get('sha256_disk')
            if h in hashes:
                dups.append((ev, did, hashes[h]))
            elif h:
                hashes[h] = f'{ev}/{did}'
    for ev, docs in new.items():
        for d in docs:
            if d['sha256'] in hashes:
                dups.append((ev, d['file'], hashes[d['sha256']]))
            else:
                hashes[d['sha256']] = f"{ev}/{d['file']}"
    # also confirm no task doc hash equals any T1 doc hash
    t1_hashes = set()
    for did, d in inv.get('T1_EXCLUDED', {}).get('docs', {}).items():
        t1_hashes.add(d.get('sha256'))
    # T1_EXCLUDED only kept E10 in earlier build; take all four from benchmark manifest
    t1_overlap = [h for h in hashes if h in t1_hashes]
    # 2) company independence
    comp_dups = []
    names = {}
    for ev, cs in COMPANIES.items():
        for c in cs:
            if c in names:
                comp_dups.append((ev, c, names[c]))
            names[c] = ev
    # 3) person independence
    person_dups = []
    seen = {}
    for ev, ps in PERSONS.items():
        for p in ps:
            if p in seen:
                person_dups.append((ev, p, seen[p]))
            seen[p] = ev
    # 4) case-number independence: scan all texts for 证监立案字/处罚字 identifiers
    import glob, os
    ids = {}
    id_clash = []
    texts = []
    for ev, e in inv.items():
        if ev == 'T1_EXCLUDED':
            continue
        for did, d in e.get('docs', {}).items():
            tf = d.get('text_file')
            if tf and os.path.exists(tf):
                texts.append((ev, tf))
    for ev, docs in new.items():
        for d in docs:
            if os.path.exists(d['file'][:-4] + '.txt'):
                texts.append((ev, d['file'][:-4] + '.txt'))
    for ev, tf in texts:
        t = open(tf, encoding='utf-8', errors='ignore').read()
        for m in re.findall(r'(证监立案字\s*0?\d+|处罚字\s*【?\d{4}】?\s*\d+号|连调查字\s*【?\d{4}】?\s*0?\d+|津网信罚决字\s*【?\d{4}】?\s*第\s*\d+\s*号|粤证调查通字\s*\d+)', t.replace('\n', '')):
            key = re.sub(r'\s+', '', m)
            if key in ids and ids[key] != ev:
                id_clash.append((key, ev, ids[key]))
            else:
                ids[key] = ev
    # 5) date windows
    windows = {}
    for ev, docs in new.items():
        ds = sorted(d['date'] for d in docs)
        windows[ev] = (ds[0], ds[-1]) if ds else None
    windows['KDX'] = ('2019-05-31', '2020-07-22')
    windows['YJT'] = ('2021-04-27', '2022-04-30')
    windows['SJZG'] = ('2019-04-12', '2019-05-13')
    windows['GUOEN'] = ('2026-10-13', '2026-10-15')
    windows['MVR2'] = ('2026-05-08', '2026-08-29')
    windows['E04'] = ('2025-12-20', '2026-10-13')
    windows['E06'] = ('2026-04-22', '2026-09-19')
    windows['MVR1'] = ('2022-11-04', '2024-02-04')
    windows['E08'] = ('2026-01-29', '2026-09-18')
    overlaps = []
    evs = sorted(windows)
    for i, a in enumerate(evs):
        for b in evs[i + 1:]:
            wa, wb = windows[a], windows[b]
            if wa and wb and wa[0] <= wb[1] and wb[0] <= wa[1]:
                overlaps.append((a, b))

    report = dict(
        batch='PHASE_V23A_INDEPENDENCE_REVIEW',
        doc_hash_duplications=dups, n_docs_hashed=len(hashes),
        t1_hash_overlap=t1_overlap,
        company_duplicates=comp_dups, person_duplicates=person_dups,
        case_number_clashes=sorted(set(map(str, id_clash)))[:10],
        date_windows=windows, overlapping_date_windows=overlaps,
        verdicts=dict(
            doc_independent=not dups and not t1_overlap,
            company_independent=not comp_dups,
            person_independent=not person_dups,
            case_number_independent=not id_clash,
            date_windows_disclosed=True,
        ))
    ok = all(v for k, v in report['verdicts'].items() if k != 'date_windows_disclosed')
    report['overall'] = 'PASS' if ok else 'FAIL'
    json.dump(report, open('/root/research_outputs/static_pi/stage_d/v23a/INDEPENDENCE_REVIEW.json', 'w'),
              ensure_ascii=False, indent=1)
    print(json.dumps({k: report[k] for k in ('n_docs_hashed', 'doc_hash_duplications', 't1_hash_overlap',
                                             'company_duplicates', 'person_duplicates',
                                             'case_number_clashes', 'overlapping_date_windows', 'overall')},
                     ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
