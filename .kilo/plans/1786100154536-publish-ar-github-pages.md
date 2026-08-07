# Publish AR Experience to GitHub Pages + Fix Daily Growth Pipeline

## Goal

Get the 8th Wall Studio AR experience (with the new Blender `daylily.glb` plant) live on GitHub Pages, openable from a phone, with the daily plant-growth script automatically rebuilding and redeploying it.

## Verified current state (no speculation)

- **GitHub Pages is already live and configured.** Repo `vitvinv/digital-garden`, Pages `build_type: workflow`, custom domain **`garden.v-e-v.org`**, HTTPS enforced, TLS cert approved (expires 2026-10-30). No DNS/Porkbun action needed.
- **Deploy workflow already succeeds** on every push to `main` (latest run `31171757433`, 2026-08-07, green). It builds `digital-garden-AR` with webpack and deploys `dist/` via `actions/deploy-pages`.
- **The live site serves the new Blender plant**: `https://garden.v-e-v.org/` returns 200, and `bundle.js`, `external/runtime/runtime.js`, `assets/daylily.glb`, `assets/gardens/fire-garden.glb` all return 200 with full content.
- **No subpath problem**: built `dist/index.html` uses relative script URLs, and `bundle.js` contains zero absolute-path asset references (asset-loader emits relative paths like `assets/daylily.glb`). `dist/` is gitignored and built only in CI.
- **`daylily.glb` is anchored to the `garden-sticker` image target** in `src/.expanse.json` (Garden → Card → daylily.glb). Phone test requires displaying `digital-garden-AR/image-targets/garden-sticker_original.png`.
- **The 8th Wall Publish dialog (HTML5 / Embed tabs) is not part of this workflow**:
  - The hosted 8th Wall platform was **retired 2026-02-28** (docs: "Publishing", 8thwall.org).
  - **HTML5 tab** → builds/downloads a self-contained `.zip` for manual hosting.
  - **Embed tab** (iframe / full HTML) → embed code for placing a hosted build on another website or a gaming platform (itch.io, Newgrounds, etc.).
  - Not needed here: pushing to GitHub `main` triggers the CI build + Pages deploy automatically. (If embedding is wanted later, the page to embed is `https://garden.v-e-v.org/`.)

## The one broken piece (root cause confirmed)

`Daily Garden Growth` (`grow.yml`) fails **every run**:

```
##[error]Unable to locate executable file: git-lfs.
```

Cause: the job runs inside the `ghcr.io/vitvinv/digital-garden-plantgl` container (a minimal conda/PlantGL image), which does **not** have `git-lfs` installed, so `actions/checkout@v4` with `lfs: true` fails before any step runs. Verified from failed run `31157230228` logs.

Note: `grow.py` imports only `numpy` + `trimesh` (plus stdlib) — PlantGL is not used by the current growth script. The container is unnecessary.

## Decision (user-approved)

Rewrite `grow.yml` to run on the hosted `ubuntu-latest` runner with pip-installed deps (no container). This matches the "pip-only, no conda" decision already documented in `IMPLEMENTATION_PLAN.md`.

## Tasks (ordered)

### 1. Add `scripts/requirements.txt`
Content:
```
numpy
trimesh
```
Enables pip caching in the workflow and matches the path already referenced by `IMPLEMENTATION_PLAN.md`.

### 2. Rewrite `.github/workflows/grow.yml`

```yaml
name: Daily Garden Growth

on:
  schedule:
    - cron: "0 6 * * *"
  workflow_dispatch:

permissions:
  contents: write

concurrency:
  group: daily-grow
  cancel-in-progress: false

env:
  GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}

jobs:
  grow:
    runs-on: ubuntu-latest
    timeout-minutes: 15
    steps:
      - name: Checkout repo
        uses: actions/checkout@v4
        with:
          lfs: true

      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip
          cache-dependency-path: scripts/requirements.txt

      - name: Install Python deps
        run: pip install -r scripts/requirements.txt

      - name: Install gltf-transform (Draco)
        run: npm install -g @gltf-transform/cli

      - name: Run grow script
        run: python scripts/grow.py

      - name: Publish (commit + push)
        run: |
          git lfs install
          bash scripts/publish.sh
```

