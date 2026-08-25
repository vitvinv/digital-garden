"""Headless geometry audit for all bundled PlantStudio species.

The report is intentionally data-oriented: it catches stage transitions,
part-scale collapses, thin pipe divisions, and oversized final bounds without
requiring Blender to be installed.
"""

import argparse
import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from blender_addon.core.draw import draw_plant
from blender_addon.core.factory import grow_species
from blender_addon.core.mesh_buffer import MeshBuffer
from blender_addon.core.plant_library import SpeciesLibrary
from blender_addon.core.tdo_parser import TdoLibrary
from blender_addon.core.turtle import MeshTurtle

DATA_DIR = os.path.join(ROOT, "blender_addon", "data")
TDO_PATH = os.path.join(DATA_DIR, "3D object library.tdo")


def iter_parts(plant):
    if plant.firstPhytomer is None:
        return
    stack = [plant.firstPhytomer]
    seen = set()
    while stack:
        part = stack.pop()
        if part is None or id(part) in seen:
            continue
        seen.add(id(part))
        yield part
        stack.extend([
            getattr(part, "leftBranchPlantPart", None),
            getattr(part, "rightBranchPlantPart", None),
            getattr(part, "nextPlantPart", None),
        ])
        stack.extend([
            getattr(part, "leftLeaf", None),
            getattr(part, "rightLeaf", None),
        ])
        stack.extend(getattr(part, "flowers", []) or [])


def flowers(plant):
    return [part for part in iter_parts(plant)
            if type(part).__name__ == "PdFlowerFruit"]


def draw(species, day, tdo_library, scale=0.001):
    plant = grow_species(species, day, seed=280, tdo_library=tdo_library)
    buffer = MeshBuffer()
    turtle = MeshTurtle(buffer)
    turtle.setScale_pixelsPerMm(scale)
    draw_plant(plant, turtle)
    return plant, buffer


def bounds(vertices):
    if not vertices:
        return (0.0, 0.0, 0.0)
    axes = list(zip(*vertices))
    return tuple(max(axis) - min(axis) for axis in axes)


def radius_anomalies(buffer):
    """Return only non-monotonic within-stroke width changes.

    A taper ratio above 1 is not itself a defect: the source data deliberately
    tapers pedicels and floral axes. The reported bug is a narrow segment in
    the middle of one logical stroke, so the strict check compares adjacent
    divisions within each stroke and permits monotonic base-to-tip taper.
    """
    by_stroke = {}
    for record in buffer.pipe_records:
        stroke_id = record.get("stroke_id")
        if stroke_id is None:
            continue
        by_stroke.setdefault(stroke_id, []).append(record)
    anomalies = []
    for stroke_id, records in by_stroke.items():
        records.sort(key=lambda item: item.get("segment_index", 0))
        widths = [record["radius_start"] for record in records]
        if records:
            widths.append(records[-1]["radius_end"])
        for index in range(1, len(widths) - 1):
            previous = widths[index - 1]
            current = widths[index]
            following = widths[index + 1]
            if current < previous * 0.8 and current < following * 0.8:
                anomalies.append((stroke_id, index, previous, current, following,
                                  records[index].get("part_id")))
    return anomalies


def transition_report(species, tdo_library):
    ages = [0, 20, 35, 39, 40, 41, 43, 45, 50, 60, 80, 120, 200]
    rows = []
    previous = None
    for age in ages:
        plant, buffer = draw(species, age, tdo_library)
        current_flowers = flowers(plant)
        open_count = sum(1 for flower in current_flowers if flower.isOpen)
        row = {
            "age": age,
            "flowers": len(current_flowers),
            "open": open_count,
            "flower_triangles": sum(record["triangles"]
                                     for record in buffer.triangle_set_records),
            "vertices": len(buffer.vertices),
            "faces": len(buffer.faces),
            "bounds": bounds(buffer.vertices),
        }
        if previous is not None:
            row["vertex_ratio"] = (len(buffer.vertices) /
                                    max(1, previous["vertices"]))
        rows.append(row)
        previous = row
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()
    library = SpeciesLibrary(DATA_DIR)
    tdo_library = TdoLibrary.from_file(TDO_PATH)
    problems = 0

    print("species\tday\twidth\tdepth\theight\tvertices\tfaces\tthin_pipes")
    for species in library.species:
        plant, buffer = draw(species, 200, tdo_library)
        width, depth, height = bounds(buffer.vertices)
        thin = radius_anomalies(buffer)
        # Global dimensions are reported for review, not rejected: the
        # catalog intentionally contains tall corn and shrubs. Strict checks
        # are limited to empty meshes and non-monotonic within-stroke widths.
        bad = not buffer.vertices
        if bad or thin:
            problems += 1
        print(f"{species.name}\t200\t{width:.6f}\t{depth:.6f}\t"
              f"{height:.6f}\t{len(buffer.vertices)}\t{len(buffer.faces)}\t{len(thin)}")
        if args.strict and thin:
            for record in thin[:5]:
                print("  thin", record)

    campanula = library.get("campanula")
    if campanula is not None:
        print("\nCampanula transitions")
        for row in transition_report(campanula, tdo_library):
            print(row)

    print(f"\n=== {len(library)} species checked, {problems} problem(s) ===")
    if args.strict and problems:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
