# Digital Garden — Implementation Plan

## Repository Structure

```
digital-garden/
├── digital-garden-AR/                    # 8th Wall Studio project (existing, webpack)
│   ├── .github/workflows/
│   │   ├── deploy.yml                    # Existing: build + deploy to GitHub Pages on push
│   │   ├── plantgl-test.yml              # Phase 0: PlantGL CI verification (workflow_dispatch)
│   │   └── grow.yml                      # Phase 5: daily grow + publish schedule
│   ├── src/
│   │   ├── assets/
│   │   │   ├── gardens/                  # NEW: per-garden GLB files
│   │   │   │   ├── {garden-slug}.glb     # Single GLB per garden — all plants composited
│   │   │   │   └── ...
│   │   │   ├── playing-cards/            # Existing
│   │   │   └── ...
│   │   ├── .expanse.json                 # Scene graph — human-edited, one gltfModel per garden
│   │   └── app.js                        # Image target registration
│   ├── image-targets/                    # Existing
│   └── ...
├── growth-config.json                    # NEW: single source of truth (human-written)
├── scripts/                              # NEW: automation
│   ├── requirements.txt                  # Python dependencies (conda + pip)
│   ├── generate.py                       # generate(species, seed, day_n, neighbor_state) -> trimesh.Trimesh
│   ├── species.py                        # Species parameter definitions
│   ├── grow.py                           # Reads config, calls generate per plant, composites into garden GLB
│   └── publish.sh                        # git add GLBs, commit, push to main
└── tests/                                # NEW
    ├── test_generate.py                  # Determinism + species tests
    ├── test_grow.py                      # Config parsing + day_n computation
    └── test_neighbor.py                  # Canopy overlap tests (Phase 6)
```

## Resolved Design Decisions

| Question | Decision |
|----------|----------|
| PlantGL CI install | **conda** (`conda install -c conda-forge openalea.plantgl`) — precompiled binaries, more reliable than pip from-source compilation |
| Initial species | `"fern"`, `"succulent"`, `"shrub"` |
| GLB compression | **Draco** from the start, via `@gltf-transform/cli` npm package |
| Plant positioning | Human arranges in GUI once; position lives in PlantGL composition. `position` in config is documentary (for neighbor overlap calc) — it's a 2D position in XZ plane, Y up, relative to image target origin. `canopy_radius` defaults per species, overridable in config |
| Image target binding | Each garden's `image_target` field binds it to exactly one sticker; all plants in that garden render on that same sticker. The config value must match `imageTarget.name` in `.expanse.json` |
| Multi-plant per garden | **Yes.** All plants in a garden are composited into a single `{garden-slug}.glb` by `grow.py`. Each plant is a separate mesh node at its `position` within the GLB scene. The AR scene loads one GLB per garden target |

## Conventions (locked)

- **GLB naming:** `{garden-slug}.glb` — one file per garden, all plants composited
- **Asset path:** `src/assets/gardens/{garden-slug}.glb`
- **`.expanse.json` reference:** `assets/gardens/{garden-slug}.glb`
- **`growth-config.json`** is the only source of truth; written by hand per planting
- Never modify `.expanse.json`, `app.js`, or any file under `digital-garden-AR/` except GLB assets the Grow script targets
- **Growth is a deterministic pure function:** `generate(species, seed, day_n, neighbor_state) -> dict` (positioned mesh data)
- Same `seed + day_n` always reproduces the same mesh
- No stateful/incremental mutation — always regenerate from scratch at target `day_n`
- **Single GLB per garden:** `grow.py` generates each plant individually via `generate()`, then composites all into one `{garden-slug}.glb` with each plant at its configured position. The AR scene has one `gltfModel` entity per garden target

---

## Phase 0: PlantGL CI Verification (HARD GATE)

**Goal:** Confirm PlantGL can export valid glTF/GLB headlessly on a GitHub Actions `ubuntu-latest` runner.

### Tasks

