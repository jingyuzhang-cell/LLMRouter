"""Migrate arenahard judge journals v2->v3 and grade only cells with new raw responses.

Budget-inheritance path: migrate() copies the v2 append-only journals (no API
calls, labels unchanged for already-graded responses); run() then judges only
the recovered reasoning cells whose (source, response, slot) keys are new.
Old v2 directories are never modified.
"""
import json
import os
import sys
from pathlib import Path
from dotenv import dotenv_values
from openai import OpenAI
from .judge_primary import migrate, run
from .embed_queries import write_json
ROOT=Path(__file__).resolve().parents[1]

PAIRS=[('train','judged_train_primary_v2','judged_train_primary_v3'),
       ('validation','judged_validation_primary_v2','judged_validation_primary_v3'),
       ('test','judged_test_primary_v2','judged_test_primary_v3')]


def main(only=None):
    key=os.environ.get('QWEN_API_KEY') or dotenv_values('/root/.env').get('QWEN_API_KEY')
    if not key:raise RuntimeError('Configured judge credential unavailable')
    client=OpenAI(base_url='https://dashscope.aliyuncs.com/compatible-mode/v1',api_key=key,timeout=120,max_retries=0)
    results={}
    for partition,old_name,new_name in PAIRS:
        if only and partition not in only:continue
        old=ROOT/'data'/old_name;new=ROOT/'data'/new_name
        if not new.exists():
            migrate(old,new)
        summary=run(ROOT/'data/cohort_full_v2',ROOT/'data/raw',new,client,partition=partition)
        results[partition]=summary
        print(partition, json.dumps(summary), flush=True)
    write_json(ROOT/'router_v2/JUDGE_V3_MIGRATION.json',dict(partitions=results))


if __name__=='__main__':main(set(sys.argv[1:]) or None)
