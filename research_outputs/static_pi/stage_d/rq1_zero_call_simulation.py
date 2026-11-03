#!/usr/bin/env python3
"""RQ1 V1.2 零调用分析程序模拟（合成数据；不是实验证据）。

检验：LOTO 分配是否避免任务过拟合；H0 假阳性；H1 功效；
级联传播是否抵消局部优势；5 任务聚类 CI 的宽度。
"""
import random
import statistics

NODES = ["E1", "E2", "E3", "E4", "J1", "J2", "SINK"]
KIND = {"E1": "extract", "E2": "extract", "E3": "extract", "E4": "extract",
        "J1": "merge", "J2": "reason", "SINK": "sink"}
# 示例交互（非真实结果）：抽取 GLM 强；合并/推理 DS 强；综合 GLM 强
P_H1 = {
    "GLM": {"E1": .90, "E2": .90, "E3": .90, "E4": .90, "J1": .78, "J2": .75, "SINK": .89},
    "DS":  {"E1": .82, "E2": .82, "E3": .82, "E4": .82, "J1": .88, "J2": .91, "SINK": .81},
}
P_H0 = {m: {n: (P_H1["GLM"][n] + P_H1["DS"][n]) / 2 for n in NODES} for m in ("GLM", "DS")}
TASKS = [f"T{i}" for i in range(1, 6)]
REPS = 2
THRESH_TP = 1.0
THRESH_Q = THRESH_TP / 23.0   # ~0.0435 in mean-quality units


def bern(p, rng):
    return 1 if rng.random() < max(0.0, min(1.0, p)) else 0


def sim_once(pmap, cascade, rng, task_sd=0.03):
    task_off = {t: rng.gauss(0, task_sd) for t in TASKS}
    # Layer 1 fixed-input observations
    obs = {}
    for t in TASKS:
        for n in NODES:
            for m in ("GLM", "DS"):
                obs[(t, n, m)] = [bern(pmap[m][n] + task_off[t] + rng.gauss(0, .02), rng)
                                  for _ in range(REPS)]
    # LOTO allocation + held-out terminal
    diffs = []
    for held in TASKS:
        train = [t for t in TASKS if t != held]
        alloc = {}
        for n in NODES:
            mg = statistics.mean(obs[(t, n, "GLM")][0] for t in train)
            md = statistics.mean(obs[(t, n, "DS")][0] for t in train)
            alloc[n] = "GLM" if mg >= md else "DS"
        def terminal(model_choice):
            ps = []
            for n in NODES:
                m = model_choice(n) if callable(model_choice) else model_choice
                ps.append(pmap[m][n] + task_off[held])
            if cascade:
                return __import__("math").prod(ps)
            return statistics.mean(ps)
        q_alloc = terminal(lambda n: alloc[n])
        q_glm = terminal("GLM")
        q_ds = terminal("DS")
        diffs.append(q_alloc - max(q_glm, q_ds))
    return diffs


def summarize(diffs):
    mean = statistics.mean(diffs)
    sd = statistics.stdev(diffs) if len(diffs) > 1 else 0.0
    return mean, sd


def run(pmap, cascade, nsim=1000, seed=20261102):
    rng = random.Random(seed)
    means = []
    sig = 0
    for _ in range(nsim):
        d = sim_once(pmap, cascade, rng)
        m, _ = summarize(d)
        means.append(m)
        # 任务级 bootstrap CI（简化：对 5 个任务差重采样）
        boot = []
        for _ in range(500):
            sample = [d[rng.randrange(len(d))] for _ in range(len(d))]
            boot.append(statistics.mean(sample))
        boot.sort()
        lo = boot[int(0.025 * len(boot))]
        if m >= THRESH_Q and lo > 0:
            sig += 1
    return statistics.mean(means), sig / nsim


if __name__ == "__main__":
    print(f"threshold: +{THRESH_TP} TP = {THRESH_Q:.4f} mean-quality; nsim=1000")
    for label, pmap, cascade in [
        ("H0 无交互 / 加性终端", P_H0, False),
        ("H0 无交互 / 级联终端", P_H0, True),
        ("H1 示例交互 / 加性终端", P_H1, False),
        ("H1 示例交互 / 级联终端", P_H1, True),
    ]:
        mean, power = run(pmap, cascade)
        print(f"{label}: LOTO mean gain={mean:+.4f} ({mean*23:+.2f} TP), materiality rate={power:.3f}")
    print("\n注：合成数据，仅检验分析程序/LOTO/阈值；不是 RQ1 实验证据。")
