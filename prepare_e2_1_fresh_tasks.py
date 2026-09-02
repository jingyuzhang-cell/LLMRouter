#!/usr/bin/env python3
"""Freeze fresh E2.1 tasks without consulting any model outcomes."""

import hashlib
import json
import math
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RAW = ROOT / "phase_c9_0/external/FinLongDocQA/dataset_qa.jsonl"
REPORTS = ROOT / "phase_c9_0/external/FinLongDocQA/reports"
OUT = ROOT / "e2_1_protocol"
N = 360
QUOTAS = {"mixed": 280, "table": 60, "text": 20}
SELECTION_SALT = "E2.1-A|20260901|"
B_SALT = "E2.1-B|20260901|"
MAX_CANDIDATE_CHARS = 180000
PAGE_PATTERN = re.compile(r"(?m)^# Page (\d+)\s*$")
TOKEN_PATTERN = re.compile(r"[A-Za-z0-9]+")

# Task manifests only. No response, score, decision, or result file is opened.
PRIOR_TASK_MANIFESTS = (
    ROOT / "e2_targeted_decomposition/E2_STAGE1_30.jsonl",
    ROOT / "phase_c9_0/C9_DEV_TASKS.jsonl",
    ROOT / "v3_confirmatory/V3_CONFIRMATORY_TASKS.jsonl",
    ROOT / "target_support_expansion_v1/combined_509_tasks_frozen.jsonl",
)


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().casefold())


def qhash(question: str) -> str:
    return hashlib.sha256(norm(question).encode("utf-8")).hexdigest()


def read_jsonl(path: Path):
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def prior_question_hashes() -> set[str]:
    seen = set()
    for path in PRIOR_TASK_MANIFESTS:
        if not path.exists():
            continue
        for row in read_jsonl(path):
            question = row.get("question") or row.get("query")
            if question:
                seen.add(qhash(str(question)))
    return seen


def dump_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def split_pages(text: str) -> list[tuple[int, str]]:
    matches = list(PAGE_PATTERN.finditer(text))
    return [
        (int(match.group(1)), text[match.end():matches[i + 1].start() if i + 1 < len(matches) else len(text)])
        for i, match in enumerate(matches)
    ]


def frozen_candidates(question: str, page_rows: list[tuple[int, str]]) -> list[int]:
    query = Counter(x.lower() for x in TOKEN_PATTERN.findall(question))
    document_frequency = Counter()
    page_counts = []
    for _, page_text in page_rows:
        counts = Counter(x.lower() for x in TOKEN_PATTERN.findall(page_text))
        page_counts.append(counts)
        for word in query:
            if word in counts:
                document_frequency[word] += 1
    n_pages = len(page_rows)
    ranked = []
    for (page, page_text), counts in zip(page_rows, page_counts):
        score = sum(
            (1 + math.log(counts[word])) * math.log((n_pages + 1) / (document_frequency[word] + 1))
            for word in query if counts[word]
        )
        ranked.append((score, page, len(page_text)))
    ranked.sort(key=lambda x: (-x[0], x[1]))
    selected, used = [], 0
    for _, page, chars in ranked:
        if selected and used + chars > MAX_CANDIDATE_CHARS:
            continue
        selected.append(page)
        used += chars
    return selected


