# Evidence retrieval

The host keeps interpretation and decisions. Ask the executor to locate a small number of relevant passages, explain relevance, and identify unresolved questions. It returns a structured list of relative file paths and line ranges; the runtime then reads those files itself to produce exact source excerpts.

```sh
python3 <skill>/scripts/agent-entry.py --state-dir <state> retrieve --cwd <project> --message-file <question.txt>
```

The runtime rejects paths outside the selected root (including escaping symlinks), invalid ranges and binary/oversized sources. It caps findings, excerpt lines and total excerpt bytes. A rejected result is a failed evidence extraction, not proof that no evidence exists. Inspect the error and ask the same executor for corrected references if useful.

Worker summaries are hypotheses; `findings[].excerpt` is read from local source. Paths and line numbers are relative to the worker cwd. Files may change between retrieval and later work: check the supplied SHA-256 before relying on an old excerpt. Do not reimport all explored files into the main chat. Read surrounding source only when the decision requires it.

Retrieval defaults to the same CLI configuration as the executor, unless model/effort was explicitly provided. It does not inherit the host's entire conversation. If no source passages are applicable, accept an empty findings list with the unresolved questions.
