# sc2bot (rewrite)

Clean rewrite skeleton:
- Engine: build/produce/placement
- Strategy: JSON-driven plan + knobs
- Behaviors: drop/combat modules

Run (example):
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -U pip
pip install -e .
python run.py --strat default --map AbyssalReefLE
