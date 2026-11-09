# Delegated execution

The host owns the requirement and final acceptance. Send a bounded deliverable, relevant interfaces, permitted edits, and an observable verification goal. Use a worker only when this saves context or work.

```sh
python3 <skill>/scripts/agent-entry.py --state-dir <state> delegate --cwd <project> --message-file <request.txt> --allow-writes
```

Keep read-only unless the user's task authorizes edits. Inspect the returned files/test report and the actual diff before claiming success. The runtime does not review, merge, or independently verify code changes. Its success status only means the worker turn completed with a final reply.

The current runtime serializes workers within a state directory. Do not simulate parallelism with multiple state directories. For a task crossing modules, define interfaces before splitting implementation. Create worktrees only when actually needed and authorized; new checkouts may omit uncommitted changes and local dependencies.

Follow up with `send <local-session-id> --message-file <feedback.txt>`. Persisted model, effort, cwd, mode and write policy remain in effect. Switching tasks should create a new session; retain a short project-level handoff rather than the whole transcript.
