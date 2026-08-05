"""N-panel UI for the PlantStudio addon."""

import bpy
from bpy.types import Panel
from bpy.props import StringProperty, IntProperty, PointerProperty, EnumProperty

from .operators import get_library

_species_cache = []


def _species_items(self, context):
    """Dynamic enum items from the species library."""
    items = []
    try:
        lib, _ = get_library()
        names = lib.names() if lib else []
    except Exception:
        names = []
    for n in names[:500]:
        items.append((n, n, n))
    if not items:
        items.append(("maiden grass", "maiden grass", "fallback"))
    return items


class PSProperties(bpy.types.PropertyGroup):
    species_name: EnumProperty(
        name="Species",
        description="PlantStudio species",
        items=_species_items,
    )
    seed: IntProperty(
        name="Seed",
        description="Deterministic random seed",
        default=280,
        min=1, max=99999,
    )
    day: IntProperty(
        name="Age (days)",
        description="Plant age in days",
        default=60,
        min=0, max=1000,
    )
    garden_slug: StringProperty(
        name="Garden slug",
        description="Garden name used in the export path",
        default="my-garden",
    )
    export_dir: StringProperty(
        name="Export dir",
        description="Directory to export GLB files into",
        subtype='DIR_PATH',
        default="",
    )

    # cached handles
    _lib = None
    _tdo_lib = None


class PS_PT_panel(Panel):
    bl_label = "PlantStudio"
    bl_idname = "PS_PT_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "PlantStudio"

    def draw(self, context):
        layout = self.layout
        props = context.scene.ps_props

        box = layout.box()
        box.label(text="Plant")
        box.prop(props, "species_name")
        row = box.row()
        row.prop(props, "seed")
        row.operator("plantstudio.random_seed", text="", icon='DICE')
        box.prop(props, "day")

        box.separator()
        box.operator("plantstudio.add_plant", icon='ADD')
        box.operator("plantstudio.regrow", icon='FILE_REFRESH')
        box.operator("plantstudio.step_day", icon='PLAY')
        box.operator("plantstudio.animate_growth", icon='TIME')
        box.operator("plantstudio.delete_plant", icon='X')

        box2 = layout.box()
        box2.label(text="Garden export")
        box2.prop(props, "garden_slug")
        box2.prop(props, "export_dir")
        box2.operator("plantstudio.export_garden", icon='EXPORT')
