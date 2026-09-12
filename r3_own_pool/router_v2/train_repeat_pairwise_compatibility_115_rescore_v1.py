"""Run the frozen trainer against parser-corrected repeat labels."""
from pathlib import Path
from . import train_repeat_pairwise_compatibility_115 as trainer

ROOT = Path(__file__).resolve().parents[1]
trainer.DATA = ROOT / "data/repeat_compatibility_115_rescore_v1"
trainer.OUT = ROOT / "router_v2/experiment_repeat_pairwise_compatibility_115_rescore_v1"

if __name__ == "__main__":
    trainer.main()
