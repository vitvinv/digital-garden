"""Realtime Plant Wizard — plant list + live knobs in the N-panel.

Design:
  - The N-panel (PlantStudio > Wizard) shows:
      * a list of plants in the scene (click to select)
      * 24 knobs (real Blender sliders) for the selected plant
  - Every knob has an update callback that sets a 'dirty' flag
  - A lightweight modal operator polls the flag on a timer and
    rebuilds the selected plant's mesh in place — realtime preview
  - Determinism preserved: knobs overwrite species params, then the
    plant is re-grown from scratch with (params, seed, day)
"""

import bpy
from bpy.types import Operator, PropertyGroup
from bpy.props import (FloatProperty, IntProperty, BoolProperty,
                       StringProperty)

from .operators import get_library
from .scene_bridge import (ensure_collection, COLLECTION_NAME,
                           rebuild_plant_mesh)
from .core.factory import create_plant

# ── knob definitions: (prop name, param path, label, min, max, default) ──

KNOB_DEFS = [
    ("knob_age_maturity", ("pGeneral", "ageAtMaturity"), "Age at maturity", 10, 500, 100),
    ("knob_flower_start", ("pGeneral", "ageAtWhichFloweringStarts"), "Flowering starts", 0, 500, 60),
    ("knob_repro_alloc", ("pGeneral", "fractionReproductiveAllocationAtMaturity_frn"), "Repro allocation", 0.0, 1.0, 0.6),
    ("knob_phyllo", ("pGeneral", "phyllotacticRotationAngle"), "Phyllotactic angle", 0, 180, 137.5),
    ("knob_line_div", ("pGeneral", "lineDivisions"), "Line divisions", 1, 20, 3),
    ("knob_sway", ("pGeneral", "randomSway"), "Random sway", 0, 90, 0),
    ("knob_branch_index", ("pMeristem", "branchingIndex"), "Branching index", 0, 100, 30),
    ("knob_branch_dist", ("pMeristem", "branchingDistance"), "Branching distance", 0, 10, 3),
    ("knob_branch_angle", ("pMeristem", "branchingAngle"), "Branch angle", 0, 180, 30),
    ("knob_determinate", ("pMeristem", "determinateProbability"), "Determinate prob.", 0.0, 1.0, 1.0),
    ("knob_symp", ("pMeristem", "branchingIsSympodial"), "Sympodial branching", 0, 1, 0),
    ("knob_secondary", ("pMeristem", "secondaryBranchingIsAllowed"), "Secondary branching", 0, 1, 0),
    ("knob_internode_len", ("pInternode", "lengthAtOptimalFinalBiomassAndExpansion_mm"), "Internode length", 0, 200, 60),
    ("knob_internode_wid", ("pInternode", "widthAtOptimalFinalBiomassAndExpansion_mm"), "Internode width", 0.1, 20, 3),
    ("knob_internode_biomass", ("pInternode", "optimalFinalBiomass_pctMPB"), "Internode biomass", 0.1, 20, 4),
    ("knob_curve", ("pInternode", "curvingIndex"), "Curving index", 0, 100, 30),
    ("knob_first_curve", ("pInternode", "firstInternodeCurvingIndex"), "First internode curve", 0, 100, 10),
    ("knob_internode_days", ("pInternode", "minDaysToCreateInternode"), "Internode days", 1, 50, 3),
    ("knob_petiole_len", ("pLeaf", "petioleLengthAtOptimalBiomass_mm"), "Petiole length", 0, 200, 30),
    ("knob_petiole_wid", ("pLeaf", "petioleWidthAtOptimalBiomass_mm"), "Petiole width", 0.1, 20, 1),
    ("knob_petiole_angle", ("pLeaf", "petioleAngle"), "Petiole angle", 0, 180, 40),
    ("knob_leaf_biomass", ("pLeaf", "optimalBiomass_pctMPB"), "Leaf biomass", 0.1, 30, 5),
    ("knob_leaflets", ("pLeaf", "compoundNumLeaflets"), "Leaflets", 1, 30, 1),
    ("knob_leaf_days", ("pLeaf", "maxDaysToGrow"), "Leaf grow days", 1, 50, 10),
]


def _knob_update(self, context):
    self.dirty = True


