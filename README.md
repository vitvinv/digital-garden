# Digital Garden ⚘

This is my art project (work in progress). Each garden is a sticker placed in a public space. Anyone can scan this sticker with a phone camera and see a 3D garden inside it, that grows as days are passing by. I am also planning to add a feature to "water" this garden to speed up its growth or perhaps support its life.

**Live:** https://garden.v-e-v.org/

The engine of this garden is a 1997 PlantStudio by Cynthia F. Kurtz and Paul D. Fernhout. I have used a coding agent to update the code and make it work both in headless mode (for growth simulation on server) and as a Blender addon (for plant arrangement)

The AR is built with 8th Wall.

## What it is

- **WebAR viewer** (`digital-garden-AR/`) — point your camera at the garden
  sticker image target (MindAR) and a virtual plant grows in place.
- **Daily growth pipeline** — the garden advances every day (`grow.yml`),
  and each push to `main` regenerates the per-day plant GLBs
  (`scripts/plant_glb.py`) and redeploys the site (`.github/workflows/deploy.yml`).

## Repository layout

| Path | What |
|---|---|
| `digital-garden-AR/` | WebAR app (webpack build, MindAR image tracking, postfx). Docs: `digital-garden-AR/README.md` |
| `scripts/` | Headless plant → GLB regenerator + compare/audit tooling. Docs: `scripts/README.md` |
| `plantstudio_blender/` | Pure-Python core + plant data used by the growth pipeline and CI tests (Blender-UI parts live in the full addon) |
| `.github/workflows/` | `deploy.yml` (Pages deploy), `grow.yml` (daily growth), `test-addon.yml` (core tests) |
| `AGENTS.md` | Commit rules for AI agents working in this repo |

## Growth model

- One config per plant: `digital-garden-AR/src/assets/plants/<plant_id>.json`
  with `species`, `seed`, and strict ISO `planted_date` (e.g. `2026-06-08`).
- `plant_id` = `lowercase(species)_<seed>`, e.g. `daylily_280`.
- The plant's shape corresponds to `age = today − planted_date` at every deploy.
- The Blender addon's **export with metadata** button authors these configs
  (`planted_date = today − age`), never hand-typed.

## The addon

The growth simulation comes from the
[**PlantStudio Blender addon**](https://github.com/vitvinv/plantstudio-blender)
(63 species, deterministic seeds, GLB export, animation; Blender 4.2 + 5.x).

## Development

- GLB regeneration: `python scripts/plant_glb.py [--day YYYY-MM-DD] [--no-compress]`
- Core tests: `python -m pytest plantstudio_blender/tests/`
- AR app dev: see `digital-garden-AR/README.md`
