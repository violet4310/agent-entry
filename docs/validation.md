# Validation record

Prototype: 0.1.0. Dates use Asia/Shanghai.

## 2026-11-09 live Codex smoke test

All four read-only turns passed in a generated temporary directory using `codex-cli 0.167.0-alpha.3.2` and the existing ChatGPT login. All four produced `turn.completed` and a final reply.

| Check | Observed result |
| --- | --- |
| Relay, first turn | Created a real Codex thread and returned the requested marker. |
| Relay, second turn | Resumed the same thread ID and recalled the first turn's marker. |
| Retrieve | Returned a structured source reference. Agent Entry read and verified line 2 of `source.txt`. |
| Delegate | Completed a bounded read-only file task and reported the marker. |

The default invocation timed out at 75 seconds. `codex doctor --network-only` reported a reachable HTTPS endpoint, a WebSocket handshake timeout, an existing manual system proxy and disabled system proxy support. The successful run used a temporary executable wrapper passed to `tools/smoke_codex.py --codex-bin`. The wrapper invoked the installed CLI with `--enable respect_system_proxy` for that test process. The separate offline suite passed all 19 cases on this host in 15.6 seconds.

The live test covers read-only delegation and CLI turn continuity. Write-enabled tasks, interactive approvals and performance comparisons remain unverified by this run. The smoke script prints the temporary artifact directory for inspection.

A second run used the same smoke fixture and system proxy with `gpt-6.1-terra` at `low` reasoning effort. All four turns passed. The saved Codex contexts confirm the model and effort for each turn.

| Turn | Sol `low` | Terra `low` |
| --- | ---: | ---: |
| Relay follow-up | 11.0 s | 9.9 s |
| Retrieve | 16.1 s | 18.0 s |
| Read-only delegate | 13.5 s | 30.4 s |

These are single observations from Agent Entry's per-turn elapsed metrics. They do not establish a model latency ranking or measure desktop responsiveness.

## 2026-10-31 offline validation

- Python 3.9.6 on macOS: 19 offline behavioral tests, approximately 20 seconds.
- All three modes, explicit thread resume across CLI invocations, preserved multiline/CRLF input and exact raw final bytes.
- Source excerpt verification, symlink/path escape rejection, line/byte limits.
- Nonzero exit, malformed/incomplete events, missing final reply and thread mismatch handled as failures.
- Timeout terminates the local worker process group; no delayed child fixture output survives.
- State-wide execution lock, explicit host-crash recovery, recursion guard.
- Copying the skill to an unrelated directory remains runnable.
- Installer copies the complete skill and refuses an existing destination.
- Official skill-creator `quick_validate.py`: `Skill is valid!` (PyYAML installed only in a temporary validation directory).
- Python syntax compilation with a temporary cache directory.
- Installed `codex-cli 0.166.0-alpha.5.1` accepts the adapter's global exec options before the resume subcommand in its help/parser check.

## 2026-10-31 live Codex attempt

A read-only test in a generated temporary fixture reached real Codex `thread.started` and `turn.started` events. The model request timed out; the wrapper terminated it after 45 seconds and saved the backend thread ID and diagnostics. No final reply was received. The later resume/retrieval/delegation checks were not run, because the smoke test stops at the first failure.

This verifies actual process startup and initial event parsing, but **does not verify a completed live round trip, real resume, model-generated structured retrieval, sandbox enforcement, or write-enabled tasks**. Offline simulation must not be described as a substitute for those checks. No speed-up claim is supported by this test.

Initial restricted-host execution could not initialize Codex's local database. The live attempt used approved host execution; this is why the skill documents that nested CLI permission boundaries must be checked independently.

No user project contents or authentication credentials were added to this repository. Live diagnostic artifacts remain in the generated temporary location printed by the smoke test.
