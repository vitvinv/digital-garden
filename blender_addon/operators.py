"""Blender operators for the PlantStudio addon."""

import os
import bpy
from bpy.types import Operator
from bpy.props import IntProperty, StringProperty, BoolProperty

from .core.plant_library import SpeciesLibrary
from .core.tdo_parser import TdoLibrary
from .scene_bridge import (ensure_collection, build_plant_object,
                           COLLECTION_NAME, plant_object_name)

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")


def get_library():
    """Get (or create) the cached species library + tdo library."""
    props = bpy.context.scene.ps_props
    if getattr(props, "_lib", None) is None:
        props._lib = SpeciesLibrary(DATA_DIR)
    if getattr(props, "_tdo_lib", None) is None:
        path = os.path.join(DATA_DIR, "3D object library.tdo")
        props._tdo_lib = TdoLibrary.from_file(path) if os.path.exists(path) else None
    return props._lib, props._tdo_lib


class PS_OT_add_plant(Operator):
    bl_idname = "plantstudio.add_plant"
    bl_label = "Add Plant"
    bl_description = "Grow a plant and add it to the scene"

    def execute(self, context):
        props = context.scene.ps_props
        lib, tdo_lib = get_library()
        species = lib.get(props.species_name)
        if species is None:
            self.report({'ERROR'}, f"Species '{props.species_name}' not found")
            return {'CANCELLED'}
        coll = ensure_collection(COLLECTION_NAME)
        obj = build_plant_object(species, props.seed, props.day, coll, tdo_lib)
        context.view_layer.objects.active = obj
        obj.select_set(True)
        self.report({'INFO'}, f"Added {obj.name} ({len(obj.data.polygons)} faces)")
        return {'FINISHED'}


class PS_OT_regrow(Operator):
    bl_idname = "plantstudio.regrow"
    bl_label = "Grow To Age"
    bl_description = "Rebuild the selected plant at its target day"

    def execute(self, context):
        obj = context.active_object
        if obj is None or "ps_species" not in obj:
            self.report({'ERROR'}, "Select a PlantStudio plant")
            return {'CANCELLED'}
        props = context.scene.ps_props
        lib, tdo_lib = get_library()
        species = lib.get(obj["ps_species"])
        if species is None:
            self.report({'ERROR'}, "Species not found")
            return {'CANCELLED'}
        day = int(obj["ps_day"])
        seed = int(obj["ps_seed"])
        # rebuild mesh in place
        new_obj = build_plant_object(species, seed, day,
                                     obj.users_collection[0], tdo_lib)
        new_obj.matrix_world = obj.matrix_world
        bpy.data.objects.remove(obj, do_unlink=True)
        context.view_layer.objects.active = new_obj
        new_obj.select_set(True)
        self.report({'INFO'}, f"Regrew to day {day}")
        return {'FINISHED'}


class PS_OT_step_day(Operator):
    bl_idname = "plantstudio.step_day"
    bl_label = "Step Day"
    bl_description = "Advance the selected plant by one day"

    def execute(self, context):
        obj = context.active_object
        if obj is None or "ps_day" not in obj:
            self.report({'ERROR'}, "Select a PlantStudio plant")
            return {'CANCELLED'}
        obj["ps_day"] = int(obj["ps_day"]) + 1
        bpy.ops.plantstudio.regrow()
        return {'FINISHED'}


class PS_OT_delete_plant(Operator):
    bl_idname = "plantstudio.delete_plant"
    bl_label = "Delete Plant"

    def execute(self, context):
        obj = context.active_object
        if obj is None or "ps_species" not in obj:
            self.report({'ERROR'}, "Select a PlantStudio plant")
            return {'CANCELLED'}
        bpy.data.objects.remove(obj, do_unlink=True)
        return {'FINISHED'}


class PS_OT_random_seed(Operator):
    bl_idname = "plantstudio.random_seed"
    bl_label = "Randomize Seed"

    def execute(self, context):
        import random
        context.scene.ps_props.seed = random.randint(1, 9999)
        return {'FINISHED'}
