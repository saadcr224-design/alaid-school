"""Vercel Python entrypoint; include the repository root in module lookup."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server import Handler

class handler(Handler):
    pass
