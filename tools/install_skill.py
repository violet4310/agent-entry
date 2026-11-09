#!/usr/bin/env python3
"""Copy the complete skill without replacing an existing installation."""
import argparse
import shutil
import tempfile
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--destination', type=Path, default=Path.home() / '.codex/skills/agent-entry')
    args = parser.parse_args()
    source = Path(__file__).resolve().parents[1] / 'skills/agent-entry'
    target = args.destination.expanduser().absolute()
    if target.exists() or target.is_symlink():
        parser.error('Destination already exists; no files were replaced: ' + str(target))
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.agent-entry-install-', dir=str(target.parent)) as temporary:
        staged = Path(temporary) / 'agent-entry'
        shutil.copytree(source, staged, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        staged.rename(target)
    print('Installed skill: ' + str(target))
    print('Start a new host session to discover $agent-entry.')


if __name__ == '__main__':
    main()
