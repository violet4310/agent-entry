#!/usr/bin/env python3
"""Deterministic protocol fixture, never makes network/model calls."""
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

args = sys.argv[1:]
prompt = sys.stdin.buffer.read().decode('utf-8')
root = Path(os.environ['FAKE_CODEX_STATE'])
root.mkdir(exist_ok=True)
with (root / 'calls.jsonl').open('a', encoding='utf-8') as handle:
    handle.write(json.dumps({'args': args, 'prompt': prompt, 'cwd': os.getcwd(),
                             'nested': os.environ.get('AGENT_ENTRY_WORKER')}, ensure_ascii=False) + '\n')
if 'resume' in args:
    remote_id = args[args.index('resume') + 1]
    known = root / (remote_id + '.json')
    if not known.exists():
        print('unknown thread', file=sys.stderr)
        sys.exit(4)
    record = json.loads(known.read_text())
    if record['cwd'] != os.getcwd():
        sys.exit(5)
else:
    remote_id = str(uuid.uuid4())
    record = {'cwd': os.getcwd(), 'messages': []}
record['messages'].append(prompt)
(root / (remote_id + '.json')).write_text(json.dumps(record, ensure_ascii=False))


def event(value):
    print(json.dumps(value, ensure_ascii=False), flush=True)


event({'type': 'thread.started', 'thread_id': 'wrong-thread' if prompt == 'WRONG_THREAD' else remote_id})
if prompt == 'TIMEOUT':
    child = 'import time,pathlib; time.sleep(4); pathlib.Path(%r).write_text("orphan")' % str(root / 'orphan.txt')
    subprocess.Popen([sys.executable, '-c', child])
    time.sleep(10)
if prompt == 'FAIL':
    event({'type': 'turn.failed', 'error': {'message': 'approval unavailable'}})
    print('approval unavailable', file=sys.stderr)
    sys.exit(3)
if prompt == 'MALFORMED':
    print('not-json', flush=True)
if 'EVIDENCE_ESCAPE' in prompt:
    reply = json.dumps({'summary': 'untrusted summary', 'findings': [
        {'path': '../secret.txt', 'start_line': 1, 'end_line': 1, 'reason': 'test'}], 'unresolved': []})
elif '--output-schema' in args:
    reply = json.dumps({'summary': 'located passage', 'findings': [
        {'path': 'source.txt', 'start_line': 2, 'end_line': 3, 'reason': 'relevant original'}], 'unresolved': []})
else:
    reply = '  回复：' + prompt + '\n\n'
if prompt != 'NO_FINAL':
    Path(args[args.index('-o') + 1]).write_bytes(reply.encode('utf-8'))
event({'type': 'item.completed', 'item': {'type': 'agent_message', 'text': 'progress is not the final file'}})
if prompt != 'INCOMPLETE':
    event({'type': 'turn.completed', 'usage': {'input_tokens': 20, 'output_tokens': 10}})
