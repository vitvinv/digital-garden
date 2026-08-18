# scripts — headless plant GLB regenerator

`plant_glb.py` grows every plant from its JSON config at `day = today − planted_date`
and writes a Draco-compressed GLB. It runs on **every push to `main`** in
`.github/workflows/deploy.yml`, right before the webpack build, so the deployed
GLB is always current for today's date.

## Config format

One file per plant in `digital-garden-AR/src/assets/plants/`:

```json
{
  "plant_id": "daylily_280",
  "species": "Daylily",
  "seed": 280,
  "planted_date": "2026-06-08"
}
```

`planted_date` is **strict ISO `YYYY-MM-DD`** — no tolerant/ambiguous parsing.
DMY values like `2026-15-08` fail the build on purpose. Dates are authored
automatically by the Blender addon's **"export with metadata"** button
(`planted_date = today − age`), never hand-typed.

## Workflow

1. Blender → Plants list → tick the plants to include
2. Set **Age (days)** per plant in the wizard
3. **export with metadata** → writes `{plant_id}.json` per checked plant
   (`plant_id = lowercase {species}_{seed}`, e.g. `daylily_280`)
4. Commit + push → `deploy.yml` regenerates GLBs (`plant_glb.py`) and builds
   the site (cache-busting appends `?v=<8-char sha>` to each plant GLB URL)

Duplicate `plant_id`s (same species+seed in two checked plants) are skipped
with a warning by the addon, and the build never overwrites silently.

## Usage

```
python scripts/plant_glb.py [--plants-dir DIR] [--day YYYY-MM-DD] [--no-compress]
```

- `--day` overrides "today" for deterministic reproduction/CI tests
- `--no-compress` skips the Draco pass (useful when `gltf-transform` is absent)
- exits non-zero if any config fails (bad date, unknown species, empty mesh)