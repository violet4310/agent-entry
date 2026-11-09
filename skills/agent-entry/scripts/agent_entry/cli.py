"""CLI shared by skill hosts and people; all three modes use one runtime."""
import argparse
import datetime
import json
import math
import os
import sys
import time
import uuid
from pathlib import Path

from .adapters import adapter_for
from .evidence import SCHEMA, extract
from .routing import discover
from .state import BusyError, Store


def timestamp():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def emit(value):
    print(json.dumps(value, ensure_ascii=False, indent=2))


def read_message(args):
    if args.message is not None:
        message = args.message
    elif args.message_file:
        message = Path(args.message_file).read_bytes().decode('utf-8')
    else:
        message = sys.stdin.buffer.read().decode('utf-8')
    if not message.strip():
        raise ValueError('Message must not be empty.')
    return message


def worker_message(mode, message):
    if mode == 'retrieve':
        return ('Locate evidence for the request below. Work read-only. Return JSON matching '
                'the provided schema: summary, findings, unresolved. At most 6 findings; each '
                'path relative to cwd with an inclusive start_line/end_line of at most 40 lines. '
                'Do not invent sources or quotes. Return empty findings if nothing applies. '
                'Do not route this request to another agent-entry worker.\n\nREQUEST:\n' + message)
    if mode == 'delegate':
        return ('Complete the bounded task below. Report changed/inspected files, decisions, '
                'checks actually run, and unresolved issues. Respect the selected sandbox and '
                'task scope. Do not route this request to another agent-entry worker.\n\nTASK:\n' + message)
    return message


