"""Garden GLB export — writes into the digital-garden AR assets path."""

import os
import json
import bpy
from bpy.types import Operator

from .scene_bridge import COLLECTION_NAME, plant_object_name


class PS_OT_export_garden(Operator):
    bl_idname = "plantstudio.export_garden"
    bl_label = "Export Garden GLB"
    bl_description = "Export the PlantStudio plants collection as a GLB"

    def execute(self, context):
        props = context.scene.ps_props
        slug = props.garden_slug.strip().lower().replace(" ", "-")
        if not slug:
            self.report({'ERROR'}, "Garden slug is empty")
            return {'CANCELLED'}

        # determine output dir: explicit export_dir or repo assets path
        if props.export_dir:
            out_dir = props.export_dir
        else:
            # default: digital-garden-AR/src/assets/gardens relative to repo root
            repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            out_dir = os.path.join(repo, "digital-garden-AR", "src", "assets", "gardens")
        os.makedirs(out_dir, exist_ok=True)

        # select all plant objects
        coll = bpy.data.collections.get(COLLECTION_NAME)
        if coll is None or len(coll.objects) == 0:
            self.report({'ERROR'}, "No PlantStudio plants in scene")
            return {'CANCELLED'}

        for obj in coll.objects:
            obj.select_set(True)
        bpy.context.view_layer.objects.active = coll.objects[0]

        # export via Blender's glTF exporter (GLB)
        out_path = os.path.join(out_dir, f"{slug}.glb")
        try:
            bpy.ops.export_scene.gltf(
                filepath=out_path,
                export_format='GLB',
                use_selection=True,
                export_yup=True,
                export_materials='EXPORT',
            )
        except TypeError:
            # older export_scene.gltf signature
            bpy.ops.export_scene.gltf(
                filepath=out_path,
                export_format='GLB',
                use_selection=True,
            )

        for obj in coll.objects:
            obj.select_set(False)

        # write growth-config.json entries for the pipeline
        entries = []
        for obj in coll.objects:
            if "ps_species" not in obj:
                continue
            species = obj["ps_species"]
            seed = int(obj["ps_seed"])
            day = int(obj["ps_day"])
            loc = obj.location
            entries.append({
                "plant_slot": obj.name,
                "species": species,
                "seed": seed,
                "planted_date": _day_to_date(day),
                "mutation_strength": 0.0,
                "position": [round(loc[0], 3), 0.0, round(loc[2], 3)],
                "canopy_radius": None,
            })

        config_path = os.path.join(out_dir, "growth-config.json")
        cfg = {"gardens": {slug: {"image_target": "", "plants": entries}}}
        with open(config_path, "w") as f:
            json.dump(cfg, f, indent=2)

        self.report({'INFO'},
                    f"Exported {len(entries)} plants to {out_path}")
        return {'FINISHED'}


def _day_to_date(day):
    from datetime import date, timedelta
    return (date.today() - timedelta(days=day)).isoformat()
