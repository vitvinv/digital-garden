"""Catalog-wide flower/fruit lifecycle audit.

The scan separates lifecycle state from rendered detail. It catches flowers
that simplify while still open, fruit rendered before a flower's state changes,
and non-monotonic per-flower stage transitions. It uses the same headless mesh
path as the addon and does not require Blender.
"""

import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from blender_addon.core.draw import (
    draw_plant,
    kExportPartFlower,
    kExportPartFruit,
)
from blender_addon.core.factory import create_plant, grow_species
from blender_addon.core.mesh_buffer import MeshBuffer
from blender_addon.core.plant_library import SpeciesLibrary
from blender_addon.core.tdo_parser import TdoLibrary
from blender_addon.core.turtle import MeshTurtle

DATA_DIR = os.path.join(ROOT, "blender_addon", "data")
TDO_PATH = os.path.join(DATA_DIR, "3D object library.tdo")
STAGE_ORDER = {"bud": 0, "open": 1, "unripe_fruit": 2, "ripe_fruit": 3}


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
            getattr(part, "leftLeaf", None),
            getattr(part, "rightLeaf", None),
        ])
        stack.extend(getattr(part, "flowers", []) or [])


def iter_flowers(plant):
    return [part for part in iter_parts(plant)
            if type(part).__name__ == "PdFlowerFruit"]


def flowering_species(species):
    params = species.params
    general = params.pGeneral
    return bool(
        int(getattr(general, "numApicalInflors",
                    getattr(general, "NumApicalInflors", 0)) or 0)
        or int(getattr(general, "numAxillaryInflors",
                       getattr(general, "NumAxillaryInflors", 0)) or 0)
    )


def state_snapshot(plant):
    current = iter_flowers(plant)
    counts = {stage: 0 for stage in STAGE_ORDER}
    for flower in current:
        counts[getattr(flower, "stage", "bud")] += 1
    return {
        "flowers": len(current),
        "bud": counts["bud"],
        "open": counts["open"],
        "unripe_fruit": counts["unripe_fruit"],
        "ripe_fruit": counts["ripe_fruit"],
        "flower_ids": {id(flower): getattr(flower, "stage", "bud")
                       for flower in current},
    }


def simulate_lifecycle(species, max_day):
    plant = create_plant(species, seed=280)
    snapshots = {0: state_snapshot(plant)}
    histories = {}
    for flower in iter_flowers(plant):
        histories[id(flower)] = [getattr(flower, "stage", "bud")]
    for _ in range(max_day):
        plant.nextDay()
        snapshot = state_snapshot(plant)
        snapshots[plant.age] = snapshot
        for flower in iter_flowers(plant):
            histories.setdefault(id(flower), []).append(
                getattr(flower, "stage", "bud"))
    return snapshots, histories


def render_snapshot(species, day, tdo_library):
    plant = grow_species(species, day, seed=280, tdo_library=tdo_library)
    buffer = MeshBuffer()
    turtle = MeshTurtle(buffer)
    turtle.setScale_pixelsPerMm(0.001)
    draw_plant(plant, turtle)
    flower_records = [record for record in buffer.triangle_set_records
                      if record.get("part_id") == kExportPartFlower]
    open_flower_records = [record for record in flower_records
                           if record.get("lifecycle_stage") == "open"]
    fruit_records = [record for record in buffer.triangle_set_records
                     if record.get("part_id") == kExportPartFruit]
    return {
        "day": day,
        "plant": plant,
        "buffer": buffer,
        "flowers": iter_flowers(plant),
        "flower_records": flower_records,
        "fruit_records": fruit_records,
        "flower_triangles": sum(r["triangles"] for r in flower_records),
        "open_flower_triangles": sum(r["triangles"]
                                      for r in open_flower_records),
        "fruit_triangles": sum(r["triangles"] for r in fruit_records),
        "flower_scales": [r["scale"] for r in flower_records],
        "fruit_scales": [r["scale"] for r in fruit_records],
    }


def first_day(snapshots, predicate, max_day):
    for day in range(max_day + 1):
        if predicate(snapshots[day]):
            return day
    return None


