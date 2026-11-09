"""Bounded discovery. Semantic workspace choice belongs to the host agent."""
import os
from pathlib import Path

EXCLUDED = {'.git', '.agent-entry', '.worktrees', 'node_modules', '.venv', 'venv',
            '__pycache__', 'dist', 'build', 'target', 'coverage'}
MARKERS = ('AGENTS.md', 'README.md', 'package.json', 'pyproject.toml', 'Cargo.toml',
           'go.mod', '.git')


def discover(root, depth=2, limit=80, max_entries=2000):
    root = Path(root).expanduser().resolve(strict=True)
    if not root.is_dir():
        raise ValueError('Discovery root must be a directory.')
    if not 0 <= depth <= 5 or not 1 <= limit <= 500:
        raise ValueError('Depth must be 0..5 and limit 1..500.')
    queue = [(root, 0)]
    result = []
    visited = 0
    truncated = False
    while queue and len(result) < limit:
        directory, level = queue.pop(0)
        result.append({'path': str(directory),
                       'markers': [name for name in MARKERS if (directory / name).exists()]})
        if level >= depth:
            continue
        children = []
        try:
            with os.scandir(str(directory)) as entries:
                for entry in entries:
                    visited += 1
                    if visited > max_entries:
                        truncated = True
                        break
                    if (not entry.name.startswith('.') and entry.name not in EXCLUDED
                            and entry.is_dir(follow_symlinks=False)):
                        children.append((Path(entry.path), level + 1))
                    if len(children) + len(queue) + len(result) >= limit:
                        truncated = True
                        break
        except PermissionError:
            result[-1]['unreadable'] = True
        queue.extend(sorted(children, key=lambda item: str(item[0])))
        if visited > max_entries:
            break
    return {'root': str(root), 'candidates': result,
            'truncated': truncated or bool(queue), 'entries_examined': min(visited, max_entries),
            'selection': 'Host selects cwd from task context; candidates are not relevance rankings.'}
