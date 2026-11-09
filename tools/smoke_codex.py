#!/usr/bin/env python3
"""Optional live Codex smoke test; creates only disposable read-only fixtures.

Uses existing Codex auth and consumes model usage. Never runs in user projects.
"""
import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--codex-bin', default='codex')
    parser.add_argument('--timeout', type=float, default=45)
    args = parser.parse_args()
    repository = Path(__file__).resolve().parents[1]
    fixture = Path(tempfile.mkdtemp(prefix='agent-entry-live-')).resolve()
    project = fixture / 'project'
    project.mkdir()
    (project / 'source.txt').write_text('Alpha\nThe retrieval marker is AE_SOURCE_42.\nOmega\n')
    base = [sys.executable, str(repository / 'cli.py'), '--state-dir', str(fixture / 'state'),
            '--codex-bin', args.codex_bin]
    print('Live smoke artifacts: ' + str(fixture), flush=True)

    def invoke(*command):
        result = subprocess.run(base + list(command), capture_output=True, text=True,
                                timeout=args.timeout + 10)
        if result.returncode:
            raise RuntimeError(result.stdout + result.stderr)
        return json.loads(result.stdout)

    common = ['--cwd', str(project), '--effort', 'low', '--timeout', str(args.timeout)]
    first = invoke('relay', *common, '--message',
                   'Remember the marker AE_SESSION_42 for this conversation. Reply only AE_SESSION_42. Do not use tools or delegate.')
    if first['reply'].strip() != 'AE_SESSION_42':
        raise RuntimeError('Unexpected first reply: ' + first['reply'])
    print('PASS relay: new thread', flush=True)
    second = invoke('send', first['session_id'], '--timeout', str(args.timeout), '--message',
                    'What marker did I ask you to remember? Reply only the marker. Do not use tools or delegate.')
    if second['remote_id'] != first['remote_id'] or second['reply'].strip() != 'AE_SESSION_42':
        raise RuntimeError('Resume did not preserve thread identity and marker.')
    print('PASS relay: same thread and remembered context', flush=True)
    found = invoke('retrieve', *common, '--message',
                   'Read source.txt. Locate the line containing the retrieval marker. Return its precise source location.')
    if not any('AE_SOURCE_42' in item['excerpt'] for item in found['evidence']['findings']):
        raise RuntimeError('Verified evidence did not include the source marker.')
    print('PASS retrieve: structured locations and locally verified source', flush=True)
    delegated = invoke('delegate', *common, '--message',
                       'Read source.txt and report the retrieval marker. Do not modify files or delegate further.')
    if 'AE_SOURCE_42' not in delegated['reply']:
        raise RuntimeError('Delegated task did not return the fixture result.')
    print('PASS delegate: bounded read-only task', flush=True)
    print('All four live turns passed. No write-enabled worker was started.', flush=True)
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (RuntimeError, OSError, subprocess.TimeoutExpired) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
