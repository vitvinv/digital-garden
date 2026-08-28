# Agent Memory usage

The `agentmemory` MCP server is available in this workspace. Its tools are prefixed
`memory_*` (e.g. `memory_lesson_save`, `memory_lesson_recall`, `memory_smart_search`,
`memory_recall`).

## Start of each session

Before re-reading project docs, recall what is already stored:

1. `memory_lesson_recall` with a topic query (structure / build / the code being changed).
2. Only re-read files the memory does not cover.

## End of each session

Save durable, non-obvious knowledge with `memory_lesson_save`:

- WHAT TO SAVE: architecture decisions, file layout that took effort to map, known bugs +
  causes, build/run quirks, conventions, anything a future session would rediscover.
- WHAT NOT TO SAVE: trivial commands, one-shot approvals, temp workarounds, file lists,
  routine edits, anything stale within a week.
- Max a few lessons per session. Duplicates auto-strengthen; nothing to clean manually.
- Daemon: `AGENTMEMORY_URL=http://localhost:3111` (autostarts at logon). If the MCP call
  fails, continue the task and don't block on it.