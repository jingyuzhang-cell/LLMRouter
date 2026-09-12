"""Frozen pairwise trainer on corrected full 400-query repeat labels."""
from pathlib import Path
from . import train_repeat_pairwise_compatibility_115 as trainer
ROOT=Path(__file__).resolve().parents[1]
trainer.PANEL_DIR=ROOT/'router_v2/knowledge_validation_400'
trainer.DATA=ROOT/'data/repeat_compatibility_400_rescore_v1'
trainer.OUT=ROOT/'router_v2/experiment_repeat_pairwise_compatibility_400'
if __name__=='__main__': trainer.main()
