# AR Garden on garden.v-e-v.org + Restructure to Per-Plant Growth Pipeline

## Context (verified)

- Repo `vitvinv/digital-garden` → GitHub Pages at **https://garden.v-e-v.org/** (`build_type: workflow`, custom domain, HTTPS enforced, cert valid to 2026-10-30). All assets currently return 200, including `assets/daylily.glb`.
- The scene (`digital-garden-AR/src/.expanse.json`) has a "Playing Cards" space (the **default** space per the space-selector) with a `Garden` entity anchored to the **`garden-sticker`** image target, whose child is `daylily.glb`. World camera confirmed (`xrCameraType: "world"`).
- **Bug:** `digital-garden-AR/src/app.js` registers only the 4 element-card targets in `XR8.XrController.configure`. Per the Studio docs (https://8thwall.org/docs/studio/guides/xr/image-targets), every target must be listed there — `garden-sticker` is not, so scanning the sticker shows nothing.
- **Risk:** the scene still references assets that don't exist in the repo: `assets/bmo-bites/cereal.glb`, `assets/bmo-bites/bmo.glb`, `assets/toggle-slam/palm-tree.glb`, `assets/magic-photos/waves.mp4` (removed in commit a031662). May cause startup errors on the phone; the Playing Cards space itself references only existing assets.
- Blender addon (`blender_addon/`, gitignored): the growth engine + mesh drawing live in **`core/` (pure Python, zero bpy)** — `grow_species(species, day, seed, tdo_library)` → `draw_plant(plant, MeshTurtle(MeshBuffer))` → verts/faces/colors. Proven headless by 48 tests. `scene_bridge.py` shows the exact headless recipe: `MeshTurtle` scale `0.001` (mm→m), `orient_vertices()` (rotate −90° about Y), then mesh/GLB export. The addon's "slider" is the `Age (days)` property (`ps_day`).
- The addon has **no GLB export code** (README's `export_glb.py` never existed) — Blender's native exporter is used today.
- `blender_addon/__init__.py` imports bpy only inside `register()`/`unregister()` → `import blender_addon.core` is safe without Blender.
- CI facts: GitHub Actions `Deploy to GitHub Pages` builds `digital-garden-AR` (webpack) on push. `Daily Garden Growth` runs on the hosted runner with pip deps and explicitly dispatches the deploy (`GITHUB_TOKEN` pushes don't trigger workflows — verified). `src/assets/**` and `image-targets/**` are Git LFS.

## Decisions (user-confirmed)

1. **Phase A first:** make the AR scene work on the phone with `daylily.glb`, then build the restructure.
2. **Per-plant JSON model:** each plant = one JSON `{plant_id, species, seed, planted_date}` + one derived GLB. Plants are arranged freely in the Studio editor (`.expanse.json`); the cloud script never touches the scene.
3. **Day model:** `day = today − planted_date`. Never regresses, catches up if a run is missed; the Blender slider maps to `planted_date = today − sliderAge` on export.
4. **Headless generation:** reuse `blender_addon/core` as-is (no rewrite) + a small trimesh GLB writer. No Blender in CI. Fidelity note: GLBs carry vertex colors, not Blender PBR materials (slightly flatter look; acceptable).
5. **Commit `blender_addon/core/` + `data/`** (+ optional `tests/`) to the repo; Blender-only UI files stay gitignored.
6. **Deploy regenerates GLBs pre-build** so the deployed site always has fresh GLBs (stale local pushes can never leak); the **daily cron** regenerates + commits + dispatches deploy (keeps the repo/Studio copy in sync via git pull).

---

## Phase A — Make the AR scene work on the phone with daylily

1. Edit `digital-garden-AR/src/app.js`: add `require('../image-targets/garden-sticker.json')` to the `imageTargetData` array (keep the 4 element targets).
2. Commit + push to `main` (auto-triggers `Deploy to GitHub Pages`). Confirm the run is green and `https://garden.v-e-v.org/bundle.js` returns 200 (grep the deployed bundle for `garden-sticker` as a sanity check).
3. **Phone test (user):**
   - Open `https://garden.v-e-v.org/` in the phone browser (Safari/Chrome); allow camera; the landing page then the "Playing Cards" space loads by default.
   - Print or display `digital-garden-AR/image-targets/garden-sticker_original.png`; point the camera at it → `daylily.glb` should appear on the sticker.
4. **If the app fails to start / black screen:**
   - The stale references to `bmo-bites`, `toggle-slam/palm-tree`, `magic-photos/waves.mp4` are the prime suspect. Strip the scene to only the garden: in the Studio editor delete the "BMO Bites", "Magic Photos", "Toggle SLAM" spaces and the "Space Selector" UI (or remove the corresponding objects in `.expanse.json`), then re-commit.
   - Use phone remote debugging (iOS Safari / Android Chrome) to read console errors and confirm which asset 404s before/after cleanup.

---

## Phase B — Per-plant PlantStudio growth pipeline (cloud, no PC)

### Tasks (ordered)

1. **Un-ignore + commit the PlantStudio core.** Update `.gitignore` to keep `blender_addon/` ignored except:
   ```
   blender_addon/
   !blender_addon/__init__.py
   !blender_addon/core/
   !blender_addon/core/**
   !blender_addon/data/
   !blender_addon/data/**
   !blender_addon/tests/        # optional, to run the 48 headless tests in CI
   !blender_addon/tests/**
   ```
   `blender_addon/data/` holds the species `.pla` libraries (63 species) + `3D object library.tdo` (~2 MB). Commit; run `pytest blender_addon/tests/` in CI (optional but recommended).

2. **Add `scripts/plant_glb.py`** (headless regenerator, mirrors `scene_bridge.py`):
   - Load `SpeciesLibrary` + `TdoLibrary` from the committed `blender_addon/data/`.
   - Read every `digital-garden-AR/src/assets/plants/*.json`.
   - For each plant: `day = (today − planted_date).days`; `grow_species(species, day, seed, tdo_library)`; `MeshBuffer` + `MeshTurtle` (scale `0.001`) + `draw_plant`; `orient_vertices` (same transform as `scene_bridge`); build a `trimesh.Trimesh` with per-face vertex colors; export GLB to `digital-garden-AR/src/assets/plants/{plant_id}.glb` (run `gltf-transform draco` if available, else fall back).
   - Deterministic per (species, seed, day, data); print per-plant summary (day, verts, faces, bytes); exit non-zero on any plant error.
   - Per-plant JSON schema: `{"plant_id": "...", "species": "Daylily", "seed": 280, "planted_date": "2026-08-01"}` — `species` must match the core library names.

3. **Seed the pipeline:** create one plant JSON (e.g. derive from daylily: species `Daylily`, seed `280`, planted_date chosen so the current day ≈ the model's age) and generate its GLB with `plant_glb.py`. Decide whether daylily moves to the per-plant model now or stays a hand-exported GLB (plants without a JSON are left untouched by the script).

4. **Wire GLB regeneration into `deploy.yml`** as a pre-build step before `npm run build`:
   - `actions/setup-python` + `pip install -r scripts/requirements.txt` (numpy, trimesh already listed) + `npm install -g @gltf-transform/cli`; then `python scripts/plant_glb.py`.
   - Effect: every deploy ships current-day GLBs; stale local GLB files never reach the live site.

5. **Point the daily cron (`grow.yml`) at the new script:** replace the `python scripts/grow.py` step with `python scripts/plant_glb.py`; keep checkout(LFS) → pip → gltf-transform → regenerate → publish (commit changed plant GLBs) → dispatch `Deploy to GitHub Pages` (`actions: write` already set). The commit keeps the repo (and a git-pull'd Studio copy) in sync with the latest growth.

6. **Blender-side (local, not committed):** add an "Export Plant Config" operator to the addon that reads the selected plant's `ps_species` / `ps_seed` / `ps_day` and writes `{plant_id, species, seed, planted_date: today − ps_day}` to `digital-garden-AR/src/assets/plants/`. The GUI keeps its WYSIWYG role; the JSON drives CI.

7. **Retire the trimesh pipeline (recommended; reversible/deferrable):** remove `scripts/grow.py`, `scripts/species.py`, `scripts/generate.py`, `scripts/designer.py`, root `growth-config.json`, `tests/test_generate.py`, `tests/test_grow.py`, and the old `src/assets/gardens/*.glb` (they are not referenced by the scene). Alternative: leave them dormant for now.

8. **Docs:** update `IMPLEMENTATION_PLAN.md` to describe the per-plant JSON model, the headless regenerator, and the cron/dispatch flow.

### Validation

- `pytest blender_addon/tests/` (48 headless tests) green in CI; add a few tests for `plant_glb.py` (byte-determinism on same day; day+1 grows mesh size; a new plant JSON produces a new GLB).
- Run `scripts/plant_glb.py` locally: valid GLBs (trimesh loads), byte-stable on repeat runs within the same day.
- Push → deploy builds with fresh GLBs; curl the plant GLB → 200; live bytes match the committed GLB.
- Dispatch `Daily Garden Growth` → GLBs regenerate, publish commits if changed, deploy dispatch succeeds (already proven mechanism).
- Next day: plants are visibly older on the phone (day has advanced by 1).

### Risks / notes

- **Fidelity:** headless GLBs are vertex-colored, not PBR-material Blender exports — flatter look. Fallback if unacceptable: run real Blender `--background` in a CI container reusing `scene_bridge` as-is.
- **Species names** in JSON must match the core library (`Daylily`, `maiden grass`, …); wrong names fail loudly in `plant_glb.py`.
- **Data source:** tests historically read `examples/PlantStudio-master/for-olpc-python`; `plant_glb.py` should consistently use the committed `blender_addon/data/`.
- **LFS:** plant GLBs under `src/assets/**` are LFS-tracked; workflows keep `lfs: true`, and publish step runs `git lfs install`.
- **Missed days** self-correct (planted_date model catches up).
- Phase A may reveal scene cleanups (missing `bmo-bites`/`toggle-slam`/`magic-photos` assets) that should be completed before Phase B polish.
