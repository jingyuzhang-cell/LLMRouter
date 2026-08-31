#!/usr/bin/env python3
"""Build outcome-blind candidate queues for C9 protocol amendment 001.

Only question, paragraphs and raw tables are projected from MultiHiertt. Gold
answer, program, evidence and question-type fields are never consulted.
"""
import hashlib
import json
import re
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path("/root")
OUT = ROOT / "phase_c9_0"
MH = OUT / "external/MultiHiertt-data/multihiertt_data"
SEED = "20260831|C9_0_PROTOCOL_AMENDMENT_001"
FORBIDDEN = {"answer", "program", "text_evidence", "table_evidence", "question_type"}


def stable(value):
    return hashlib.sha256((SEED + "|" + value).encode()).hexdigest()


def norm(value):
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9%]+", " ", str(value).lower())).strip()


class TableParser(HTMLParser):
    def __init__(self):
        super().__init__(); self.rows=[]; self.row=[]; self.cell=[]; self.in_cell=False; self.attrs=[]
    def handle_starttag(self, tag, attrs):
        if tag == "tr": self.row=[]
        elif tag in {"td", "th"}: self.in_cell=True; self.cell=[]; self.attrs.append(dict(attrs))
    def handle_data(self, data):
        if self.in_cell: self.cell.append(data)
    def handle_endtag(self, tag):
        if tag in {"td", "th"}:
            self.row.append(re.sub(r"\s+", " ", "".join(self.cell)).strip()); self.in_cell=False
        elif tag == "tr" and self.row: self.rows.append(self.row)


def parse_table(raw):
    p=TableParser(); p.feed(raw); return p.rows, p.attrs


def project_multihiertt():
    projected=[]
    for split in ("train", "dev", "test"):
        for row in json.loads((MH/(split+".json")).read_text()):
            qa=row.get("qa") or {}
            # Deliberately access only the allowed key.
            projected.append({
                "source":"MultiHiertt", "source_id":str(row["uid"]),
                "question":str(qa.get("question", "")),
                "paragraphs":[str(x) for x in row.get("paragraphs", [])],
                "tables":[str(x) for x in row.get("tables", [])],
                "source_split":split,
            })
    return projected


def dependent_steps(question):
    q=norm(question)
    rules=[]
    if re.search(r"(?:same|current) (?:growth|increasing|change) rate", q) and re.search(r"what (?:will|would)", q):
        rules.append("derive_rate_then_project")
    if re.search(r"in the year (?:with|where|having)", q) and re.search(r"(?:growth|increasing|change) rate|average|sum|total", q):
        rules.append("select_condition_then_compute")
    if re.search(r"(?:combined|sum|total|average) .+ (?:as a percentage|portion|ratio|compared|compare)", q):
        rules.append("aggregate_then_normalize_or_compare")
    if re.search(r"percentage change .+ (?:ratio|percentage|margin|rate)", q):
        rules.append("derive_metric_then_compare")
    if re.search(r"(?:difference|change) between .+ (?:growth|percentage|ratio|average)", q):
        rules.append("derive_two_metrics_then_compare")
    return rules


def hierarchy_required(item):
    q=norm(item["question"]); reasons=[]
    comparative=bool(re.search(r"\b(?:which year|most|highest|lowest|larger|smaller|increase|decrease|growth|average|sum|total|difference|compare|between)\b",q))
    for ti,raw in enumerate(item["tables"]):
        rows,attrs=parse_table(raw)
        if len(rows)<3: continue
        labels=[norm(r[0]) if r else "" for r in rows]
        # A group header has a label but no numeric payload; repeated child rows
        # below different group headers encode a parent/child path.
        group=[]
        for i,r in enumerate(rows):
            payload=" ".join(r[1:])
            if labels[i] and not re.search(r"\d",payload): group.append(i)
        repeated={x for x in labels if x and labels.count(x)>=2 and len(x)>=4 and x not in {"total","subtotal","amount","revenue","revenues"}}
        referenced=[x for x in repeated if x in q]
        # Require the same child label below at least two distinct parent rows.
        for child in referenced:
            parents=set()
            for pos,label in enumerate(labels):
                if label != child: continue
                prior=[g for g in group if g < pos]
                if prior: parents.add(labels[max(prior)])
            if len(parents)>=2 and comparative:
                reasons.append({"table_index":ti,"kind":"same_child_across_parent_groups","child_label":child,"parent_labels":sorted(parents)[:6]})
    return reasons


def task_id(source, source_id):
    return "c9_"+hashlib.sha256((source+"|"+source_id).encode()).hexdigest()[:20]


def main():
    items=project_multihiertt()
    multi=[]; hierarchy=[]
    for x in items:
        base={"task_id":task_id(x["source"],x["source_id"]),"source_dataset":x["source"],"source_id":x["source_id"],
              "question":x["question"],"context":"\n".join(x["paragraphs"]),"tables_html":x["tables"]}
        steps=dependent_steps(x["question"])
        steps=[s for s in steps if s in {"derive_rate_then_project","select_condition_then_compute"}]
        if steps: multi.append(base|{"proposed_capability":"multi_step_numerical_reasoning","observable_inclusion_reason":steps})
        hierarchy_reasons=hierarchy_required(x)
        strict_reasons=[]
        qn=norm(x["question"])
        for reason in hierarchy_reasons:
            parents=reason["parent_labels"]
            parent_refs=[p for p in parents if len(p)>3 and p in qn]
            years={y for p in parents for y in re.findall(r"\b(?:19|20)\d{2}\b",p)}
            year_path=len(years)>=2 and (re.search(r"which year|what year|when",qn) or len(set(re.findall(r"\b(?:19|20)\d{2}\b",qn)))>=2)
            if parent_refs or year_path:
                strict_reasons.append(reason|{"question_parent_references":parent_refs,"year_parent_path":bool(year_path)})
        if strict_reasons: hierarchy.append(base|{"proposed_capability":"hierarchical_table_reasoning","observable_inclusion_reason":strict_reasons})
    multi.sort(key=lambda x:stable("multi|"+x["task_id"])); hierarchy.sort(key=lambda x:stable("hierarchy|"+x["task_id"]))
    for name,rows in (("C9_MULTI_STEP_AMENDMENT_001_REVIEW.jsonl",multi),("C9_HIERARCHICAL_TABLE_REVIEW.jsonl",hierarchy)):
        (OUT/name).write_text("".join(json.dumps(x|{"review_decision":None,"review_reason":None},ensure_ascii=False)+"\n" for x in rows))
    audit={"status":"CANDIDATE_QUEUES_BUILT_PENDING_BLIND_REVIEW","protocol_amendment":"C9_0_PROTOCOL_AMENDMENT_001",
           "candidate_counts":{"multi_step_numerical_reasoning":len(multi),"hierarchical_table_reasoning":len(hierarchy)},
           "allowed_multihiertt_fields":["uid","qa.question","paragraphs","tables"],"forbidden_fields_not_used":sorted(FORBIDDEN),
           "outcome_accessed":False,"model_response_accessed":False,"api_calls":0}
    (OUT/"C9_0_AMENDMENT_001_CANDIDATE_AUDIT.json").write_text(json.dumps(audit,indent=2)+"\n")
    print(json.dumps(audit,indent=2))


if __name__ == "__main__": main()