def run_turn(store, record, message, executable, timeout):
    if os.environ.get('AGENT_ENTRY_WORKER') == '1':
        raise ValueError('Nested agent-entry execution is disabled; complete the assigned task directly.')
    artifacts = store.run_dir(record['id'])
    record.update(status='running', updated_at=timestamp(), last_run=str(artifacts))
    store.save(record)
    (artifacts / 'request.txt').write_text(message, encoding='utf-8')
    backend = adapter_for(record['backend'], executable)
    started = time.monotonic()
    result = backend.run(record, worker_message(record['mode'], message), artifacts, timeout,
                         SCHEMA if record['mode'] == 'retrieve' else None)
    metrics = {'elapsed_seconds': round(time.monotonic() - started, 3),
               'reply_bytes': len(result.reply),
               'event_bytes': (artifacts / 'events.jsonl').stat().st_size
               if (artifacts / 'events.jsonl').exists() else 0}
    record.update(status=result.status, remote_id=result.remote_id,
                  updated_at=timestamp(), last_error=result.error, last_metrics=metrics)
    evidence = None
    if result.status == 'success' and record['mode'] == 'retrieve':
        try:
            evidence = extract(record['cwd'], result.reply.decode('utf-8'))
            (artifacts / 'evidence.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding='utf-8')
        except (ValueError, OSError, UnicodeError) as exc:
            record.update(status='failed', last_error='Evidence verification failed: ' + str(exc))
    store.save(record)
    envelope = {'session_id': record['id'], 'backend': record['backend'],
                'remote_id': record['remote_id'], 'cwd': record['cwd'], 'mode': record['mode'],
                'status': record['status'], 'artifacts': str(artifacts), 'metrics': metrics}
    if record['status'] == 'success':
        if evidence is not None:
            envelope['evidence'] = evidence
        else:
            envelope['reply'] = result.reply.decode('utf-8')
    else:
        envelope['error'] = record['last_error']
    return envelope, result.reply


def start(args):
    cwd = Path(args.cwd).expanduser().resolve(strict=True)
    if not cwd.is_dir():
        raise ValueError('Worker cwd must be a directory.')
    adapter_for(args.backend, args.codex_bin)
    record = {'id': str(uuid.uuid4()), 'mode': args.command, 'cwd': str(cwd),
              'backend': args.backend, 'remote_id': None, 'model': args.model,
              'effort': args.effort, 'sandbox': 'workspace-write' if args.allow_writes else 'read-only',
              'status': 'created', 'created_at': timestamp(), 'updated_at': timestamp()}
    store = Store(args.state_dir)
    message = read_message(args)
    with store.locked():
        store.save(record)
        envelope, _ = run_turn(store, record, message, args.codex_bin, args.timeout)
    emit(envelope)
    return 0 if envelope['status'] == 'success' else 1


def continue_turn(args, message=None, raw=None):
    store = Store(args.state_dir)
    message = read_message(args) if message is None else message
    with store.locked():
        record = store.get(args.session_id)
        if not record.get('remote_id'):
            raise ValueError('No backend session ID recorded; inspect artifacts or use recover.')
        if record['status'] == 'running':
            raise ValueError('Session marked running. If the previous process crashed, use recover first.')
        envelope, reply = run_turn(store, record, message, args.codex_bin, args.timeout)
    use_raw = args.raw if raw is None else raw
    if use_raw and envelope['status'] == 'success':
        if record['mode'] != 'relay':
            raise ValueError('Raw replies are only available for relay sessions.')
        sys.stdout.buffer.write(reply)
        sys.stdout.buffer.flush()
    elif use_raw:
        print(json.dumps(envelope, ensure_ascii=False), file=sys.stderr)
    else:
        emit(envelope)
    return 0 if envelope['status'] == 'success' else 1


def chat(args):
    record = Store(args.state_dir).get(args.session_id)
    if record['mode'] != 'relay':
        raise ValueError('chat requires a relay session.')
    print('Relay session %s in %s. /status, /quit; one line per turn.' %
          (record['id'], record['cwd']), file=sys.stderr)
    while True:
        print('\nYou> ', end='', file=sys.stderr, flush=True)
        message = sys.stdin.readline()
        if message == '' or message.rstrip('\r\n') == '/quit':
            return 0
        if message.rstrip('\r\n') == '/status':
            print(json.dumps(Store(args.state_dir).get(args.session_id), ensure_ascii=False), file=sys.stderr)
            continue
        if not message.strip():
            continue
        code = continue_turn(args, message=message, raw=True)
        if code:
            return code


def recover(args):
    store = Store(args.state_dir)
    with store.locked():
        record = store.get(args.session_id)
        if record['status'] != 'running':
            raise ValueError('Recovery is only for a session left running by a crashed host.')
        path = Path(record['last_run']) / 'events.jsonl'
        if path.is_file():
            for line in path.read_text(encoding='utf-8', errors='replace').splitlines():
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                if event.get('type') == 'thread.started' and isinstance(event.get('thread_id'), str):
                    candidate = event['thread_id']
                    if record.get('remote_id') and candidate != record['remote_id']:
                        raise ValueError('Thread mismatch in recovery artifacts.')
                    record['remote_id'] = candidate
        # A stale lock is not proof the remote model/tool work stopped. No retry.
        record.update(status='interrupted', updated_at=timestamp(),
                      last_error='Recovered host record only. Inspect backend activity and files before resuming.')
        store.save(record)
    emit(record)
    return 0


def positive_timeout(value):
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError('timeout must be a positive finite number')
    return number


def parser():
    root = argparse.ArgumentParser(description='Agent Entry: delegate, retrieve, or relay in the right directory.')
    root.add_argument('--state-dir', default='.agent-entry', help='Persistent state root; keep the same absolute path across turns.')
    root.add_argument('--codex-bin', default='codex', help='Codex executable path (no shell command).')
    commands = root.add_subparsers(dest='command', required=True)
    lookup = commands.add_parser('discover', help='Bounded directory candidates; the host chooses relevance.')
    lookup.add_argument('--root', required=True)
    lookup.add_argument('--depth', type=int, default=2)
    lookup.add_argument('--limit', type=int, default=80)
    caps = commands.add_parser('capabilities')
    caps.add_argument('--backend', default='codex')
    for mode in ('delegate', 'retrieve', 'relay'):
        command = commands.add_parser(mode)
        command.add_argument('--cwd', required=True)
        command.add_argument('--backend', default='codex')
        command.add_argument('--model', help='Explicit executor model; omission uses Codex config.')
        command.add_argument('--effort', choices=['minimal', 'low', 'medium', 'high', 'xhigh', 'max', 'ultra'])
        if mode == 'retrieve':
            command.set_defaults(allow_writes=False)
        else:
            command.add_argument('--allow-writes', action='store_true')
        add_message(command)
        command.add_argument('--timeout', type=positive_timeout, default=600)
    send = commands.add_parser('send')
    send.add_argument('session_id')
    send.add_argument('--raw', action='store_true', help='Relay final bytes only; errors go to stderr.')
    add_message(send)
    send.add_argument('--timeout', type=positive_timeout, default=600)
    terminal = commands.add_parser('chat')
    terminal.add_argument('session_id')
    terminal.add_argument('--timeout', type=positive_timeout, default=600)
    for name in ('show', 'recover'):
        commands.add_parser(name).add_argument('session_id')
    commands.add_parser('sessions')
    return root


def add_message(command):
    group = command.add_mutually_exclusive_group()
    group.add_argument('--message', help='Short prompt. Prefer stdin/files for sensitive or multiline text.')
    group.add_argument('--message-file', help='UTF-8 request file. Without either option, read stdin.')


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.command == 'discover':
            emit(discover(args.root, args.depth, args.limit))
        elif args.command == 'capabilities':
            emit({'backend': args.backend, 'capabilities': adapter_for(args.backend).capabilities})
        elif args.command in ('delegate', 'retrieve', 'relay'):
            return start(args)
        elif args.command == 'send':
            if args.raw and Store(args.state_dir).get(args.session_id)['mode'] != 'relay':
                raise ValueError('--raw requires a relay session.')
            return continue_turn(args)
        elif args.command == 'chat':
            return chat(args)
        elif args.command == 'recover':
            return recover(args)
        elif args.command == 'show':
            emit(Store(args.state_dir).get(args.session_id))
        elif args.command == 'sessions':
            emit(Store(args.state_dir).records())
        return 0
    except KeyboardInterrupt:
        print('Interrupted.', file=sys.stderr)
        return 130
    except (OSError, ValueError, RuntimeError) as exc:
        print(json.dumps({'status': 'error', 'error': str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
