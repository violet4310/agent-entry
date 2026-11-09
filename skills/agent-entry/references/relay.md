# Persistent relay

Create one execution session in the selected cwd, then use its local ID for every subsequent user turn. The runtime records the backend thread ID from Codex JSON events and resumes that exact thread. It never selects an unrelated latest session.

```sh
python3 <skill>/scripts/agent-entry.py --state-dir <state> relay --cwd <project> --message-file <request.txt>
python3 <skill>/scripts/agent-entry.py --state-dir <state> send <local-session-id> --message-file <reply.txt> --raw
python3 <skill>/scripts/agent-entry.py --state-dir <state> chat <local-session-id>
```

New-session output is a JSON envelope with `session_id`, `reply`, and artifact paths. `send --raw` writes exactly the executor's final UTF-8 bytes to stdout, without trimming, a prefix, or an extra newline. The terminal `chat` interface uses this path; prompts/status are on stderr. It accepts one line per user turn, `/status` to inspect state and `/quit` to exit. Use `send --message-file` for multiline input.

In a host chat, relay only `reply` without editorial additions when successful. Byte-for-byte identity of the host model's generated answer is not enforceable by a skill; use raw output/terminal chat when strict identity matters. Questions in the final reply go to the user and their answer goes back to the same session. Host UI does not change to a different native chat automatically.

Do not present partial output as a successful reply. Nonzero exit, timeout, interrupted turn, invalid JSON events, missing final message or missing thread ID are explicit failures. Events and stderr remain in artifacts. An interrupted write task may already have edited files; inspect its state before resuming. A failed run with a known backend thread ID can be resumed deliberately using `send`; no automatic retry occurs.

The `exec` backend cannot forward interactive approval controls, native rich media, active-turn steering or mid-turn input. Those require a richer backend/client. Do not invent approval success or promise the same latency as a direct session. Relay keeps intermediate output out of the host transcript, but the executor's own history still grows.