def main() -> None:
    assert sum(QUOTAS.values()) == N
    excluded = prior_question_hashes()
    candidates = []
    raw_gold = {}
    for row in read_jsonl(RAW):
        question_hash = qhash(str(row["question"]))
        if question_hash in excluded:
            continue
        company, year = str(row["company"]), str(row["year"])
        report = REPORTS / company / f"{year}.md"
        if not report.exists() or row["type"] not in QUOTAS:
            continue
        canonical = f"finlongdocqa|{company}|{year}|{row['id']}"
        task_id = "e21_" + hashlib.sha256(canonical.encode()).hexdigest()[:20]
        selection_hash = hashlib.sha256(
            (SELECTION_SALT + canonical).encode("utf-8")
        ).hexdigest()
        task = {
            "task_id": task_id,
            "source": "FinLongDocQA",
            "source_id": str(row["id"]),
            "company": company,
            "year": year,
            "task_type": row["type"],
            "question": row["question"],
            "reference_answer": row["answer"],
            "document_path": str(report.relative_to(ROOT)),
            "document_id": f"FinLongDocQA:{company}:{year}",
            "question_normalized_sha256": question_hash,
            "selection_sha256": selection_hash,
        }
        candidates.append(task)
        raw_gold[task_id] = [
            f"FinLongDocQA:{company}:{year}:page:{int(page)}"
            for page in row["page_numbers"]
        ]

    selected = []
    page_cache = {}
    for task_type, quota in QUOTAS.items():
        stratum = sorted(
            (x for x in candidates if x["task_type"] == task_type),
            key=lambda x: (x["selection_sha256"], x["task_id"]),
        )
        accepted = []
        for task in stratum:
            report = ROOT / task["document_path"]
            if report not in page_cache:
                page_cache[report] = split_pages(report.read_text(encoding="utf-8"))
            candidate_pages = frozen_candidates(task["question"], page_cache[report])
            gold_pages = {int(x.rsplit(":", 1)[1]) for x in raw_gold[task["task_id"]]}
            if gold_pages.issubset(candidate_pages):
                task["candidate_page_ids"] = [
                    f"{task['document_id']}:page:{page}" for page in candidate_pages
                ]
                task["candidate_char_cap"] = MAX_CANDIDATE_CHARS
                accepted.append(task)
                if len(accepted) == quota:
                    break
        if len(accepted) < quota:
            raise RuntimeError(f"Insufficient retriever-reachable {task_type} tasks: {len(accepted)} < {quota}")
        selected.extend(accepted)
    selected.sort(key=lambda x: (x["selection_sha256"], x["task_id"]))
    assert len(selected) == N
    assert len({x["task_id"] for x in selected}) == N
    assert not ({x["question_normalized_sha256"] for x in selected} & excluded)

    b_subset = sorted(
        selected,
        key=lambda x: (
            hashlib.sha256((B_SALT + x["task_id"]).encode("utf-8")).hexdigest(),
            x["task_id"],
        ),
    )[:30]
    b_rows = [
        {
            "task_id": x["task_id"],
            "subset_sha256": hashlib.sha256(
                (B_SALT + x["task_id"]).encode("utf-8")
            ).hexdigest(),
        }
        for x in b_subset
    ]
    annotation_template = [
        {
            "task_id": x["task_id"],
            "annotator_id": "",
            "canonical_evidence_ids": [],
            "acceptable_alternative_sets": [],
            "notes": "",
            "completed": False,
        }
        for x in selected
    ]
    # Native dataset page labels are the frozen primary Gold under protocol 3.1.
    raw_gold_rows = [
        {"task_id": x["task_id"], "dataset_page_evidence_ids": raw_gold[x["task_id"]]}
        for x in selected
    ]

    OUT.mkdir(exist_ok=True)
    dump_jsonl(OUT / "E2_1_A_FRESH_360_TASKS.jsonl", selected)
    dump_jsonl(OUT / "E2_1_B_PREFIXED_30_TASKS.jsonl", b_rows)
    dump_jsonl(OUT / "E2_1_ANNOTATOR_A_TEMPLATE.jsonl", annotation_template)
    dump_jsonl(OUT / "E2_1_ANNOTATOR_B_TEMPLATE.jsonl", annotation_template)
    dump_jsonl(OUT / "E2_1_NATIVE_PAGE_GOLD_360.jsonl", raw_gold_rows)
    report = {
        "status": "TASKS_B_SUBSET_AND_NATIVE_GOLD_FROZEN",
        "selection_used_model_outcomes": False,
        "prior_task_manifests_checked": [str(p.relative_to(ROOT)) for p in PRIOR_TASK_MANIFESTS],
        "prior_question_hashes": len(excluded),
        "raw_candidates": len(candidates),
        "eligibility": "All native Gold pages reachable within frozen BM25 candidate set",
        "candidate_char_cap": MAX_CANDIDATE_CHARS,
        "selected_n": len(selected),
        "selected_strata": dict(Counter(x["task_type"] for x in selected)),
        "b_subset_n": len(b_rows),
        "gold_source": "FinLongDocQA dataset-provided page_numbers",
    }
    (OUT / "E2_1_TASK_SELECTION_REPORT.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