class PSWizardKnobs(PropertyGroup):
    """Knob values for the selected plant. Sliders set dirty for live rebuild."""

    selected_index: IntProperty(name="Selected plant", default=-1)
    dirty: BoolProperty(name="Dirty", default=False)
    fast_preview: BoolProperty(name="Fast preview", default=True)

    knob_age_maturity: FloatProperty(name="Age at maturity", min=10, max=500, default=100, update=_knob_update)
    knob_flower_start: FloatProperty(name="Flowering starts", min=0, max=500, default=60, update=_knob_update)
    knob_repro_alloc: FloatProperty(name="Repro allocation", min=0.0, max=1.0, default=0.6, update=_knob_update)
    knob_phyllo: FloatProperty(name="Phyllotactic angle", min=0, max=180, default=137.5, update=_knob_update)
    knob_line_div: FloatProperty(name="Line divisions", min=1, max=20, default=3, update=_knob_update)
    knob_sway: FloatProperty(name="Random sway", min=0, max=90, default=0, update=_knob_update)
    knob_branch_index: FloatProperty(name="Branching index", min=0, max=100, default=30, update=_knob_update)
    knob_branch_dist: FloatProperty(name="Branching distance", min=0, max=10, default=3, update=_knob_update)
    knob_branch_angle: FloatProperty(name="Branch angle", min=0, max=180, default=30, update=_knob_update)
    knob_determinate: FloatProperty(name="Determinate prob.", min=0.0, max=1.0, default=1.0, update=_knob_update)
    knob_symp: FloatProperty(name="Sympodial branching", min=0, max=1, default=0, update=_knob_update)
    knob_secondary: FloatProperty(name="Secondary branching", min=0, max=1, default=0, update=_knob_update)
    knob_internode_len: FloatProperty(name="Internode length", min=0, max=200, default=60, update=_knob_update)
    knob_internode_wid: FloatProperty(name="Internode width", min=0.1, max=20, default=3, update=_knob_update)
    knob_internode_biomass: FloatProperty(name="Internode biomass", min=0.1, max=20, default=4, update=_knob_update)
    knob_curve: FloatProperty(name="Curving index", min=0, max=100, default=30, update=_knob_update)
    knob_first_curve: FloatProperty(name="First internode curve", min=0, max=100, default=10, update=_knob_update)
    knob_internode_days: FloatProperty(name="Internode days", min=1, max=50, default=3, update=_knob_update)
    knob_petiole_len: FloatProperty(name="Petiole length", min=0, max=200, default=30, update=_knob_update)
    knob_petiole_wid: FloatProperty(name="Petiole width", min=0.1, max=20, default=1, update=_knob_update)
    knob_petiole_angle: FloatProperty(name="Petiole angle", min=0, max=180, default=40, update=_knob_update)
    knob_leaf_biomass: FloatProperty(name="Leaf biomass", min=0.1, max=30, default=5, update=_knob_update)
    knob_leaflets: FloatProperty(name="Leaflets", min=1, max=30, default=1, update=_knob_update)
    knob_leaf_days: FloatProperty(name="Leaf grow days", min=1, max=50, default=10, update=_knob_update)


def _set_param_by_path(params, path, value):
    section, attr = path
    obj = getattr(params, section, None)
    if obj is None:
        return
    setattr(obj, attr, float(value))


def apply_knobs_to_params(species, knobs):
    """Overwrite the species params with current knob values."""
    from .core.normalize import normalize_params
    normalize_params(species.params)
    for prop_name, path, _label, _lo, _hi, _default in KNOB_DEFS:
        _set_param_by_path(species.params, path, getattr(knobs, prop_name))


def load_knobs_from_params(species, knobs):
    """Set knob values from the species' current params (on selection)."""
    for prop_name, path, _label, _lo, _hi, _default in KNOB_DEFS:
        section, attr = path
        obj = getattr(species.params, section, None)
        if obj is not None and hasattr(obj, attr):
            try:
                setattr(knobs, prop_name, float(getattr(obj, attr)))
            except (TypeError, ValueError):
                pass


def _rebuild_selected(context, fast=True):
    """Rebuild the selected plant's mesh in place using current knobs."""
    knobs = context.scene.ps_wizard_knobs
    coll = bpy.data.collections.get(COLLECTION_NAME)
    if coll is None or not (0 <= knobs.selected_index < len(coll.objects)):
        return
    obj = coll.objects[knobs.selected_index]
    lib, tdo_lib = get_library()
    species = lib.get(obj["ps_species"])
    if species is None:
        return
    apply_knobs_to_params(species, knobs)
    seed = int(obj["ps_seed"])
    day = int(obj["ps_day"])
    plant = create_plant(species, seed=seed, tdo_library=tdo_lib)
    plant.growTo(day)
    rebuild_plant_mesh(obj, plant, fast=fast)


