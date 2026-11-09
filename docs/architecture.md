# Architecture and extension contract

## Product modes

Keep these separate from backend transport choices:

1. **Delegate**: the host owns requirements, review and integration. A worker returns a bounded deliverable.
2. **Retrieve**: a worker identifies source locations; local code verifies and reads excerpts; the host retains interpretation and execution.
3. **Relay**: one backend conversation receives successive user turns and returns final replies without model rewriting in the runtime.

Native chat handoff, app-server, and exec are transport/UI choices, not replacements for these three modes.

## Boundaries

```text
User → Host agent / SKILL.md → Python runtime → Adapter → Execution agent
                              ├─ directory candidates
                              ├─ private session state + lock
                              ├─ event / diagnostic / final artifacts
                              └─ local evidence verification
```

The host supplies semantic routing. Bounded directory discovery is deterministic and deliberately does not rank natural-language relevance. It never chooses the wrong cwd merely to avoid a question.

The skill folder is the distributable unit; all runtime modules live under its `scripts/agent_entry`. The root `cli.py`, docs and tests are development conveniences, not runtime dependencies. No permanent global AGENTS.md changes are needed to use the skill.

## Adapter contract

See `adapters.py`: an adapter exposes `name`, explicit `capabilities`, and `run(record, message, artifacts, timeout, schema=None) → Result`.

Input includes an absolute cwd, optional backend thread ID, sandbox policy and explicit model/effort. Result contains a status, backend thread ID, exact final reply bytes, and a diagnostic error. Never return a successful final result solely because the process exited zero. Verify the backend's completion signal and session identity.

A future adapter must describe which capabilities it supports; fail clearly if its runtime cannot enforce a requested read-only policy. Do not silently map all backends to Codex permissions or treat a prompt as an access-control boundary. Do not create a new conversation when resume was requested. CLI flags and authentication stay inside the adapter.

Register a new backend in `adapter_for`, add its capabilities, and test creation, two-turn resume, Unicode/multiline replies, unknown session IDs, cancellation and failure. Schema support is required for the current retrieval pipeline; an adapter lacking it must reject that mode until it has a suitable implementation.

The initial Codex adapter invokes `exec --json` with a final-message file, captures progress separately, and uses `exec resume <exact-id>` for follow-ups. It does not forward interactive approvals. A future app-server adapter should handle bidirectional permission requests, streaming, and cancellation explicitly rather than emulating them with final text.

## State and lifecycle

Each local session has `session.json` and isolated `runs/<run-id>/` artifacts. Saved records contain mode, cwd, sandbox, backend, backend ID, explicit model/effort, status and last-run metrics. The backend retains conversation history; the runtime does not inject the parent transcript automatically.

`created → running → success | failed | timeout | interrupted`

Follow-up turns reuse the record and backend ID. State writes use atomic replacement. A nonblocking OS file lock covers the entire run within a state directory. A crash releases the lock but may leave `running`; explicit `recover` reconstructs the ID from available events without launching anything. It cannot guarantee a detached backend has stopped.

No automatic retry occurs after failures. Local timeout/interruption kills the process group; backend-side persistence and cancellation semantics still depend on the adapter. An interruption can happen after code modifications.

## Performance claims

Track elapsed time, reply bytes and event bytes. Compare the same task/model/settings against a direct agent session before claiming latency or resource improvements. Delegation adds orchestration and extra model work; relay adds a wrapper; retrieval saves parent context only if it returns bounded relevant evidence. Neither the worker nor the host has infinite context. Client rendering lag and service connectivity require separate diagnosis.

## Next increments

- Optional real Codex smoke tests in disposable fixtures, with actual compatibility results.
- A second execution backend to exercise capability differences.
- App-server support for interactive approvals and streamed replies.
- Project registry/routing persistence if real usage shows repeated discovery overhead.
- Measured scheduling/worktree support when concurrent implementation is justified.

Avoid adding a resident daemon, web UI or automatic parallelism before usage demonstrates the need.
