# AGENTS.md — Agent Rules

This repository is **public**: anything that lands in the git index lands on GitHub.
Local internals (agent memory, agent/IDE workspaces, secrets) are not needed for
this project to function — keep them on disk only, outside git.

## Never commit

- Agent/IDE workspaces: `.freebuff/`, `.kilo/`, `.claude/`, `.cursor/`, `.hermes/`,
  `.agents/`, `.agentmemory/`, `.graphify/`, `.expanse.json`
- Agent memory and local instructions: `MEMORY.md`, local guidance inside `AGENTS.md`
  (references to `AGENTMEMORY_URL`, ports, machine paths, session/lesson dumps)
- Secrets: `.env`, `.env.*`, keys, tokens, passwords, `local_config.py`
- Build artifacts: `*.zip`, `dist/`, `build/`, `node_modules/`
- Local caches and databases: `__pycache__/`, `.pytest_cache/`, `.hypothesis/`, `*.db`, `*.sqlite`
- Vendored copies and drafts with no references from code/scripts (e.g. `examples/PlantStudio-master`)

## Commit workflow

1. Before committing, run `git status` — the index should contain only what is intended.
2. Never use a bare `git add .` / `git add -A` — add explicit paths.
3. If `git status` shows anything from the never-commit list, do not add it — extend `.gitignore`.
4. Keep local agent instructions in `~/.agents/` or files named `*.local.md`, both gitignored.
5. Never rewrite history without an explicit request (no force pushes).

## About this project

Digital garden. Published via GitHub Pages.
- CI: `.github/workflows/deploy.yml` — deploy; `grow.yml` — daily growth;
  `test-addon.yml` — addon core tests.
- Growth uses pure Python: `plantstudio_blender/core/` + `plantstudio_blender/data/`
  (Blender-dependent code is never committed — enforced in `.gitignore`).
- AR viewing: `digital-garden-AR/` (WebAR page over exported GLB).
- Core tests: `pytest` in `plantstudio_blender/tests/`.