class PS_OT_wizard(Operator):
    """Live wizard loop — polls knob changes and rebuilds in place."""
    bl_idname = "plantstudio.wizard"
    bl_label = "Start Live Wizard"
    bl_description = "Start realtime plant editing (knobs rebuild the plant live)"

    _timer = None

    def invoke(self, context, event):
        props = context.scene.ps_props
        knobs = context.scene.ps_wizard_knobs
        lib, _ = get_library()

        # pre-fill knobs from the currently selected species
        species = lib.get(props.species_name)
        if species is not None:
            load_knobs_from_params(species, knobs)

        coll = bpy.data.collections.get(COLLECTION_NAME)
        if coll is not None and len(coll.objects) > 0:
            knobs.selected_index = 0
        else:
            knobs.selected_index = -1

        wm = context.window_manager
        self._timer = wm.event_timer_add(0.05, window=context.window)
        wm.modal_handler_add(self)
        context.area.tag_redraw()
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        knobs = context.scene.ps_wizard_knobs
        if event.type in {'RIGHTMOUSE', 'ESC'}:
            self._stop(context)
            return {'CANCELLED'}
        if event.type == 'TIMER':
            if knobs.dirty:
                knobs.dirty = False
                _rebuild_selected(context, fast=knobs.fast_preview)
            context.area.tag_redraw()
        return {'PASS_THROUGH'}

    def _stop(self, context):
        wm = context.window_manager
        if self._timer is not None:
            wm.event_timer_remove(self._timer)
            self._timer = None
        context.area.tag_redraw()


class PS_OT_wizard_stop(Operator):
    bl_idname = "plantstudio.wizard_stop"
    bl_label = "Stop Live Wizard"

    def execute(self, context):
        # find the running modal operator and cancel it
        for area in context.screen.areas:
            area.tag_redraw()
        self.report({'INFO'}, "Press ESC or right-click to stop the live wizard")
        return {'FINISHED'}


class PS_OT_wizard_select(Operator):
    bl_idname = "plantstudio.wizard_select"
    bl_label = "Select Plant"
    index: IntProperty(name="Index", default=0)

    def execute(self, context):
        knobs = context.scene.ps_wizard_knobs
        knobs.selected_index = self.index
        knobs.dirty = True
        coll = bpy.data.collections.get(COLLECTION_NAME)
        if coll is not None and 0 <= self.index < len(coll.objects):
            obj = coll.objects[self.index]
            context.view_layer.objects.active = obj
            obj.select_set(True)
        return {'FINISHED'}


class PS_OT_wizard_add(Operator):
    bl_idname = "plantstudio.wizard_add"
    bl_label = "Add Plant"
    species_name: StringProperty(name="Species", default="")

    def execute(self, context):
        props = context.scene.ps_props
        lib, tdo_lib = get_library()
        knobs = context.scene.ps_wizard_knobs
        name = self.species_name or props.species_name
        species = lib.get(name)
        if species is None:
            self.report({'ERROR'}, f"Species '{name}' not found")
            return {'CANCELLED'}
        apply_knobs_to_params(species, knobs)
        coll = ensure_collection(COLLECTION_NAME)
        from .scene_bridge import build_plant_object
        obj = build_plant_object(species, props.seed, props.day, coll, tdo_lib)
        knobs.selected_index = len(coll.objects) - 1
        knobs.dirty = True
        context.view_layer.objects.active = obj
        obj.select_set(True)
        return {'FINISHED'}


def draw_wizard_panel(layout, context):
    """Draw the wizard section in the N-panel."""
    props = context.scene.ps_props
    knobs = context.scene.ps_wizard_knobs

    coll = bpy.data.collections.get(COLLECTION_NAME)
    plants = list(coll.objects) if coll else []

    box = layout.box()
    box.label(text="Wizard", icon='TOOL_SETTINGS')

    # plant list
    row = box.row()
    row.label(text=f"Plants ({len(plants)})")
    for i, obj in enumerate(plants):
        r = box.row(align=True)
        op = r.operator("plantstudio.wizard_select", text=obj.name,
                        depress=(i == knobs.selected_index))
        op.index = i

    # add plant
    row = box.row()
    row.prop(props, "species_name", text="")
    op = row.operator("plantstudio.wizard_add", text="Add", icon='ADD')
    op.species_name = props.species_name

    # knobs for the selected plant
    if 0 <= knobs.selected_index < len(plants):
        box.label(text=f"Knobs — {plants[knobs.selected_index].name}",
                  icon='OPTIONS')
        box.prop(knobs, "fast_preview")
        for prop_name, _path, label, _lo, _hi, _default in KNOB_DEFS:
            box.prop(knobs, prop_name, text=label)
    else:
        box.label(text="No plant selected. Add one first.", icon='INFO')

    row = box.row()
    row.operator("plantstudio.wizard", text="Start Live", icon='PLAY')
    row.operator("plantstudio.wizard_stop", text="Stop", icon='SNAP_FACE')