1. Create `scripts/requirements.txt` with PlantGL and mesh-processing dependencies
2. Create `scripts/generate.py` — minimal stub: imports PlantGL, creates a simple mesh (unit cube or sphere), exports as `.glb` binary
3. Create `.github/workflows/plantgl-test.yml` — `workflow_dispatch` workflow that:
   - Checks out repo
   - Sets up Miniconda (conda-incubator/setup-miniconda)
   - Installs `openalea.plantgl` from conda-forge, plus `trimesh`, `numpy`
   - Runs `generate.py` with hardcoded test params
   - Validates output GLB with `gltf-validator` (npm `@gltf-transform/cli`)
   - Applies Draco compression via `gltf-transform draco`
   - Uploads the resulting GLB as a workflow artifact
4. If PlantGL needs an OpenGL context: test `xvfb-run` wrapper. If that fails, test `osmesa`/`egl` backend (via `libosmesa6` apt package or `pyrender` with `osmesa`). Document the working incantation
5. Open the exported GLB in a glTF viewer to confirm visually correct

### Files touched

| File | Action |
|------|--------|
| `scripts/requirements.txt` | New |
| `scripts/generate.py` | New (stub, rewritten in Phase 1) |
| `.github/workflows/plantgl-test.yml` | New |

### Definition of Done

- [ ] `plantgl-test.yml` workflow runs green on `workflow_dispatch`
- [ ] PlantGL imports without error on `ubuntu-latest`
- [ ] Output GLB passes `gltf-validator` with zero errors
- [ ] Draco-compressed GLB loads in desktop glTF viewer
- [ ] No display/server/X11 errors in CI logs
- [ ] Working CI incantation documented (xvfb? osmesa? nothing needed?)

### Fallback if Phase 0 fails

If PlantGL cannot run headlessly on GitHub Actions:
- Shift to **local-only regeneration**: developer runs `grow.py` on their machine periodically, commits manually
- Or: containerize with software GPU on self-hosted runner
- Or: swap PlantGL for a pure-Python L-system + mesh builder (e.g., `lpy` + `trimesh`)

---

## Phase 1: Deterministic Growth Function

**Goal:** Implement per-plant mesh generation as a pure function. `generate(species, seed, day_n, neighbor_state) -> dict` where dict contains mesh data and metadata.

### Tasks

1. Define species parameters in `species.py`:
   - `name`, `default_canopy_radius`, `max_height`
   - Growth curve: S-curve mapping `day_n → scale_factor` (params: midpoint day, steepness, max)
   - Procedural params: `branching_angle`, `branching_depth`, `leaf_density`, `trunk_taper`
   - Species: `"fern"`, `"succulent"`, `"shrub"`
2. Implement deterministic PRNG seeded from `(seed * 31 + day_n * 7) % MOD` — same inputs always produce same random sequence
3. Build PlantGL procedural plant graph from species params, scaled by growth curve at `day_n`
4. Tessellate plant graph → `trimesh.Trimesh` object
5. Return `{"mesh": trimesh.Trimesh, "height": float, "canopy_radius": float}` — caller handles GLB export and Draco compression
6. Apply `neighbor_state` discount: `effective_day_n = day_n * max(0.1, 1.0 - total_overlap)` (stubbed until Phase 6)
7. Unit tests:
   - `test_generate_deterministic`: same args → byte-identical mesh vertex data across 3 runs
   - `test_generate_divergent`: different seeds → different meshes
   - `test_generate_growth`: day_30 > day_7 in vertex count / bounding box

### Files touched

| File | Action |
|------|--------|
| `scripts/generate.py` | Rewrite from Phase 0 stub |
| `scripts/species.py` | New |
| `tests/test_generate.py` | New |

### Definition of Done

- [ ] `generate("fern", 42, 30, None)` produces byte-identical vertex data on repeated calls
- [ ] `generate("fern", 42, 30, None)` != `generate("fern", 43, 30, None)` (different seed)
- [ ] `generate("fern", 42, 30, None)` visibly larger than `generate("fern", 42, 7, None)` (growth)
- [ ] All unit tests pass

---

## Phase 2: Grow Script (Garden Compositing)

**Goal:** `scripts/grow.py` — reads `growth-config.json`, calls `generate()` per plant, composites all plants into one `{garden-slug}.glb` per garden, writes to `src/assets/gardens/`.

### Tasks