def lifecycle_flags(snapshots, histories, renders, max_day):
    flags = []
    first_open = first_day(snapshots, lambda s: s["open"] > 0, max_day)
    first_fruit = first_day(
        snapshots,
        lambda s: s["unripe_fruit"] + s["ripe_fruit"] > 0,
        max_day,
    )
    if first_fruit is not None and not any(
            snapshots[day]["open"] > 0 for day in range(first_fruit)):
        flags.append("fruit_without_open_stage")

    for flower_id, stages in histories.items():
        previous = -1
        for stage in stages:
            current = STAGE_ORDER.get(stage, -1)
            if current < previous:
                flags.append("per_flower_stage_regressed")
                break
            previous = current

    open_renders = [render for render in renders
                    if render["flowers"] and any(
                        getattr(flower, "stage", "bud") == "open"
                        for flower in render["flowers"])]
    for previous, current in zip(open_renders, open_renders[1:]):
        previous_open = sum(
            getattr(flower, "stage", "bud") == "open"
            for flower in previous["flowers"])
        current_open = sum(
            getattr(flower, "stage", "bud") == "open"
            for flower in current["flowers"])
        if previous_open <= 0 or current_open <= 0:
            continue
        previous_per_open = previous["open_flower_triangles"] / previous_open
        current_per_open = current["open_flower_triangles"] / current_open
        if previous_per_open >= 20 and current_per_open < previous_per_open * 0.5:
            flags.append(
                f"open_flower_detail_collapse:{previous['day']}->"
                f"{current['day']}:{previous_per_open:.1f}->{current_per_open:.1f}"
            )
            break
        if current["open_flower_triangles"] == 0:
            flags.append(f"open_flower_not_rendered:{current['day']}")
            break

    if first_open is not None:
        first_render = next((r for r in renders if r["day"] == first_open), None)
        if first_render is not None and first_render["open_flower_triangles"] == 0:
            flags.append(f"open_flower_not_rendered:{first_open}")

    return first_open, first_fruit, sorted(set(flags))


def evidence_days(snapshots, max_day):
    """Choose lifecycle checkpoints instead of rendering every simulated day."""
    days = {0, max_day}
    signatures = {}
    for day, snapshot in snapshots.items():
        signature = (snapshot["bud"], snapshot["open"],
                     snapshot["unripe_fruit"], snapshot["ripe_fruit"])
        if signature != signatures.get("previous"):
            days.add(day)
            signatures["previous"] = signature
    open_days = [day for day, snapshot in snapshots.items()
                 if snapshot["open"] > 0]
    fruit_days = [day for day, snapshot in snapshots.items()
                  if snapshot["unripe_fruit"] + snapshot["ripe_fruit"] > 0]
    for candidates in (open_days, fruit_days):
        if not candidates:
            continue
        first = candidates[0]
        last = candidates[-1]
        days.update({first, min(max_day, first + 1), min(max_day, first + 5),
                     min(max_day, first + 10), last})
        days.update(candidates[::10])
    return sorted(day for day in days if 0 <= day <= max_day)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-day", type=int, default=200)
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()
    if args.max_day < 1:
        parser.error("--max-day must be positive")

    library = SpeciesLibrary(DATA_DIR)
    tdo_library = TdoLibrary.from_file(TDO_PATH)
    lifecycle_count = 0
    problem_count = 0
    print("species\tfirst_open\tfirst_fruit\topen_peak_tris\tfruit_peak_tris\tflags")
    for species in library.species:
        if not flowering_species(species):
            continue
        lifecycle_count += 1
        try:
            snapshots, histories = simulate_lifecycle(species, args.max_day)
            render_days = evidence_days(snapshots, args.max_day)
            renders = [render_snapshot(species, day, tdo_library)
                       for day in render_days]
            first_open, first_fruit, flags = lifecycle_flags(
                snapshots, histories, renders, args.max_day)
            open_peak = max((r["flower_triangles"] for r in renders), default=0)
            fruit_peak = max((r["fruit_triangles"] for r in renders), default=0)
        except Exception as error:
            first_open = first_fruit = "error"
            open_peak = fruit_peak = 0
            flags = [f"scan_error:{type(error).__name__}:{error}"]
        if flags:
            problem_count += 1
        print(f"{species.name}\t{first_open}\t{first_fruit}\t{open_peak}\t"
              f"{fruit_peak}\t{','.join(flags) if flags else 'none'}")

    print(f"\n=== {lifecycle_count} flowering species checked, "
          f"{problem_count} problem(s) ===")
    if args.strict and problem_count:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
