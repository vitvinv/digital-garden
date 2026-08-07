# Digital Garden — Implementation Plan

## Architecture Decision (Phase 0 outcome)

**PlantGL is not available** on conda-forge or PyPI. It exists only as a C++ source repository (github.com/openalea/plantgl) requiring manual compilation with Qt/OpenGL dependencies — impossible to install in a GitHub Actions runner without building from source.

**Decision:** The procedural plant generator uses **trimesh** (pure Python, pip-installable) for all mesh construction. The `generate()` pure function produces deterministic meshes using trimesh primitives (cylinders, quad faces) assembled into species-specific plant architectures. This is simpler, faster in CI, and has zero external C++ dependencies.

## Repository Structure (actual)

```
digital-garden/                             # Git repo root
├── .github/workflows/
│   ├── deploy.yml                          # Build 8th Wall project + deploy to GitHub Pages
│   └── grow.yml                            # Daily cron: grow plants + publish
├── digital-garden-AR/                      # 8th Wall Studio project (existing, webpack)
│   ├── src/
│   │   ├── assets/
│   │   │   └── gardens/                    # Generated: {garden-slug}.glb per garden
│   │   ├── .expanse.json                   # Scene graph — human-edited
│   │   └── app.js
│   └── package.json
├── growth-config.json                      # Source of truth (human-written)
├── scripts/
│   ├── requirements.txt                    # numpy, trimesh
│   ├── generate.py                         # Deterministic plant mesh generator
│   ├── species.py                          # 3 species: fern, succulent, shrub
│   ├── grow.py                             # Reads config, generates, composites, writes GLBs
│   └── publish.sh                          # git add GLBs, commit, push
└── tests/
    ├── test_generate.py                    # 68 tests
    └── test_grow.py                        # 10 tests
```

## Conventions

- **GLB naming:** `{garden-slug}.glb` — one file per garden, all plants composited
- **Asset path:** `digital-garden-AR/src/assets/gardens/{garden-slug}.glb`
- **Growth is deterministic:** `generate(species, seed, day_n, neighbor_state) -> dict`
- Same `seed + day_n` always reproduces identical vertex data
- No stateful/incremental mutation — always regenerate from scratch
- **Neighbor interaction:** canopy radius scaled by current-day growth, overlap → discount up to 90%
- **Draco compression:** via `gltf-transform draco` CLI in CI

## What's built and working

| Phase | Status | Details |
|-------|--------|---------|
| **Phase 0** | **FAILED** — adapted | PlantGL not installable in CI. Switched to trimesh-based generator. |
| **Phase 1** | Complete | `generate.py` + `species.py`: 3 species, S-curve growth, deterministic PRNG |
| **Phase 2** | Complete | `grow.py`: reads config, composites gardens, writes GLBs + Draco |
| **Phase 3** | Complete | `publish.sh`: git add/commit/push, triggers deploy |
| **Phase 4** | Pending | Manual E2E test — human places gltfModel in `.expanse.json`, runs pipeline |
| **Phase 5** | Complete | `grow.yml`: daily cron + workflow_dispatch, pip-only, no conda |
| **Phase 6** | Complete | Neighbor overlap discount in `compute_neighbor_state()`, current-day canopy scaling |
| **Phase 7** | Deferred | Watering mechanic |

## CI workflow (grow.yml)

```
Daily at 06:00 UTC (or manual dispatch)
  → checkout (LFS) on hosted ubuntu runner (git-lfs available, no container)
  → pip install numpy trimesh (scripts/requirements.txt)
  → npm install -g @gltf-transform/cli (Draco)
  → python scripts/grow.py
  → bash scripts/publish.sh      # commit + push
  → deploy.yml triggers           # webpack build + Pages deploy
```

> Note: `grow.py` only needs numpy + trimesh (no PlantGL). The `ghcr.io/vitvinv/digital-garden-plantgl` container approach was abandoned — it lacked git-lfs and every scheduled run failed at checkout.

## Verified

- **78/78 tests pass** (`pytest tests/`)
- `grow.py` produces valid composite GLBs (multi-mesh, multi-plant garden)
- Determinism: byte-identical vertex data on repeated `generate()` calls
- Different seeds → different meshes (genetic diversity)
- Growth: day_90 plant has more vertices than day_7 plant (all species)
- Neighbor overcrowding reduces growth (max 90% discount, 10% floor)

## Deployment status (verified 2026-08-07)

- **GitHub Pages: DONE** — Source: GitHub Actions (`build_type: workflow`)
- **Custom domain: DONE** — `garden.v-e-v.org`, HTTPS enforced, TLS cert approved
- **DNS: DONE** — `garden.v-e-v.org` resolves to GitHub Pages (no Porkbun action needed)
- **Phase 4 E2E: DONE** — `gltfModel` entities present in `.expanse.json` (`assets/daylily.glb`, `assets/gardens/*.glb`), deploy green, live assets return 200 on `garden.v-e-v.org`
- **Daily Garden Growth: fixed** — `grow.yml` rewritten to run on the hosted runner with pip-installed deps (was failing on missing git-lfs inside the PlantGL container)
