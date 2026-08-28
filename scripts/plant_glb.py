"""
Headless plant GLB regenerator (PlantStudio core, no Blender).

Reads per-plant JSON configs from `digital-garden-AR/src/assets/plants/*.json`,
grows each plant deterministically at `day = today - planted_date` using the
pure-Python PlantStudio core (plantstudio_blender/core), and writes one GLB per
plant to `digital-garden-AR/src/assets/plants/{plant_id}.glb`.

Per-plant JSON schema:
    {
      "plant_id": "daylily_280",
      "species": "Daylily",            # must match the core species library
      "seed": 280,
      "planted_date": "2026-06-08"     # strict ISO YYYY-MM-DD; day = today - planted_date
    }

Configs are authored by the Blender addon's "export with metadata" button,
which always writes strict ISO dates. Hand-typed DMY/ambiguous dates are
rejected by design.

Output matches the Blender addon's export conventions:
  - MeshTurtle scale 0.001 (mm -> meters)
  - orient_vertices() from scene_bridge (PlantStudio +X growth -> Blender Z-up)
  - Blender Z-up -> glTF Y-up conversion (same as Blender's native exporter)
  - per-face colors baked into exploded vertex colors (COLOR_0)
  - Draco compression via `gltf-transform draco` when available

Usage:
    python scripts/plant_glb.py [--plants-dir DIR] [--day YYYY-MM-DD] [--no-compress]
                                [--no-decimate]
"""

import argparse
import json
import shutil
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np
import trimesh

from plantstudio_blender.core.factory import grow_species
from plantstudio_blender.core.plant_library import SpeciesLibrary
from plantstudio_blender.core.mesh_buffer import MeshBuffer
from plantstudio_blender.core.turtle import MeshTurtle
from plantstudio_blender.core.draw import draw_plant
from plantstudio_blender.core.tdo_parser import TdoLibrary
from plantstudio_blender.core.decimate import simplify_mesh

DATA_DIR = ROOT / "plantstudio_blender" / "data"
DEFAULT_PLANTS_DIR = ROOT / "digital-garden-AR" / "src" / "assets" / "plants"

# Hard-coded per decision; change here to pick a different reduction.
DECIMATE_RATIO = 0.5


def orient_vertices(vertices):
    """PlantStudio grows along +X; Blender's up is +Z (see scene_bridge)."""
    return [(-z, y, x) for (x, y, z) in vertices]


def to_gltf_vertices(vertices):
    """Blender Z-up -> glTF Y-up, matching Blender's native glTF exporter."""
    return [(x, z, -y) for (x, y, z) in orient_vertices(vertices)]


def compute_day_n(planted_date_str, today=None):
    if today is None:
        today = date.today()
    planted = datetime.strptime(planted_date_str, "%Y-%m-%d").date()
    return max(0, (today - planted).days)


def build_trimesh(data):
    """Convert {vertices, faces, face_colors} into a vertex-colored mesh.

    Face colors (PlantStudio 0-255 RGB) are baked into exploded per-vertex
    colors so every triangle keeps its exact color in any renderer.
    """
    verts = to_gltf_vertices(data["vertices"])
    faces = data["faces"]
    colors = data["face_colors"]

    exploded_verts = []
    exploded_faces = []
    exploded_colors = []
    for face, color in zip(faces, colors):
        base = len(exploded_verts)
        exploded_verts.append(verts[face[0]])
        exploded_verts.append(verts[face[1]])
        exploded_verts.append(verts[face[2]])
        exploded_colors.extend([(color[0], color[1], color[2], 255)] * 3)
        exploded_faces.append([base, base + 1, base + 2])

    mesh = trimesh.Trimesh(
        vertices=np.asarray(exploded_verts, dtype=np.float32),
        faces=np.asarray(exploded_faces, dtype=np.int32),
        process=False,
    )
    mesh.visual = trimesh.visual.ColorVisuals(
        mesh, vertex_colors=np.asarray(exploded_colors, dtype=np.uint8))
    return mesh


