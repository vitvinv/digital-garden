"""Headless Blender decimation worker (Decimate modifier).

Reads a JSON mesh {"vertices": [[x,y,z],...], "faces": [[i,j,k],...]} in any
consistent coordinate space, applies Blender's Decimate modifier
(COLLAPSE mode by default, ratio 0.2), and writes the decimated mesh back as
the same JSON shape. Face winding and vertex coordinates are preserved; only
collapsed vertices/faces are removed.

Used by scripts/plant_glb.py. Run inside Blender:

    blender --background --factory-startup --python scripts/blender_decimate.py -- \
        mesh_in.json mesh_out.json --ratio 0.2 --mode COLLAPSE
"""

import argparse
import json
import sys

__all__ = ["decimate_json"]


def parse_args(argv):
    parser = argparse.ArgumentParser(
        description="Apply the Blender Decimate modifier to a JSON mesh.")
    parser.add_argument("input", help="input JSON {vertices, faces}")
    parser.add_argument("output", help="output JSON {vertices, faces}")
    parser.add_argument("--ratio", type=float, default=0.2,
                        help="Decimate modifier ratio (default 0.2)")
    parser.add_argument("--mode", default="COLLAPSE",
                        choices=["COLLAPSE", "UN_SUBDIVIDE", "DISSOLVE", "PLANAR"],
                        help="Decimate modifier mode (default COLLAPSE)")
    return parser.parse_args(argv)


def decimate_json(vertices, faces, ratio=0.2, mode="COLLAPSE"):
    """Apply the Decimate modifier to {vertices, faces}, return the result.

    Imported lazily so the module can be imported outside Blender for tests.
    """
    import bpy

    mesh = bpy.data.meshes.new("Plant")
    mesh.from_pydata(vertices, [], [tuple(face) for face in faces])
    mesh.update()
    mesh.validate()

    obj = bpy.data.objects.new("Plant", mesh)
    bpy.context.scene.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj

    before = len(mesh.polygons)
    modifier = obj.modifiers.new("Decimate", "DECIMATE")
    modifier.decimate_type = mode
    modifier.ratio = ratio
    bpy.ops.object.modifier_apply(modifier=modifier.name)
    after = len(obj.data.polygons)

    out_vertices = [tuple(vertex.co) for vertex in obj.data.vertices]
    out_faces = [[index for index in polygon.vertices]
                 for polygon in obj.data.polygons]
    print(f"decimate: {before} -> {after} faces (ratio {ratio}, mode {mode})")
    return {"vertices": out_vertices, "faces": out_faces}


def main():
    argv = sys.argv
    if "--" in argv:
        argv = argv[argv.index("--") + 1:]
    args = parse_args(argv)

    with open(args.input, "r", encoding="utf-8") as f:
        data = json.load(f)

    result = decimate_json(data["vertices"], data["faces"],
                           ratio=args.ratio, mode=args.mode)

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(result, f)


if __name__ == "__main__":
    main()
