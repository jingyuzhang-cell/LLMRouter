"""Offline parser-consistent rescore for the full 400-query repeat panel."""
from pathlib import Path
from . import rescore_repeat_compatibility_115 as rescorer
ROOT=Path(__file__).resolve().parents[1]
rescorer.SOURCE=ROOT/'data/repeat_compatibility_400'
rescorer.OUT=ROOT/'data/repeat_compatibility_400_rescore_v1'
if __name__=='__main__': rescorer.main()
