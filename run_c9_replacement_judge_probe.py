#!/usr/bin/env python3
"""Outcome-blind replacement-judge calibration only; never writes formal labels."""
import asyncio, hashlib, json, os, random, re, string, sys, time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path("/root")
DATA = ROOT / "phase_c9_0"
PROJECT = ROOT / "autodl-tmp/LLMRouter-extracted/LLMRouter-main/LLMRouter-main"
SEED = "20260831|C9_2_QUALITY_EVALUATION_V1"
N = 15

def read(path):
    return [json.loads(x) for x in Path(path).read_text().splitlines() if x.strip()]

for line in (ROOT / ".env").read_text().splitlines():
    value = line.strip()
    if value and not value.startswith("#") and "=" in value:
        key, secret = value.split("=", 1)
        os.environ.setdefault(key.strip(), secret.strip().strip('"').strip("'"))

sys.path.insert(0, str(PROJECT))
from openclaw_router.config import OpenClawConfig
from openclaw_router.server import LLMBackend
from openclaw_router.judge_utils import extract_message_text

tasks = {x["task_id"]: x for x in read(DATA / "C9_DEV_TASKS.jsonl") if x.get("split") == "development_train"}
routes = {x["task_id"]: x for x in read(DATA / "C9_2_EVALUATION_ROUTE_MANIFEST.jsonl")}
groups = defaultdict(list)
for row in read(DATA / "C9_TRAIN_RESPONSES.jsonl"):
    if row.get("success") and routes[row["task_id"]]["evaluation_route"] == "independent_judge_0_4":
        groups[(row["task_id"], int(row["repeat"]))].append(row)
assert len(groups) == 810

strata = defaultdict(list)
for key, values in groups.items():
    strata[(tasks[key[0]]["primary_capability"], len(values))].append(key)
for keys in strata.values():
    keys.sort(key=lambda k: hashlib.sha256(f"C9_REPLACEMENT_PROBE|{k[0]}|{k[1]}".encode()).hexdigest())
ordered_strata = sorted(strata)
selected = []
while len(selected) < N:
    progressed = False
    for stratum in ordered_strata:
        if strata[stratum] and len(selected) < N:
            selected.append(strata[stratum].pop(0)); progressed = True
    if not progressed: break
assert len(selected) == N

def blinded(key, order_tag):
    tid, rep = key
    values = sorted(groups[key], key=lambda x: x["model"])
    labels = list(string.ascii_uppercase[:len(values)])
    indexes = list(range(len(values)))
    digest = hashlib.sha256(f"{SEED}|{order_tag}|{tid}|{rep}".encode()).hexdigest()
    random.Random(int(digest, 16)).shuffle(indexes)
    ordered = [values[i] for i in indexes]
    mapping = {labels[j]: ordered[j]["model"] for j in range(len(ordered))}
    answers = "\n\n".join(f"Answer {labels[j]}:\n{ordered[j].get('answer','')}" for j in range(len(ordered)))
    return mapping, answers

def prompt_for(key, order_tag):
    tid, rep = key; task = tasks[tid]; mapping, answers = blinded(key, order_tag)
    reference = str(task.get("reference_answer") or "").strip()
    refpart = f"\nReference answer:\n{reference}" if reference else "\nNo reference answer is available. Judge only whether each answer is correct and supported by the supplied context/table."
    prompt = f'''You are an independent evaluator. Score every blinded candidate answer independently; do not rank candidates or infer model identity. Use only the question, supplied context/table, and reference answer when present.
Rubric: 4=fully correct and supported; 3=mostly correct with only minor omission; 2=partly correct with a material omission or local error; 1=little correct content and main conclusion wrong; 0=incorrect, irrelevant, unsupported, or no valid answer.
Return only JSON exactly shaped as {{"scores":[{{"label":"A","score":4,"reason":"brief reason"}}]}}. Include every supplied label exactly once; score must be an integer 0..4.
Question:
{task.get("question","")}
Context:
{task.get("context","")}
Table:
{json.dumps(task.get("table") or [], ensure_ascii=False)}{refpart}

{answers}'''
    return mapping, prompt

def parse(raw, mapping):
    try:
        match = re.search(r"\{.*\}", raw, re.S); obj = json.loads(match.group(0) if match else raw)
        got = {str(x["label"]): x for x in obj["scores"]}
        if set(got) != set(mapping) or any(not isinstance(x.get("score"), int) or not 0 <= x["score"] <= 4 for x in got.values()): return None
        return {mapping[label]: int(got[label]["score"]) for label in mapping}
    except Exception:
        return None

async def call(backend, model, key, order_tag):
    mapping, prompt = prompt_for(key, order_tag); start = time.perf_counter(); parsed = None; error = None
    try:
        result = await backend.call(model, [{"role":"user","content":prompt}], max_tokens=1500, temperature=0, stream=False)
        parsed = parse(extract_message_text(result), mapping)
        if parsed is None: raise ValueError("judge_json_schema_invalid")
    except Exception as exc:
        error = str(exc)[:1000]
    return {"group_id":f"{key[0]}:{key[1]}","judge_model":model,"order_tag":order_tag,"success":parsed is not None,"scores_by_model":parsed,"error":error,"latency_ms":round((time.perf_counter()-start)*1000,2)}

async def main():
    config = OpenClawConfig.from_yaml(str(PROJECT / "configs/openclaw_multi_provider.yaml")); backend = LLMBackend(config)
    manifest = [{"group_id":f"{t}:{r}","task_id":t,"repeat_id":r,"primary_capability":tasks[t]["primary_capability"],"candidate_count":len(groups[(t,r)])} for t,r in selected]
    (DATA / "C9_2_REPLACEMENT_JUDGE_PROBE_MANIFEST.json").write_text(json.dumps({"created_at":datetime.now(timezone.utc).isoformat(),"groups":manifest},ensure_ascii=False,indent=2)+"\n")
    results = []
    for index, key in enumerate(selected, 1):
        for model, tag in (("doubao-seed-2.1-turbo","primary"),("gemini-2.5-pro","secondary")):
            row = await call(backend, model, key, tag); results.append(row)
            print(json.dumps({"progress":f"{index}/{N}","group_id":row["group_id"],"judge":model,"success":row["success"],"error":row["error"]},ensure_ascii=False),flush=True)
        if index <= 5:
            row = await call(backend,"doubao-seed-2.1-turbo",key,"primary"); row["replicate"]="exact_duplicate"; results.append(row)
            row = await call(backend,"doubao-seed-2.1-turbo",key,"perturbed"); row["replicate"]="order_perturbation"; results.append(row)
    (DATA / "C9_2_REPLACEMENT_JUDGE_PROBE_EVENTS.jsonl").write_text("".join(json.dumps(x,ensure_ascii=False)+"\n" for x in results))
    print(json.dumps({"status":"PROBE_COLLECTION_COMPLETE","events":len(results)},ensure_ascii=False))

asyncio.run(main())
