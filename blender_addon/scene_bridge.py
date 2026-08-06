"""Bridge: PdPlant mesh data -> Blender mesh objects and materials.

Uses only stable bpy APIs available in Blender 4.2 LTS and 5.x LTS.
"""

import os
import bpy
import bmesh
import mathutils

from .core.factory import create_plant
from .core.mesh_buffer import MeshBuffer
from .core.turtle import MeshTurtle
from .core.draw import draw_plant

COLLECTION_NAME = "PlantStudio Plants"
GARDEN_COLLECTION_PREFIX = "PS Garden"


def ensure_collection(name, parent=None):
    if name in bpy.data.collections:
        coll = bpy.data.collections[name]
    else:
        coll = bpy.data.collections.new(name)
        bpy.context.scene.collection.children.link(coll)
    return coll


def color_to_rgba(color, alpha=1.0):
    """PlantStudio 0-255 color -> (r, g, b, a) 0-1."""
    r, g, b = (float(c) / 255.0 for c in color[:3])
    return (r, g, b, alpha)


def make_material(name, color):
    """Create a Blender material from a PlantStudio color (if not existing)."""
    if name in bpy.data.materials:
        return bpy.data.materials[name]
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf is not None:
        bsdf.inputs["Base Color"].default_value = color_to_rgba(color)
        bsdf.inputs["Roughness"].default_value = 0.6
    return mat


def build_mesh_object(plant, name):
    """Build a bpy mesh object from a grown plant."""
    buffer = MeshBuffer()
    turtle = MeshTurtle(buffer)
    turtle.setScale_pixelsPerMm(0.1)  # mm -> cm scale
    draw_plant(plant, turtle)
    data = buffer.to_mesh_data()

    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(data["vertices"], [], data["faces"])
    mesh.update()

    # materials: one per unique color
    color_to_mat = {}
    for i, color in enumerate(data["face_colors"]):
        mat_name = f"{name}_mat_{color[0]}_{color[1]}_{color[2]}"
        if mat_name not in color_to_mat:
            mat = make_material(mat_name, color)
            mesh.materials.append(mat)
            color_to_mat[mat_name] = len(mesh.materials) - 1
        mesh.polygons[i].material_index = color_to_mat[mat_name]

    obj = bpy.data.objects.new(name, mesh)
    return obj


def plant_object_name(species, seed, day):
    return f"{species.replace(' ', '_')}_{seed}_d{day}"


def build_plant_object(species, seed, day, collection, tdo_library):
    """Grow + build + link a plant object. Returns the bpy object."""
    plant = create_plant(species, seed=seed, tdo_library=tdo_library)
    plant.growTo(day)
    name = plant_object_name(species.name, seed, day)
    obj = build_mesh_object(plant, name)
    # store metadata
    obj["ps_species"] = species.name
    obj["ps_seed"] = seed
    obj["ps_day"] = day
    collection.objects.link(obj)
    return obj


def rebuild_plant_mesh(obj, plant, fast=False):
    """
    Rebuild the mesh of an existing plant object in place (no new object).

    fast=True: lower-detail draw (fewer stem divisions) for realtime preview.
    """
    buffer = MeshBuffer()
    turtle = MeshTurtle(buffer)
    turtle.setScale_pixelsPerMm(0.1)
    if fast:
        # realtime preview: 1 division per stem, low pipe faces
        try:
            plant.pGeneral.lineDivisions = 1
        except AttributeError:
            pass
    draw_plant(plant, turtle)
    data = buffer.to_mesh_data()

    mesh = obj.data
    name = obj.name
    mesh.clear_geometry()
    mesh.from_pydata(data["vertices"], [], data["faces"])
    mesh.update()

    # rebuild material slots to match current colors
    color_to_slot = {}
    mesh.materials.clear()
    for i, color in enumerate(data["face_colors"]):
        mat_name = f"{name}_mat_{color[0]}_{color[1]}_{color[2]}"
        if mat_name not in color_to_slot:
            mat = make_material(mat_name, color)
            mesh.materials.append(mat)
            color_to_slot[mat_name] = len(mesh.materials) - 1
        mesh.polygons[i].material_index = color_to_slot[mat_name]
    return obj