Key points preserved from the old file: `contents: write` permission, `GITHUB_TOKEN` env (used by `scripts/publish.sh` to set the token remote), `lfs: true` checkout (hosted runners have `git-lfs`), and `git lfs install` before publishing so LFS objects for regenerated `gardens/*.glb` are pushed.

### 3. Optional housekeeping (do if low-risk)
- Delete the **dead nested workflow** `digital-garden-AR/.github/workflows/deploy.yml` — GitHub only reads `.github/workflows/` at the repo root, so it never runs and only causes confusion.
- Remove/replace the now-unused PlantGL container path: `build-docker.yml` + the `container:` reference in the old `grow.yml` (the new `grow.yml` already drops it). Leaving `build-docker.yml` running is harmless but wasteful; preferred: delete it and the PlantGL verification step it runs.
- Update stale claims in `IMPLEMENTATION_PLAN.md` (Phase 0 "PlantGL not available", grow pipeline "container", "scripts/requirements.txt" missing) to reflect the trimesh/pip-only reality.

### 4. Push to `main`
The push triggers `Deploy to GitHub Pages` (sanity check that nothing regressed). Workflow changes alone do not publish — the growth pipeline only runs on schedule/dispatch.

### 5. Verify the growth pipeline end-to-end
- Manually dispatch **Daily Garden Growth** (Actions tab → workflow_dispatch).
- Expect: checkout OK → grow.py regenerates `digital-garden-AR/src/assets/gardens/*.glb` → `publish.sh` commits (`grow: <date> — N garden(s) updated`) and pushes to `main` → `Deploy to GitHub Pages` auto-triggers → Pages updates.
- If GLBs are byte-identical to the committed ones, `publish.sh` exits 0 with no commit and no deploy — expected and correct.

### 6. Validate deployment
- `gh run list` shows both runs green.
- `curl -s -o NUL -w "%{http_code}" https://garden.v-e-v.org/assets/gardens/fire-garden.glb` → 200 (repeat for `water-garden.glb`, `daylily.glb`).

### 7. Phone test
1. Display `digital-garden-AR/image-targets/garden-sticker_original.png` (print or a second device/screen).
2. On the phone browser open **`https://garden.v-e-v.org/`** (HTTPS required for camera).
3. Allow camera access; accept the landing page; point camera at the garden-sticker image.
4. Confirm the `daylily.glb` model and the procedural garden GLBs render.
- Note: this scene is **image-target based** (SLAM), so a target image must be in view. The target list is configured in `src/app.js` + `.expanse.json`.

## Validation summary
- `pytest tests/` (78 tests) still green before/after workflow edits (no Python changes expected).
- `Daily Garden Growth` run green on dispatch.
- Follow-on `Deploy to GitHub Pages` run green.
- Live assets return 200 on `garden.v-e-v.org`.
- Manual AR check on phone against the garden-sticker target.

## Risks / notes
- **Scheduled runs that produce no diff**: publish.sh exits cleanly (no commit → no deploy). Idempotent by design.
- **LFS**: `daylily.glb`, image targets, and `gardens/*.glb` are LFS-tracked (`.gitattributes`). Both workflows must keep `lfs: true`; hosted runners have git-lfs. Explicit `git lfs install` is included before the push.
- **`grow.py` needs only numpy + trimesh** (verified imports). Draco is optional (grow.py falls back gracefully when `gltf-transform` is absent).
- **The Blender `daylily.glb` is static** — `grow.py` only regenerates `gardens/*.glb`. The new plant will not change daily; only the procedural gardens grow. Integrating the Blender plant into daily growth would require adding it as a procedural species in `growth-config.json` — out of scope unless requested.
- **Phone/desktop**: use a recent mobile browser (Safari / Chrome); camera + HTTPS required; no extra 8th Wall app key or domain allow-listing is needed for this self-hosted Studio build.
