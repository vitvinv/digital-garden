"""
Phase 0 verification: confirm PlantGL can run headlessly in CI.

This is a standalone script called by .github/workflows/plantgl-test.yml.
It does NOT import generate.py — it tests openalea.plantgl directly.

Success = PlantGL imports, creates geometry, exports mesh data usable by trimesh.
Failure = anything else (missing display, segfault, import error).
"""

import sys
import os
import json
import numpy as np

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tmp")
OUTPUT_GLB = os.path.join(OUTPUT_DIR, "plantgl_test.glb")
OUTPUT_META = os.path.join(OUTPUT_DIR, "plantgl_test_meta.json")


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # Step 1: Import
    print("[1/4] Importing openalea.plantgl...")
    try:
        from openalea.plantgl import all as pgl
        print("      OK — imported")
        print(f"      Module path: {pgl.__file__ if hasattr(pgl, '__file__') else 'N/A'}")
    except ImportError as e:
        print(f"FATAL: {e}")
        sys.exit(1)

    # Step 2: Create geometry (a cone profile revolved around Y)
    print("[2/4] Creating test geometry...")
    try:
        from openalea.plantgl.scenegraph import Shape, Material, Scene
        from openalea.plantgl.math import Vector3

        ctrl_pts = [Vector3(0, 0, 0), Vector3(0.5, 0, 0), Vector3(0, 1, 0)]
        profile = pgl.Polyline(ctrl_pts)

        # Revolve around Y
        axis = (Vector3(0, 0, 0), Vector3(0, 1, 0))
        shape_3d = pgl.AxialGeometry.sweep(profile, axis=axis, angle=360)

        if shape_3d is None:
            print("FATAL: sweep returned None")
            sys.exit(1)

        mat = Material()
        shape = Shape(shape_3d, mat)
        scene = Scene()
        scene.add(shape)
        print(f"      Scene created with {len(scene)} shape(s)")
    except Exception as e:
        print(f"FATAL: geometry creation failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    # Step 3: Tessellate and extract mesh data
    print("[3/4] Tessellating and extracting mesh data...")
    try:
        tesselator = pgl.Tesselator()
        triangulated = tesselator.process(scene)

        if triangulated is None or len(triangulated) == 0:
            print("FATAL: empty tessellation result")
            sys.exit(1)

        tri_shape = triangulated[0]
        geom = tri_shape.geometry

        point3 = geom.pointList
        index3 = geom.indexList

        vertices = np.array([(p.x, p.y, p.z) for p in point3], dtype=np.float32)
        faces = np.array([(i.x, i.y, i.z) for i in index3], dtype=np.uint32).reshape(-1, 3)

        print(f"      Vertices: {len(vertices)}, Faces: {len(faces)}")
    except Exception as e:
        print(f"FATAL: tessellation failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    # Step 4: Export to GLB via trimesh
    print("[4/4] Exporting GLB via trimesh...")
    try:
        import trimesh
        mesh = trimesh.Trimesh(vertices=vertices, faces=faces)
        mesh.export(OUTPUT_GLB, file_type="glb")

        file_size = os.path.getsize(OUTPUT_GLB)
        meta = {
            "vertices": int(len(vertices)),
            "faces": int(len(faces)),
            "file_size_bytes": file_size,
            "file_path": OUTPUT_GLB,
        }
        with open(OUTPUT_META, "w") as f:
            json.dump(meta, f, indent=2)

        print(f"      GLB: {OUTPUT_GLB} ({file_size} bytes)")
        print(f"      Meta: {OUTPUT_META}")
        print()
        print("PHASE 0 PASSED")
    except Exception as e:
        print(f"FATAL: GLB export failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
