"""Quality evaluators (protocol v1.1 - per task, no global judge).

math:    exact_match on the final number (\\boxed or #### or last number)
code:    pass@1 sandbox execution (reuses LLMRouterBench execution harness)
knowledge: option letter match
general: qwen-max judge (judge_prompts/v1.md) - called from judge.py step, not here
"""
import importlib.util
import json
import pathlib
import re
import sys

LLRB = pathlib.Path("/root/routing_reproduction/llmrouterbench_r2/LLMRouterBench")


def _load_exec(task):  # load execution.py directly to avoid evaluation/__init__ chain
    spec = importlib.util.spec_from_file_location(f"{task}_execution",
                                                  LLRB / "evaluation" / task / "execution.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m

NUM_RE = re.compile(r"-?\$?\d[\d,]*\.?\d*%?")
BOXED_RE = re.compile(r"\\boxed\{([^{}]+)\}")


def _num(s):
    return float(s.replace(",", "").replace("$", "").replace("%", "").strip())


def extract_number(text):
    m = BOXED_RE.findall(text or "")
    if m:
        cands = NUM_RE.findall(m[-1])
        if cands:
            return _num(cands[-1])
    tail = (text or "").rsplit("####", 1)
    if len(tail) == 2:
        cands = NUM_RE.findall(tail[1])
        if cands:
            return _num(cands[-1])
    lines = [l for l in (text or "").splitlines() if l.strip()]
    for line in reversed(lines[-5:] if len(lines) >= 5 else lines):
        cands = NUM_RE.findall(line)
        if cands:
            return _num(cands[-1])
    return None


def exact_match_math(answer, gt, tol=1e-4):
    a, g = extract_number(answer), _num(gt) if gt is not None else None
    if a is None or g is None:
        return None  # parse_failed
    return float(abs(a - g) <= max(tol, abs(g) * 1e-6))


def extract_option(text):
    # A boxed option is an explicit final-answer form commonly emitted by math-
    # heavy chat models. Restrict the payload to one option letter so boxed
    # intermediate numeric work cannot be mistaken for a multiple-choice answer.
    boxed = re.findall(r"\\boxed\s*\{\s*([A-J])\s*\}", text or "", re.I)
    if boxed:
        return boxed[-1].upper()
    m = re.findall(r"[Aa]nswer\s*(?:is|:)?\s*\(?([A-J])\)?", text or "")
    if m:
        return m[-1].upper()
    lines = [l.strip() for l in (text or "").splitlines() if l.strip()]
    for line in reversed(lines[-3:]):
        m = re.fullmatch(r"\(?([A-J])\)?\.?", line)
        if m:
            return m.group(1).upper()
    # Accept a response that consists of a single option-prefixed paragraph,
    # e.g. "A. Reptiles ...". Reject copied option lists by requiring exactly
    # one option-prefixed line in the entire response.
    prefixed = [re.match(r"^\s*([A-J])[.)]\s+\S", line, re.I)
                for line in (text or "").splitlines()]
    prefixed = [match for match in prefixed if match]
    if len(prefixed) == 1 and lines and re.match(r"^\s*[A-J][.)]\s+\S", lines[0], re.I):
        return prefixed[0].group(1).upper()
    return None


def option_match(answer, gt):
    a = extract_option(answer)
    if a is None:
        return None
    return float(a == str(gt).strip().upper()[-1])


def extract_code(text):
    blocks = re.findall(r"```(?:python|py)?\s*\n(.*?)```", text or "", re.S)
    if blocks:
        return "\n\n".join(blocks)
    return text or ""


def pass_at1_mbpp(answer, gt_json):
    """Sandbox-extract the code and run the official test_list."""
    tests = json.loads(gt_json)
    code = extract_code(answer)
    if not code.strip():
        return None
    result = _load_exec("MBPP").check_correctness(0, 0, code + "\n\n" + "\n".join(tests), 10.0)
    return float(result.get("passed", False))


def pass_at1_humaneval(answer, gt_json):
    gt = json.loads(gt_json)
    code = extract_code(answer)
    if not code.strip():
        return None
    prog = code + "\n\n" + gt["test"] + f"\ncheck({gt['entry_point']})\n"
    result = _load_exec("HumanEval").check_correctness(0, 0, prog, 10.0)
    return float(result.get("passed", False))


def evaluate(rec):
    """Fill quality.auto_* / final / quality_source for all 4 slots of one record."""
    src = rec["dataset"]
    for r in rec["responses"]:
        q = r["quality"]
        if r["status"] != "ok" or r.get("answer") is None:
            q["quality_source"] = {"gsm8k": "exact_match", "mbpp": "pass@1", "humaneval": "pass@1",
                                   "mmlupro": "option_match", "arenahard": "judge_qwen-max"}[src]
            continue
        ans, gt = r["answer"], rec["ground_truth"]
        if src == "gsm8k":
            s = exact_match_math(ans, gt)
        elif src == "mmlupro":
            s = option_match(ans, gt)
        elif src == "mbpp":
            s = pass_at1_mbpp(ans, gt)
        elif src == "humaneval":
            s = pass_at1_humaneval(ans, gt)
        else:
            s = None  # arenahard -> judge step
        q["quality_source"] = {"gsm8k": "exact_match", "mbpp": "pass@1", "humaneval": "pass@1",
                               "mmlupro": "option_match", "arenahard": "judge_qwen-max"}[src]
        if s is None:
            r["status"] = "parse_failed" if src != "arenahard" else r["status"]
        else:
            q["auto_score"], q["auto_correct"] = s, bool(s)
            q["final"] = s
    return rec
