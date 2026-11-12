#!/usr/bin/env python3
"""MX机制实验运行器: 3任务×2场景×2配对×2臂=24次真实执行(探索性,须单独GO)
用法: python3 mech_run.py dryrun|run
"""
import sys, json, importlib.util
sys.path.insert(0, "/root/research_outputs/RQ_DYN_V6_DESIGN")
spec=importlib.util.spec_from_file_location("v6ex","/root/research_outputs/RQ_DYN_V6_DESIGN/v6_executor.py")
v6=importlib.util.module_from_spec(spec); spec.loader.exec_module(v6)

TASKS=["MX1_E04","MX2_STSHUN","MX3_ZD"]
# 配对设计: 每任务4配对(2×S3+2×S4),区组内臂序固定交替(pair奇数PD先/偶数FC先,机制实验不涉统计随机化声明)
order=lambda pair: ("Proposed-Dynamic","Fixed-Composite") if pair%2==1 else ("Fixed-Composite","Proposed-Dynamic")

def build_plan():
    plan=[]
    for t in TASKS:
        for pair in [1,2,3,4]:
            sc="S3" if pair<=2 else "S4"
            for arm in order(pair):
                plan.append(dict(task=t,pair=pair,scenario=sc,arm=arm))
    return plan  # 24条

def main(mode):
    if mode=="dryrun": v6.set_dry_run(True)
    plan=build_plan()
    assert len(plan)==24
    pkgs={t:json.load(open(f"/root/research_outputs/RQ_DYN_V6_DESIGN/mech_experiment/{t}.json")) for t in TASKS}
    runs=[]; spent=0.0; CAP=1.20
    for i,e in enumerate(plan):
        if spent>CAP:
            print(f"⛔ 预算熔断: 累计¥{spent:.4f}>¥{CAP},停止于第{i}次,已执行{len(runs)}次"); break
        r=v6.execute_task(pkgs[e["task"]],e["arm"],e["scenario"],e["pair"],
                          deadline_s=300,exec_tag="MX")
        # 关键日志完整性守卫
        pl=r.get("process_log",{})
        missing=[k for k in ("decision_log","inject_trace","node_log","_recovery_texts") if k not in pl]
        if missing or not pl.get("inject_trace",{}).get("inject_node"):
            print(f"⛔ 关键日志缺失{missing},停止"); json.dump(runs,open("mech_result_PARTIAL.json","w"),ensure_ascii=False); raise SystemExit(2)
        runs.append(r); spent+=r["cost_yuan"]
        print(f"[{i+1}/24] {e['task']} {e['scenario']} p{e['pair']} {e['arm'][:12]:12s} "
              f"TP={r['tp']}/{r['n_slots']} inj={r['process_log']['inject_trace']['inject_node']} "
              f"decisions={len(r['process_log']['decision_log'])} cost=¥{r['cost_yuan']:.4f}",flush=True)
    m=v6.derive_metrics(runs)
    json.dump({"runs":runs,"metrics":m},open("/root/research_outputs/RQ_DYN_V6_DESIGN/mech_experiment/"
        +("dryrun_result.json" if mode=="dryrun" else "mech_result.json"),"w"),ensure_ascii=False,indent=1)
    print("\n=== 机制指标 ==="); print(json.dumps(m,ensure_ascii=False,indent=1))

if __name__=="__main__":
    main(sys.argv[1] if len(sys.argv)>1 else "dryrun")
