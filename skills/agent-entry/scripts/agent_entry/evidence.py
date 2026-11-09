"""Verify worker references and read bounded source text locally."""
import hashlib
import json
from pathlib import Path

SCHEMA = {
    'type': 'object', 'additionalProperties': False,
    'required': ['summary', 'findings', 'unresolved'],
    'properties': {
        'summary': {'type': 'string'},
        'unresolved': {'type': 'array', 'items': {'type': 'string'}},
        'findings': {'type': 'array', 'items': {
            'type': 'object', 'additionalProperties': False,
            'required': ['path', 'start_line', 'end_line', 'reason'],
            'properties': {'path': {'type': 'string'}, 'start_line': {'type': 'integer'},
                           'end_line': {'type': 'integer'}, 'reason': {'type': 'string'}}}}
    }
}


def extract(cwd, reply, max_findings=6, max_lines=40, max_bytes=16000):
    root = Path(cwd).resolve(strict=True)
    data = json.loads(reply)
    if (not isinstance(data, dict) or not isinstance(data.get('summary'), str)
            or not isinstance(data.get('unresolved'), list)
            or not all(isinstance(s, str) for s in data['unresolved'])
            or not isinstance(data.get('findings'), list)):
        raise ValueError('Invalid retrieval result shape.')
    if len(data['findings']) > max_findings:
        raise ValueError('Too many findings; ask the worker for at most 6.')
    total = 0
    findings = []
    for finding in data['findings']:
        if not isinstance(finding, dict) or not isinstance(finding.get('path'), str):
            raise ValueError('Invalid finding.')
        relative = Path(finding['path'])
        if relative.is_absolute():
            raise ValueError('Evidence paths must be relative to cwd.')
        path = (root / relative).resolve(strict=True)
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise ValueError('Evidence path escapes the selected directory.') from exc
        start, end = finding.get('start_line'), finding.get('end_line')
        if (type(start) is not int or type(end) is not int or start < 1
                or end < start or end - start + 1 > max_lines
                or not isinstance(finding.get('reason'), str)):
            raise ValueError('Invalid evidence range/reason; maximum 40 lines per finding.')
        # Bounded read, including if the file grows after stat.
        with path.open('rb') as handle:
            content = handle.read(2_000_001)
        if len(content) > 2_000_000 or b'\x00' in content:
            raise ValueError('Evidence source is binary or exceeds 2 MB.')
        lines = content.decode('utf-8').splitlines(keepends=True)
        if end > len(lines):
            raise ValueError('Evidence range exceeds current source length.')
        excerpt = ''.join(lines[start - 1:end])
        total += len(excerpt.encode('utf-8'))
        if total > max_bytes:
            raise ValueError('Evidence excerpts exceed the total byte budget.')
        findings.append(dict(finding, path=str(path.relative_to(root)), excerpt=excerpt,
                             sha256=hashlib.sha256(content).hexdigest()))
    return dict(data, findings=findings, excerpt_bytes=total)
