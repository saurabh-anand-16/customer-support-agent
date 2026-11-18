"""
config.py - settings shared by every script.

Nothing here does any work. It only holds constants, so that "today", the random
seed and the folder paths are defined in exactly one place.
"""
from datetime import date
from pathlib import Path

# The project root is the folder that contains `scripts/`. Path(__file__) is this file,
# .resolve() makes it absolute, and .parent.parent goes up two levels.
# Using pathlib means the same code works on Windows, macOS and Linux.
ROOT = Path(__file__).resolve().parent.parent

RAW_CSV = ROOT / "data" / "raw" / "amazon.csv"      # the Kaggle file, never edited
CLEAN_DIR = ROOT / "data" / "clean"                 # every generated table is written here
SCHEMA_SQL = ROOT / "schema.sql"
DB_PATH = ROOT / "returns_agent.db"

# The agent never asks the computer's clock what day it is. "Today" is fixed so that
# every answer ("is this order still inside its window?") is reproducible and testable.
TODAY = date(2026, 11, 17)

# Fixed random seed: running the generator twice gives byte-identical data.
SEED = 2026

# How much synthetic data to generate.
N_CUSTOMERS = 400
N_ORDERS = 2500

# Day counting (decided with you): the delivery date itself is day 1.
# So a 10-day window delivered on the 1st covers the 1st to the 10th, inclusive,
# and the last eligible day is delivery_date + (window - 1).
DELIVERY_DAY_IS_DAY_ONE = True