1. Define `growth-config.json` schema (write empty example; human fills real entries)
2. Parse config; for each plant, compute `day_n = max(0, (today - planted_date).days)`
3. For each plant: call `generate()`, get mesh + metadata
4. Per garden: create a glTF scene, place each plant mesh at its `position` offset
5. Export single GLB: `src/assets/gardens/{garden-slug}.glb`
6. Apply Draco compression via `gltf-transform draco` CLI on the combined GLB
7. Auto-create `src/assets/gardens/` directory if missing
8. Print summary: `[{garden-slug}] {count} plants → {size}KB (grown to day {max_day_n})`
9. Unit tests:
   - `test_day_n_computation`: verify date math
   - `test_idempotent`: run twice, second run overwrites with identical bytes
   - `test_missing_dir`: auto-creates directory

### Files touched

| File | Action |
|------|--------|
| `growth-config.json` | New (empty example — human fills real entries) |
| `scripts/grow.py` | New |
| `tests/test_grow.py` | New |

### `growth-config.json` schema

```json
{
  "gardens": {
    "{garden-slug}": {
      "image_target": "20_Element_Fire",
      "plants": [
        {
          "plant_slot": "plant-0",
          "species": "fern",
          "seed": 42,
          "planted_date": "2025-06-15",
          "mutation_strength": 0.0,
          "position": [0.0, 0.0, 0.0],
          "canopy_radius": null
        }
      ]
    }
  }
}
```

- `position`: [x, y, z] in image-target-local space (XZ ground plane, Y up). Used to offset mesh in combined GLB; also used in Phase 6 for neighbor overlap.
- `canopy_radius`: `null` means use species default. Override to set manually.
- `mutation_strength`: reserved for future genetic drift; currently 0.0.
- The `image_target` field binds all plants in this garden to that sticker. Human must ensure it matches the `imageTarget.name` in `.expanse.json`.

### Definition of Done

- [ ] `python scripts/grow.py` run twice → identical output GLB bytes
- [ ] Multi-plant garden: GLB contains N mesh nodes at correct positions
- [ ] Missing directories auto-created
- [ ] Graceful errors for unknown species, invalid dates, missing keys
- [ ] All unit tests pass

---

## Phase 3: Publish Script

**Goal:** `scripts/publish.sh` — commits changed GLB files and pushes to main. The existing `deploy.yml` triggers on push and handles the webpack build + GitHub Pages deploy.

### Tasks

1. `git add digital-garden-AR/src/assets/gardens/*.glb`
2. If no staged changes: exit 0
3. If changes: `git commit -m "grow: day {day_n} — {count} garden(s) updated"`
4. `git push origin main`
5. Configure git author as `github-actions[bot]`
6. Handle push conflict: `git pull --rebase` and retry once

### Files touched

| File | Action |
|------|--------|
| `scripts/publish.sh` | New |

### Definition of Done

- [ ] No-op when no GLBs changed (no empty commits)
- [ ] Push triggers `deploy.yml` workflow
- [ ] Commit message includes day number and garden count
- [ ] Handles push conflict gracefully

---

## Phase 4: Single-Garden End-to-End Test

**Goal:** Manual end-to-end walkthrough with one garden, one plant, one real image target.

### Tasks (performed by a human, documented in plan)

1. Pick an existing image target (e.g., `20_Element_Fire`) or create a new one
2. In `.expanse.json`, add a `gltfModel` entity under the image target, pointing to `assets/gardens/{test-garden-slug}.glb`
3. Write `growth-config.json` with one garden, one plant:
   ```json
   {
     "gardens": {
       "{test-garden-slug}": {
         "image_target": "20_Element_Fire",
         "plants": [
           {
             "plant_slot": "plant-0",
             "species": "fern",
             "seed": 42,
             "planted_date": "2025-07-01",
             "mutation_strength": 0.0,
             "position": [0.0, 0.0, 0.0],
             "canopy_radius": null
           }
         ]
       }
     }
   }
   ```
4. Run `python scripts/grow.py` — verify `src/assets/gardens/{test-garden-slug}.glb` created
5. Run `cd digital-garden-AR && npm run build` — verify GLB copied to `dist/assets/gardens/`
6. Run `cd digital-garden-AR && npm run serve` — scan target with phone, verify plant renders in AR
7. Run `scripts/publish.sh` — verify commit appears, Pages deploys

