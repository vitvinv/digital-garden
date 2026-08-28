# Plan: Split the PlantStudio Blender addon into its own repo

**Status:** Approved (Aug 25, 2026)

## Goal

Create a separate GitHub repo for the PlantStudio Blender addon so you can push addon changes to both repos from VS Code with one button:

- **`vitvinv/plantstudio-blender`** (new) — the **full** addon, including the Blender GUI bridge (`animator.py`, `operators.py`, `scene_bridge.py`, `ui_panel.py`, `wizard.py`). This is where day-to-day editing happens.
- **`vitvinv/digital-garden`** (existing) — keeps only the **headless** subset in `plantstudio_blender/` (`__init__.py`, `blender_manifest.toml`, `core/`, `data/`, `tests/`, `tools/`), matching the original `.gitignore` intent ("keep the Blender-only UI files local"). Used by the CI growth script.

## Architecture

- The addon lives in a `plantstudio_blender/` **subfolder** inside the new repo (same relative layout as digital-garden), so imports and tests are identical in both repos and the sync is a plain folder copy.
- The new repo root holds: `README.md`, `LICENSE` (GPL-3.0, matches the manifest), `.gitignore`, `scripts/sync_addon.py`, `.vscode/tasks.json`, `.github/workflows/test.yml`.
- **One button = VS Code Task** (Ctrl+Shift+B in the addon repo) running `scripts/sync_addon.py`, which:
  1. pushes the addon repo,
  2. copies the headless subset into the sibling `digital-garden` clone,
  3. commits and pushes digital-garden.

> The SCM push button cannot split different content between two repos — it pushes the whole repo to every remote — so a Task is the one-click mechanism.

## Pre-requisite: main is currently broken

The rename commit `17fa8a6` renamed `blender_addon/` → `plantstudio_blender/` but left `blender_addon` imports behind. `pytest plantstudio_blender/tests/` fails today, and the CI growth script (`scripts/plant_glb.py`) would fail too. Fixes required:

1. `blender_addon.` → `plantstudio_blender.` imports in:
   - `plantstudio_blender/tests/test_core.py`, `test_mesh_output.py`, `test_simulation.py`
   - `plantstudio_blender/tools/compare_campanula.py`, `validate_pla.py`
   - `scripts/audit_geometry.py`, `audit_lifecycle.py`, `compare_to_original.py`, `plant_glb.py`
2. Tests point `DATA_DIR` at `examples/PlantStudio-master/for-olpc-python/` (60 files); repoint to the addon's own `plantstudio_blender/data/` (14 files, verified overlapping) so tests are self-contained in both repos. Verify with pytest.

## Phase 1 — digital-garden: make the headless split real

1. `.gitignore`: replace `!plantstudio_blender/*.py` with `!plantstudio_blender/__init__.py` so the 5 UI bridge files are no longer tracked.
2. `git rm --cached` the 5 UI files and delete them from the working tree (they move to the new repo).
3. Apply the import + `DATA_DIR` fixes above; run `pytest` → green.
4. Commit and push digital-garden.

## Phase 2 — create the standalone repo

1. Create empty `vitvinv/plantstudio-blender` on GitHub (or use `gh` if authenticated).
2. Clone it locally as a sibling of digital-garden.
3. Copy the full addon (all 49 files, including the UI bridge) into `plantstudio_blender/`; apply the same import/`DATA_DIR` fixes.
4. Add root files: `README.md`, `LICENSE` (GPL-3.0), `.gitignore` (`__pycache__/`, `*.pyc`, `*.zip`), `.github/workflows/test.yml` (pytest on push).
5. Run pytest → green; commit; add remote; push.

## Phase 3 — one-button sync

1. `scripts/sync_addon.py` in the new repo:
   - `git push origin main` (addon repo).
   - Copy headless subset (`__init__.py`, `blender_manifest.toml`, `core/`, `data/`, `tests/`, `tools/`, delete-synced) into `../digital-garden/plantstudio_blender/`.
   - In digital-garden: `git add`, commit `chore(addon): sync headless subset from plantstudio-blender @ <sha>`, push.
   - Python (not rsync) so it works on Windows; sibling-path default with a `--dg` override.
2. `.vscode/tasks.json` (new repo): default build task → `python scripts/sync_addon.py`, bound to Ctrl+Shift+B.
3. Dry-run the full flow end to end and confirm both repos are updated.

## Notes / optional

- **Auto-sync Action** (later upgrade): a workflow in `plantstudio-blender` that pushes the headless subset to digital-garden on every push — needs a PAT secret with write access to digital-garden.
- `plantstudio_blender.zip` is currently tracked in digital-garden; it's a build artifact of the full addon — optionally untrack it there and generate it from the addon repo instead.
- Rule of thumb afterward: hand-edit the addon only in the new repo; digital-garden's `plantstudio_blender/` is a generated mirror.
