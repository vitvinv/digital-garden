"""
Headless plant GLB regenerator (PlantStudio core + headless Blender decimation).

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
                                [--no-decimate] [--blender PATH]

Decimation is done by a headless Blender instance running
scripts/blender_decimate.py (Decimate modifier, COLLAPSE mode). If no Blender
binary is found, the script falls back to the pure-Python QEM decimator so the
pipeline keeps working in CI.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
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
BLENDER_SCRIPT = ROOT / "scripts" / "blender_decimate.py"

# Headless Blender Decimate modifier settings.
DECIMATE_MODE = "COLLAPSE"
DECIMATE_RATIO = 0.2

# Common places Blender installs; overridable via BLENDER_EXE or --blender.
BLENDER_CANDIDATES = [
    str(Path.home() / "Documents" / "stable" / "blender-5.2.1-lts.9e2066aef7ef" / "blender.exe"),
    str(Path.home() / "Documents" / "stable" / "blender-4.5.13-lts.daeeeca98fb0" / "blender.exe"),
    "/usr/bin/blender",
    "/usr/local/bin/blender",
]


def find_blender(explicit=None):
    """Resolve the Blender executable for headless decimation."""
    if explicit:
        return explicit if Path(explicit).exists() else None
    env = os.environ.get("BLENDER_EXE")
    if env and Path(env).exists():
        return env
    for candidate in BLENDER_CANDIDATES:
        if Path(candidate).exists():
            return candidate
    return shutil.which("blender")


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


def run_blender_decimate(blender_path, vertices, faces, ratio=DECIMATE_RATIO,
                         mode=DECIMATE_MODE):
    """Decimate a mesh by shelling out to a headless Blender instance.

    Returns {"vertices": [...], "faces": [...]} for the decimated mesh.
    Raises subprocess.CalledProcessError if Blender fails.
    """
    with tempfile.TemporaryDirectory(prefix="plant_decimate_") as tmp:
        tmp_dir = Path(tmp)
        in_path = tmp_dir / "mesh_in.json"
        out_path = tmp_dir / "mesh_out.json"
        in_path.write_text(json.dumps(
            {"vertices": [list(v) for v in vertices],
             "faces": [list(f) for f in faces]}), encoding="utf-8")
        cmd = [
            blender_path, "--background", "--factory-startup",
            "--python", str(BLENDER_SCRIPT), "--",
            str(in_path), str(out_path), "--ratio", str(ratio),
            "--mode", mode,
        ]
        subprocess.run(cmd, check=True, capture_output=True, text=True,
                       timeout=600)
        return json.loads(out_path.read_text(encoding="utf-8"))


def rebake_face_colors(orig_verts, orig_faces, orig_colors, new_verts,
                       new_faces):
    """Color each decimated face from its nearest original face centroid.

    Blender's Decimate modifier merges vertices, so exact per-face color
    mapping is lost. For each new face we take the color of the original face
    whose centroid is nearest — deterministic, palette-preserving, and keeps
    the exploded-per-face-color output convention of this pipeline.
    """
    ov = np.asarray(orig_verts, dtype=np.float64)
    nv = np.asarray(new_verts, dtype=np.float64)
    orig_centroids = ov[np.asarray(orig_faces, dtype=np.int64)].mean(axis=1)
    new_centroids = nv[np.asarray(new_faces, dtype=np.int64)].mean(axis=1)

    colors = np.zeros((len(new_centroids), 3), dtype=np.int64)
    chunk = 64
    for start in range(0, len(new_centroids), chunk):
        block = new_centroids[start:start + chunk]
        dist2 = ((block[:, None, :] - orig_centroids[None, :, :]) ** 2).sum(axis=2)
        nearest = np.argmin(dist2, axis=1)
        colors[start:start + chunk] = np.asarray(orig_colors, dtype=np.int64)[nearest]
    return [tuple(int(c) for c in row) for row in colors]


def decimate_data(data, blender_path=None):
    """Decimate a {vertices, faces, face_colors} mesh dict.

    Prefers a headless Blender instance (Decimate modifier, COLLAPSE ratio
    0.2); falls back to the pure-Python QEM decimator when no Blender binary
    is available so CI stays green.
    """
    if blender_path:
        decimated = run_blender_decimate(blender_path, data["vertices"],
                                         data["faces"])
        data = dict(data)
        data["face_colors"] = rebake_face_colors(
            data["vertices"], data["faces"], data["face_colors"],
            decimated["vertices"], decimated["faces"])
        data["vertices"] = decimated["vertices"]
        data["faces"] = decimated["faces"]
        return data
    return simplify_mesh(data["vertices"], data["faces"], data["face_colors"],
                         DECIMATE_RATIO)


def regenerate_plant(config, plants_dir, day_override=None, compress=True,
                     decimate=True, lib=None, tdo_lib=None, blender_path=None):
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
        data = decimate_data(data, blender_path=blender_path)
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
    parser.add_argument("--blender", type=str, default=None,
                        help="Path to the Blender executable used for "
                             "decimation (default: BLENDER_EXE, common install "
                             "paths, or blender on PATH)")
    args = parser.parse_args()

    blender_path = find_blender(args.blender)
    if not args.no_decimate and blender_path:
        print(f"Decimator: headless Blender ({Path(blender_path).name}), "
              f"mode {DECIMATE_MODE}, ratio {DECIMATE_RATIO}")
    elif not args.no_decimate:
        print("WARNING: no Blender binary found; decimation falls back to the "
              "pure-Python QEM decimator")

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
                             lib=lib, tdo_lib=tdo_lib,
                             blender_path=blender_path)
        except Exception as e:
            failed += 1
            print(f"  [{config_path.name}] ERROR: {e}")

    print(f"\n=== DONE === {len(configs) - failed}/{len(configs)} plants regenerated")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
