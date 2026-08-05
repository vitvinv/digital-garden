"""
Grow script — reads growth-config.json, calls generate() per plant,
composites all plants of a garden into a single {garden-slug}.glb,
applies Draco compression, writes to src/assets/gardens/.

Usage:
    python scripts/grow.py [--config growth-config.json]
"""

import sys
import os
import json
import subprocess
import shutil
from datetime import date, datetime
from pathlib import Path

import numpy as np
import trimesh

from species import SPECIES, growth_scale
from generate import generate, DeterministicRNG

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = ROOT / "growth-config.json"
GARDENS_DIR = ROOT / "digital-garden-AR" / "src" / "assets" / "gardens"


def load_config(path):
    with open(path, "r") as f:
        cfg = json.load(f)
    if "gardens" not in cfg:
        raise ValueError("Config must have a 'gardens' key")
    return cfg


def compute_day_n(planted_date_str, today=None):
    if today is None:
        today = date.today()
    planted = datetime.strptime(planted_date_str, "%Y-%m-%d").date()
    return max(0, (today - planted).days)


def compute_neighbor_state(plant, all_plants_in_garden):
    """Calculate canopy overlap with other plants in the same garden.
    
    Uses each plant's current-day canopy radius (scaled by growth curve),
    not the full mature radius.
    """
    if len(all_plants_in_garden) <= 1:
        return None

    def _current_canopy(p):
        species_name = p.get("species", "fern")
        params = SPECIES.get(species_name)
        day_n = compute_day_n(p.get("planted_date", "2000-01-01"))
        scale = growth_scale(params, day_n)
        override = p.get("canopy_radius")
        base = params.get_canopy_radius(override if override is not None else None)
        return base * scale

    pos = np.array(plant.get("position", [0, 0, 0]), dtype=np.float64)
    my_radius = _current_canopy(plant)

    total_overlap = 0.0
    neighbor_count = 0

    for other in all_plants_in_garden:
        if other is plant:
            continue
        other_pos = np.array(other.get("position", [0, 0, 0]), dtype=np.float64)
        other_radius = _current_canopy(other)

        # Distance in XZ plane (ignore Y — canopy is a horizontal disc projection)
        dist = np.linalg.norm((pos - other_pos) * np.array([1, 0, 1]))
        combined = my_radius + other_radius

        if dist < combined and min(my_radius, other_radius) > 0:
            overlap = (combined - dist) / min(my_radius, other_radius)
            total_overlap += min(overlap, 1.0)
            neighbor_count += 1

    total_overlap = min(total_overlap, 1.0)
    if neighbor_count == 0:
        return None

    return {"total_overlap": total_overlap, "neighbor_count": neighbor_count}


def composite_garden_garden(garden_slug, garden_cfg):
    """
    Generate all plants for one garden, composite into a single GLB.
    Returns (trimesh.Scene, day_n_values).
    """
    plants = garden_cfg.get("plants", [])
    if not plants:
        print(f"  [{garden_slug}] WARNING: no plants defined, skipping.")
        return None, []

    scene = trimesh.Scene()
    day_n_values = []

    for plant in plants:
        slot = plant.get("plant_slot", "unknown")
        species_name = plant.get("species", "fern")
        seed = plant.get("seed", 0)
        planted_date = plant.get("planted_date")
        position = plant.get("position", [0.0, 0.0, 0.0])
        mutation_strength = plant.get("mutation_strength", 0.0)

        if not planted_date:
            print(f"  [{garden_slug}] {slot}: SKIP — no planted_date")
            continue

        day_n = compute_day_n(planted_date)
        day_n_values.append(day_n)

        neighbor_state = compute_neighbor_state(plant, plants)
        overrides = plant.get("overrides")

        result = generate(species_name, seed, day_n, neighbor_state, overrides)
        mesh = result["mesh"]
        verts = result["vertices"]
        faces = result["faces"]
        height = result["height"]

        if verts == 0:
            print(f"  [{garden_slug}] {slot} ({species_name}): day {day_n} — EMPTY, skipping")
            continue

        # Apply position offset
        transform = trimesh.transformations.translation_matrix(position)
        mesh.apply_transform(transform)

        node_name = f"{garden_slug}-{slot}"
        scene.add_geometry(mesh, node_name=node_name,
                          geom_name=node_name,
                          transform=transform)

        print(f"  [{garden_slug}] {slot} ({species_name}): day {day_n}, "
              f"height {height:.2f}m, {verts}v/{faces}f")

    return scene, day_n_values


def export_garden_glb(garden_slug, scene, compress=True):
    """Write the composite garden scene to a GLB file."""
    GARDENS_DIR.mkdir(parents=True, exist_ok=True)

    out_path = GARDENS_DIR / f"{garden_slug}.glb"
    temp_path = GARDENS_DIR / f"{garden_slug}.tmp.glb"

    scene.export(file_obj=str(temp_path), file_type="glb")

    if compress:
        compressed = run_draco_compression(str(temp_path), str(out_path))
        if not compressed:
            shutil.move(str(temp_path), str(out_path))
        else:
            temp_path.unlink(missing_ok=True)
    else:
        shutil.move(str(temp_path), str(out_path))

    size_kb = out_path.stat().st_size / 1024
    print(f"  [{garden_slug}] -> {out_path.name} ({size_kb:.0f} KB)")
    return out_path


def run_draco_compression(src, dst):
    """Run gltf-transform draco on a GLB file. Returns True on success."""
    draco_cmd = shutil.which("gltf-transform")
    if not draco_cmd:
        print(f"  [{src}] gltf-transform not found, skipping Draco compression")
        return False
    try:
        subprocess.run(
            [draco_cmd, "draco", src, dst],
            check=True,
            capture_output=True,
            text=True,
            timeout=60,
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(f"  [{src}] Draco compression failed: {e}")
        return False


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Grow all digital garden plants.")
    parser.add_argument("--config", type=str, default=str(DEFAULT_CONFIG),
                       help="Path to growth-config.json")
    parser.add_argument("--no-compress", action="store_true",
                       help="Skip Draco compression")
    args = parser.parse_args()

    config_path = Path(args.config)
    if not config_path.exists():
        print(f"ERROR: config not found at {config_path}")
        sys.exit(1)

    cfg = load_config(config_path)
    gardens = cfg["gardens"]
    today = date.today()

    print(f"=== grow.py === {today.isoformat()}")
    print(f"Gardens: {len(gardens)}")

    total_updated = 0
    for garden_slug, garden_cfg in gardens.items():
        print(f"\n--- {garden_slug} ---")
        scene, day_n_values = composite_garden_garden(garden_slug, garden_cfg)

        if scene is None:
            continue

        export_garden_glb(garden_slug, scene,
                         compress=not args.no_compress)
        total_updated += 1

    print(f"\n=== DONE === {total_updated} garden(s) updated")


if __name__ == "__main__":
    main()