### Definition of Done

- [ ] Plant renders in AR when image target is scanned
- [ ] Changing `planted_date` earlier → re-run grow → larger plant (verifies growth)
- [ ] Full pipeline: grow → build → AR → publish → live

---

## Phase 5: GitHub Actions Daily Workflow

**Goal:** `.github/workflows/grow.yml` — scheduled daily cron that runs grow + publish.

### Tasks

1. Create workflow with `schedule: cron(0 6 * * *)` + `workflow_dispatch`
2. Steps:
   - Checkout `main` with `lfs: true`
   - Setup Miniconda (same as Phase 0), install Python deps from `scripts/requirements.txt`
   - Setup Node 20, `npm install -g @gltf-transform/cli` (for Draco)
   - Run `python scripts/grow.py`
   - Configure git, run `bash scripts/publish.sh`
3. Concurrency: `group: daily-grow, cancel-in-progress: false`
4. Permissions: `contents: write`

### Files touched

| File | Action |
|------|--------|
| `.github/workflows/grow.yml` | New |

### Definition of Done

- [ ] `workflow_dispatch` runs green end-to-end
- [ ] Commit appears from `github-actions[bot]`
- [ ] `deploy.yml` auto-triggers and deploys
- [ ] Daily cron runs without manual intervention (3-day monitor)

---

## Phase 6: Neighbor Interaction

**Goal:** Growth discount from canopy overlap with neighbors in the same garden.

### Tasks

1. In `grow.py`, for each plant in a garden, compute neighbor overlap:
   - Use plant `position` (XZ plane) and `canopy_radius` (species default or override)
   - Pairwise overlap: `max(0, (r1 + r2 - distance(p1, p2)) / min(r1, r2))`
   - Total overlap = sum of all pairwise overlaps (capped at 1.0)
2. Pass `neighbor_state = {"total_overlap": float, "neighbor_count": int}` to `generate()`
3. In `generate()`: `effective_day_n = day_n * max(0.1, 1.0 - total_overlap)`
4. Unit tests:
   - Isolated = full growth
   - Two touching = reduced growth
   - Three-way overlap = further reduction

### Files touched

| File | Action |
|------|--------|
| `scripts/grow.py` | Modify: compute neighbor overlap |
| `scripts/generate.py` | Modify: apply neighbor discount |
| `tests/test_neighbor.py` | New |

### Definition of Done

- [ ] Isolated plant larger than crowded plant (same species/seed/day_n)
- [ ] Overlap fraction in [0, 1]
- [ ] Growth never below 10% of normal
- [ ] All neighbor tests pass

---

## Phase 7: Watering (Future — Deferred)

**Goal:** Human "waters" a plant; growth rate boosted for N days after watering.

### Proposed tasks (TBD)

1. Add `last_watered_date` to `growth-config.json`
2. Growth multiplier: `min(2.0, 1.0 + max(0, N - days_since_watered) / N)` where `N = 7`
3. AR UI: "watered" feedback on target scan
4. Watering trigger: target scan (passive), button tap (UI), or separate image target

---

## Risks

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| **PlantGL needs OpenGL on headless CI** | Medium | **Blocker** (Phase 0 gate) | `xvfb-run`, `osmesa`, or `EGL`; fallback to local-only |
| **PlantGL API unfamiliar / poor Python docs** | Medium | Delays Phase 1 | Phase 0 discovers exact API surface early |
| **Repo size from daily binary commits** | Medium | Annoying | LFS enabled; Draco ~50KB/garden; 1GB free tier lasts years |
| **Git LFS bandwidth cap** | Low | Cost | 20 gardens × 50KB × 30 days = 30MB/month (well under 1GB) |
| **Concurrent scheduled CI runs** | Low | Duplicate commits | `concurrency` group |
| **Push fails (remote ahead)** | Low | Missed grow | Retry with `git pull --rebase` |
| **Draco decoder missing in 8th Wall** | Low | GLB won't render | 8th Wall uses Three.js with DRACOLoader built-in |
| **CeCILL-C license** | None | No impact | LGPL-compatible, no open-source obligation |
