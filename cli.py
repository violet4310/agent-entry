#!/usr/bin/env python3
"""Repository convenience entry; the skill bundle also runs independently."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / 'skills' / 'agent-entry' / 'scripts'))
from agent_entry.cli import main

if __name__ == '__main__':
    raise SystemExit(main())
