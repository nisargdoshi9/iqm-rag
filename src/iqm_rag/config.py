"""Central configuration: data paths and settings read from environment variables.

Loading a `.env` file is added once the dependency choice is made.
"""

import os
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT_DIR / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
CHUNKS_DIR = DATA_DIR / "chunks"
EVALUATION_DIR = DATA_DIR / "evaluation"

BASE_URL = "https://help.iqm.com/en"

SCRAPER_USER_AGENT = os.environ.get("SCRAPER_USER_AGENT", "")
SCRAPER_DELAY_SECONDS = float(os.environ.get("SCRAPER_DELAY_SECONDS", "1.0"))
