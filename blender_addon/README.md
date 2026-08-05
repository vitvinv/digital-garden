# PlantStudio — Blender Addon

A port of **PlantStudio** (Kurtz-Fernhout Software, GPL v3, 1997) as a Blender
addon. It rebuilds PlantStudio's biomass-driven meristem growth simulation,
ships the original species library (63 plants), and produces **real mesh
objects** you can compose into gardens — something the original program
couldn't do.

The PlantStudio authors themselves wished for this: *"We would also love to
see it as, say, a Blender plugin"* — and *"Composition of plants done in other
tools (like Blender)"*.

## Features

- **63 real species** from the original `.pla` libraries (maiden grass, garden
  flowers, wildflowers, shrubs, grassy plants, breeder plants...)
- **Deterministic growth**: same seed + parameters + day = identical plant
  (PlantStudio's Park-Miller RNG, ported exactly)
- **Full biomass simulation**: meristems accumulate photosynthate, create
  phytomers, branch probabilistically, flower and set fruit at maturity
- **Real 3D objects**: the original 57-object `.tdo` library (leaves, petals,
  buds, seeds) drawn via a ported 3D turtle
- **Growth animation**: watch plants grow day by day in the timeline
- **Garden export to GLB**: compose multiple plants in one scene and export a
  single GLB with colors — ready for the digital-garden AR pipeline

## Installation

1. Zip the `blender_addon` folder (the folder that contains `__init__.py`)
   as `plantstudio.zip`
2. Blender → Edit → Preferences → Add-ons → Install → select the zip
3. Enable **"PlantStudio"** in the "Add Mesh" category
4. Open the 3D Viewport → Sidebar (`N`) → **PlantStudio** tab

Works in **Blender 4.2 LTS** and **Blender 5.x LTS**.

## Usage

### Add a plant

1. Pick a **Species** from the dropdown (63 species)
2. Set a **Seed** (deterministic; same seed = same plant) or hit the dice
3. Set **Age (days)**
4. Click **Add Plant** — a mesh object appears at the origin

### Grow

- **Grow To Age**: rebuilds the selected plant at its stored day
- **Step Day**: +1 day
- **Animate Growth**: plays growth frame by frame to maturity

### Compose a garden

- Add several plants; move/rotate/scale them freely in the viewport
- Give the garden a **slug** (e.g. `fire-garden`)
- Optionally set an **Export dir**; otherwise GLB goes to
  `digital-garden-AR/src/assets/gardens/{slug}.glb`
- Click **Export Garden GLB** — writes the GLB **and** a `growth-config.json`
  with the plants (species, seed, day → planted_date, position)

## Architecture

```
blender_addon/
  __init__.py          # Blender addon registration (lazy bpy imports)
  core/                # Pure Python 3, NO Blender — pytest-testable
    rng.py             # Park-Miller RNG (deterministic)
    pla_parser.py      # .pla species file parser
    tdo_parser.py      # .tdo 3D object parser + library
    params.py          # parameter containers
    normalize.py       # fills defaults so any species runs
    plant.py           # growth engine (nextDay, biomass allocation)
    meristem.py        # bud growth, branching, flowering
    internode.py       # stems
    leaf.py            # leaves
    inflorescence.py   # flowers / fruits
    traverser.py       # part-tree walker
    matrix3d.py        # 3D matrices (256-degree turtle units)
    turtle.py          # draws into a mesh buffer
    mesh_buffer.py     # vertices/faces/colors accumulator
    draw.py            # part -> mesh drawing
  scene_bridge.py      # core -> Blender mesh objects + materials
  operators.py         # UI operators
  ui_panel.py          # N-panel
  animator.py          # growth animation
  export_glb.py        # garden GLB + growth-config.json export
  data/                # bundled .pla libraries + 3D object library.tdo
  tests/               # pytest suite (no Blender needed)
```

## Determinism guarantee

The growth simulation is a pure function of `(species, seed, day)`:

```
same species + same seed + same day  ->  byte-identical plant
```

The Park-Miller RNG (ported from `urandom.py`) is pure arithmetic — identical
on every platform. `growth-config.json` stores `species`, `seed`, and
`planted_date`, so the pipeline can always regenerate a plant exactly.

## Tests

```
python -m pytest blender_addon/tests/
```

Runs headless (no Blender) — 27 tests covering RNG determinism, parsers
(63 species + 57 TDOs), the simulation, and mesh output.

## Source material

The original PlantStudio source (GPL v3) lives in
`examples/PlantStudio-master/` (Delphi, Python, Java variants). This addon
ports the algorithm to clean Python 3 and reuses the `.pla`/`.tdo` data as-is.

## License

GPL v3 (matching the original PlantStudio release).
