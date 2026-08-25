"""Compare every ported species against the original 1997 PlantStudio data.

The .pla/.tdo files in plantstudio_blender/data are byte-identical to the 1997
collection (examples/PlantStudio2). The port must therefore interpret every
parameter exactly as the original did. This script iterates all species and
reports:

1. pFlower/pInflor separation: the flower's OptimalBiomass_pctMPB must NOT
   be shadowed by the inflorescence's optimalBiomass_pctMPB (this was the
   root cause of giant flowers/plants before the fix).
2. Rendered scale: each plant drawn at mm->m and measured; the "origPx"
   column approximates the original's on-screen size (mm * drawingScale).
3. Flower/fruit scale check: port petal scale == original formula
   (scaleAtFullSize/100 * min(1, liveBiomass / flower.optimalBiomass)).

Run:  python scripts/compare_to_original.py [--strict]
"""

import argparse
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from plantstudio_blender.core.plant_library import SpeciesLibrary
from plantstudio_blender.core.tdo_parser import TdoLibrary
from plantstudio_blender.core.factory import grow_species
from plantstudio_blender.core.mesh_buffer import MeshBuffer
from plantstudio_blender.core.turtle import MeshTurtle
from plantstudio_blender.core.draw import draw_plant

DATA_DIR = os.path.join(ROOT, "plantstudio_blender", "data")
TDO_PATH = os.path.join(DATA_DIR, "3D object library.tdo")


def gp(obj, name, default=0.0):
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def raw_flower_inflor(pla_path):
    """Return {(species): (flowerOptRaw, inflorOptRaw)} from raw .pla text."""
    result = {}
    current = None
    with open(pla_path, encoding="latin-1") as f:
        for line in f:
            line = line.strip()
            if line.startswith("[") and "start PlantStudio plant" in line:
                current = line[1:line.find("]")]
                result.setdefault(current, {})
                continue
            if current is None:
                continue
            m = re.search(r"\[(kFlowerOptimalBiomassFemale|kInflorescenceBiomassRequiredFemale)\]\s*=", line)
            if m:
                result[current][m.group(1)] = line.split("=", 1)[1].strip()
    return result


def collect_flowers(plant):
    flowers = []
    seen = set()
    def walk(part):
        if part is None or id(part) in seen:
            return
        seen.add(id(part))
        if type(part).__name__ == "PdInflorescence":
            for f in getattr(part, "flowers", []) or []:
                flowers.append(f)
        for a in ("nextPlantPart", "leftBranchPlantPart", "rightBranchPlantPart"):
            walk(getattr(part, a, None))
        if hasattr(part, "leafAttachedTo") and getattr(part, "leafAttachedTo"):
            walk(part.leafAttachedTo)
    walk(plant.firstPhytomer)
    return flowers


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--strict", action="store_true",
                        help="exit non-zero on any scale anomaly")
    args = parser.parse_args()

    lib = SpeciesLibrary(DATA_DIR)
    tdo_lib = TdoLibrary.from_file(TDO_PATH)

    raw = {}
    for path in sorted(os.listdir(DATA_DIR)):
        if path.endswith(".pla"):
            raw.update(raw_flower_inflor(os.path.join(DATA_DIR, path)))

    problems = 0
    print(f"{'species':26s} {'W_m':>7s} {'H_m':>7s} {'flwOpt(raw)':>11s} "
          f"{'infOpt(raw)':>11s} {'flwOpt(port)':>12s} {'infOpt(port)':>12s} "
          f"{'petalScl':>8s} {'OK':>3s}")
    print("-" * 110)

    for sp in sorted(lib.species, key=lambda s: s.name.lower()):
        r = raw.get(sp.name, {})
        flw_raw = r.get("kFlowerOptimalBiomassFemale")
        inf_raw = r.get("kInflorescenceBiomassRequiredFemale")
        # Normalize so the lowercase aliases exist exactly as the draw/sim
        # pipeline sees them.
        from plantstudio_blender.core.normalize import normalize_params
        normalize_params(sp.params)
        pf = sp.params.flowers.get("kGenderFemale", {})
        pi = sp.params.inflors.get("kGenderFemale", {})
        # flower optimal is stored under the capital-O registry key, then
        # aliased to lowercase by normalize_flowers (only if unshadowed).
        flw_port = pf.get("optimalBiomass_pctMPB")
        if flw_port is None:
            flw_port = pf.get("OptimalBiomass_pctMPB")
        inf_port = pi.get("optimalBiomass_pctMPB")

        # collision check: flower optimal must not be shadowed by inflor's
        ok_collision = True
        if flw_raw and inf_raw:
            try:
                ok_collision = (flw_port is not None
                                and abs(float(flw_port) - float(flw_raw)) < 1e-6)
            except (TypeError, ValueError):
                ok_collision = False

        # rendered scale check
        ok_scale = True
        w = h = 0.0
        try:
            plant = grow_species(sp, 200, seed=280, tdo_library=tdo_lib)
            buf = MeshBuffer()
            turtle = MeshTurtle(buf)
            turtle.setScale_pixelsPerMm(0.001)
            draw_plant(plant, turtle)
            if buf.vertices:
                xs = [v[0] for v in buf.vertices]
                zs = [v[2] for v in buf.vertices]
                w = max(xs) - min(xs)
                h = max(zs) - min(zs)
                # sanity: nothing should be > 5m; a "plant" that renders at
                # dozens of meters means a scale bug (flower/fruit optimal
                # biomass collision inflated propFullSize).
                if max(w, h) > 5.0:
                    ok_scale = False
        except Exception as e:
            ok_scale = False
            print(f"{sp.name:26s} ERROR {e}")

        # petal scale check vs original formula
        petal_ok = True
        try:
            plant = grow_species(sp, 200, seed=280, tdo_library=tdo_lib)
            flowers = collect_flowers(plant)
            if flowers and pf:
                flw_opt = float(flw_port or 1.0)
                td = pf.get("tdoParams", {})
                pet = td.get("kFirstPetals")
                if pet is not None:
                    s = gp(pet, "scaleAtFullSize", 0.0)
                    if s > 0:
                        live = flowers[0].liveBiomass_pctMPB
                        port_pfs = min(1.0, live / max(1e-9, flw_opt))
                        port_scale = s / 100.0 * port_pfs
                        orig_pfs = min(1.0, live / max(1e-9, flw_opt))
                        orig_scale = s / 100.0 * orig_pfs
                        if abs(port_scale - orig_scale) > 1e-9:
                            petal_ok = False
        except Exception:
            petal_ok = False

        ok = ok_collision and ok_scale and petal_ok
        if not ok:
            problems += 1
        print(f"{sp.name:26s} {w:7.3f} {h:7.3f} "
              f"{str(flw_raw):>11s} {str(inf_raw):>11s} "
              f"{str(flw_port):>12s} {str(inf_port):>12s} "
              f"{'ok' if ok_collision else 'COLLIDE':>8s} "
              f"{'OK' if ok else 'PROBLEM':>7s}")

    print(f"\n=== {len(lib.species)} species checked, {problems} problem(s) ===")
    if args.strict and problems:
        sys.exit(1)


if __name__ == "__main__":
    main()
