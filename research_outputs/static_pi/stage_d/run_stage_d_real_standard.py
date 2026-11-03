#!/usr/bin/env python3
"""带标准 GLM 适配器的真实执行 launcher（不改冻结执行器）。"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, "/root/research_outputs/static_pi/stage_a")
sys.path.insert(0, "/root/capital_opinion_pilot")

cfg = json.load(open("/root/.zcode/v2/provider_config.json"))
ds = next(r["config"]["access"]["apiKey"]
          for r in cfg["config"]["providerConfigRules"]["providerRules"]
          if r["providerId"] == "deepseek")
os.environ["DEEPSEEK_API_KEY"] = ds
os.environ["STAGE_D_REAL_CALLS_AUTHORIZED"] = "1"

from standard_glm_runtime import install
install()
import stage_d_executor as E

args = sys.argv[1:] or ["run", "--out", "runs_final_real_standard"]
# 本 launcher 只用于真实执行：强制 --real，防止误跑 Mock
if args and args[0] == "run" and "--real" not in args:
    args.insert(1, "--real")
system_exit = E.main()
sys.exit(system_exit)