def run_draco_compression(src, dst):
    """Run gltf-transform draco on a GLB file. Returns True on success."""
    draco_cmd = shutil.which("gltf-transform")
    if not draco_cmd:
        print(f"  [{src.name}] gltf-transform not found, skipping Draco")
        return False
    try:
        subprocess.run(
            [draco_cmd, "draco", str(src), str(dst)],
            check=True, capture_output=True, text=True, timeout=120,
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(f"  [{src.name}] Draco compression failed: {e}")
        return False


def regenerate_plant(config, plants_dir, day_override=None, compress=True,
                     decimate=True, lib=None, tdo_lib=None):
    plant_id = config.get("plant_id")
    species_name = config.get("species")
    seed = config.get("seed", 0)
    planted_date = config.get("planted_date")

    if not plant_id or not species_name or not planted_date:
        raise ValueError(f"plant config missing plant_id/species/planted_date: {config}")

    try:
        day_n = compute_day_n(planted_date, day_override)
    except ValueError as e:
        raise ValueError(f"[{plant_id}] planted_date '{planted_date}' must be "
                         f"strict ISO YYYY-MM-DD: {e}") from e
    species = lib.get(species_name)
    if species is None:
        raise ValueError(f"unknown species '{species_name}' (library has "
                         f"{len(lib)} species)")

    plant = grow_species(species, day_n, seed=seed, tdo_library=tdo_lib)
    buffer = MeshBuffer()
    turtle = MeshTurtle(buffer)
    turtle.setScale_pixelsPerMm(0.001)  # mm -> meters (same as scene_bridge)
    draw_plant(plant, turtle)

    verts, faces = buffer.stats()
    if faces == 0:
        print(f"  [{plant_id}] ({species_name}): day {day_n} - EMPTY mesh, "
              f"skipping (existing GLB kept)")
        return None

    data = buffer.to_mesh_data()
    full_faces = len(data["faces"])
    if decimate:
        data = simplify_mesh(data["vertices"], data["faces"],
                             data["face_colors"], DECIMATE_RATIO)
    lod_faces = len(data["faces"])
    mesh = build_trimesh(data)

    out_path = plants_dir / f"{plant_id}.glb"
    temp_path = plants_dir / f"{plant_id}.tmp.glb"
    mesh.export(file_obj=str(temp_path), file_type="glb")

    if compress and run_draco_compression(temp_path, out_path):
        temp_path.unlink(missing_ok=True)
    else:
        shutil.move(str(temp_path), str(out_path))

    bounds = mesh.bounds
    size_kb = out_path.stat().st_size / 1024
    if decimate:
        face_stats = f"{full_faces}f -> {lod_faces}f (ratio {DECIMATE_RATIO})"
    else:
        face_stats = f"{full_faces}f"
    print(f"  [{plant_id}] ({species_name}): day {day_n}, {verts}v/{face_stats}, "
          f"bounds y {bounds[0][1]:.2f}..{bounds[1][1]:.2f}m, {size_kb:.0f} KB")
    return out_path


def main():
    parser = argparse.ArgumentParser(description="Regenerate plant GLBs headlessly.")
    parser.add_argument("--plants-dir", type=str, default=str(DEFAULT_PLANTS_DIR),
                        help="Directory containing plant JSON configs")
    parser.add_argument("--day", type=str, default=None,
                        help="Override 'today' as YYYY-MM-DD (for determinism tests)")
    parser.add_argument("--no-compress", action="store_true",
                        help="Skip Draco compression")
    parser.add_argument("--no-decimate", action="store_true",
                        help="Export full-detail meshes (skip decimation)")
    args = parser.parse_args()

    plants_dir = Path(args.plants_dir)
    if not plants_dir.is_dir():
        print(f"ERROR: plants dir not found at {plants_dir}")
        sys.exit(1)

    day_override = date.fromisoformat(args.day) if args.day else None
    today = day_override or date.today()

    lib = SpeciesLibrary(str(DATA_DIR))
    tdo_lib = TdoLibrary.from_file(str(DATA_DIR / "3D object library.tdo"))

    configs = sorted(plants_dir.glob("*.json"))
    if not configs:
        print(f"No plant configs found in {plants_dir}")
        return

    print(f"=== plant_glb.py === {today.isoformat()}")
    print(f"Plants: {len(configs)} (library: {len(lib)} species)")

    failed = 0
    for config_path in configs:
        with open(config_path, "r") as f:
            config = json.load(f)
        try:
            regenerate_plant(config, plants_dir, day_override=day_override,
                             compress=not args.no_compress,
                             decimate=not args.no_decimate,
                             lib=lib, tdo_lib=tdo_lib)
        except Exception as e:
            failed += 1
            print(f"  [{config_path.name}] ERROR: {e}")

    print(f"\n=== DONE === {len(configs) - failed}/{len(configs)} plants regenerated")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
