# 实验可比性：Z0 与 Z1 的输入一致性

## 冻结测量代码（calib_harness_v3.py, `measure()`）

```python
def measure(transport, ledger, reps=2):
    rows = setup_check()
    if any(r['status'] != 'OK' for r in rows.values()):
        print('SETUP NOT ALL OK — measurement refused (no calls made)')
        return dict(refused=True, setup=rows)
    tasks = load_tasks()
    RUNS.mkdir(exist_ok=True)
    units = []
    for tid, t in tasks.items():
        parent = json.loads((PARENTS / f'{tid}.json').read_text())
        inj = select_injection(t, parent)
        d1 = t['documents']['D1']; d2 = t['documents']['D2']
        tl_ans = parent['outputs']['tl']['answer']
        er_inj = inj['injected_er']
        for rep in (1, 2):
            prompt = P.xc_dual_generic(d1['doc_id'], d2['doc_id'], tl_ans[:2000], er_inj[:2000],
                                       d1['excerpt_text'], d2['excerpt_text'])
            ledger.pre(prompt, MAX_JOIN_TOKENS)
            o0 = transport.call(prompt, MAX_JOIN_TOKENS, f'xc:{tid}:{rep}')
            ledger.add(dict(kind='measure', arm='Z0', task=tid, rep=rep, node='xc', model=MODEL,
                            prompt_sha256=sha(prompt), answer=o0['answer'], finish=o0['finish'],
                            tokens_in=o0['tokens_in'], tokens_out=o0['tokens_out'],
                            cash_cny=o0['cash_cny'], latency_s=o0['latency_s'],
                            response_model=o0['response_model'], ts=time.strftime('%Y-%m-%dT%H:%M:%S')))
            prompt = P.loc_dual_generic(d1['doc_id'], d2['doc_id'], tl_ans[:2000], er_inj[:2000],
                                        d1['excerpt_text'], d2['excerpt_text'])
            ledger.pre(prompt, MAX_JOIN_TOKENS)
            ol = transport.call(prompt, MAX_JOIN_TOKENS, f'loc:{tid}:{rep}')
            ledger.add(dict(kind='measure', arm='Z1', task=tid, rep=rep, node='loc', model=MODEL,
                            prompt_sha256=sha(prompt), answer=ol['answer'], finish=ol['finish'],
                            tokens_in=ol['tokens_in'], tokens_out=ol['tokens_out'],
                            cash_cny=ol['cash_cny'], latency_s=ol['latency_s'],
                            response_model=ol['response_model'], ts=time.strftime('%Y-%m-%dT%H:%M:%S')))
            prompt = P.ver_dual_generic(d1['doc_id'], d2['doc_id'], ol['answer'][:2000],
                                        tl_ans[:2000], er_inj[:2000],
                                        d1['excerpt_text'], d2['excerpt_text'])
            ledger.pre(prompt, MAX_JOIN_TOKENS)
            ov = transport.call(prompt, MAX_JOIN_TOKENS, f'ver:{tid}:{rep}')
            ledger.add(dict(kind='measure', arm='Z1', task=tid, rep=rep, node='ver', model=MODEL,
                            prompt_sha256=sha(prompt), answer=ov['answer'], finish=ov['finish'],
                            tokens_in=ov['tokens_in'], tokens_out=ov['tokens_out'],
                            cash_cny=ov['cash_cny'], latency_s=ov['latency_s'],
                            response_model=ov['response_model'], ts=time.strftime('%Y-%m-%dT%H:%M:%S')))
            i0 = extract_json(o0['answer']); il = extract_json(ol['answer']); iv = extract_json(ov['answer'])
            s0, w0 = score_output(i0, inj, t, 'xc')
            sl, wl = score_output(il, inj, t, 'loc')
            sv, wv = score_output(iv, inj, t, 'ver')
            units.append(dict(task_id=tid, rep=rep, injection=inj['fact_id'],
                              correct=inj['correct'], wrong=inj['wrong'],
                              z0=dict(success=s0, why=w0, finish=o0['finish']),
                              z1=dict(loc=sl, loc_why=wl, ver=sv, ver_why=wv,
                                      success=(sl and sv), finish=[ol['finish'], ov['finish']])))
            print(f'{tid} rep{rep} inj={inj["fact_id"]} Z0={s0}({w0}) '
                  f'Z1={sl and sv}(loc={sl}:{wl}, ver={sv}:{wv})')
    report = dict(generated_at=time.strftime('%Y-%m-%dT%H:%M:%S'), units=units, caps=CAPS,
                  prior=PRIOR, ledger=dict(calls=ledger.calls, tokens=ledger.tokens, yuan=ledger.yuan))
    agg0 = sum(1 for u in units if u['z0']['success'])
    agg1 = sum(1 for u in units if u['z1']['success'])
    both_fail = {}
    for u in units:
        if not u['z0']['success']:
            both_fail.setdefault(u['task_id'], []).append(u['rep'])
    one_task_both = any(len(v) >= 2 for v in both_fail.values())
    report['summary'] = dict(n_units=len(units), z0_success=agg0, z1_success=agg1,
                             z1_gate=agg1 >= 8, z0_success_gate=agg0 <= 6,
                             z0_both_reps_fail_task=one_task_both,
                             z0_gate=(agg0 <= 6 and one_task_both))
    (RUNS / f'CAL5_V2_REPORT_{time.strftime("%Y%m%d_%H%M%S")}.json').write_text(
        json.dumps(report, ensure_ascii=False, indent=1))
    print('SUMMARY', report['summary'])

```

## 一致性事实

1. **同一父输出**：每个任务只调用一次 `select_injection(t, parent)`，得到 `tl_ans` 与 `er_inj`；两次重复与两个臂全部复用这两个字符串，不重新生成父输出。
2. **同一原始文书**：`d1['excerpt_text']`、`d2['excerpt_text']` 来自任务集 V2 的冻结输入；Z0 的 xc、Z1 的 loc 与 ver 均传入完全相同的两个字符串。
3. **同一注入**：`er_inj` 是冻结 er 原始回答的**单次替换**结果（`FACT_SEMANTICS_CHECK.json` 中 `injection_single_replace=true`），错误值、位置、次数在两次重复和两个臂中一致。
4. **Gold 只在事后评分**：`score_output` 在模型调用之后运行，使用任务集 `facts` 中的正确值做判定；调用前的提示词重建检查（`GOLD_ISOLATION_CHECK.json`）证明 `facts`/`injection_candidates` 未进入任何父节点提示词。
5. **输出切片一致**：Z0 的 xc 与 Z1 的 loc 接收相同的 `tl_ans[:2000]`/`er_inj[:2000]`；ver 额外接收 loc 的回答（这是 Z1 的处理结构，不是额外信息）。

## 可复核方式

- 查看 `outputs/{task}_{node}.json` 的 `prompt_sha256`，与 `prompts/{task}_{node}.txt` 的 SHA256 对照；
- 查看 `checks/INJECTION_INTEGRITY.json` 的替换计数与前后 SHA；
- 直接阅读 `code/calib_harness_v3.py` 的 `measure()` 与 `select_injection()`。
