"""PlantStudio — a Blender addon port of the PlantStudio plant simulator.

Rebuilds PlantStudio's biomass-driven meristem growth model in Blender:
load species from bundled .pla libraries (63 species), grow them
deterministically by day + seed, and compose multiple plants into
gardens exportable as GLB for the digital-garden AR pipeline.

Works in Blender 4.2 LTS and 5.x LTS.

Note: bpy-dependent modules are imported lazily inside register() so
that the pure-Python core stays importable outside Blender (for tests).
"""

bl_info = {
    "name": "PlantStudio",
    "author": "Kurtz-Fernhout Software (ported)",
    "version": (0, 2, 0),
    "blender": (4, 2, 0),
    "location": "View3D > Sidebar > PlantStudio",
    "description": "PlantStudio plant growth simulator: 63 species, deterministic growth, garden GLB export",
    "category": "Add Mesh",
}


def register():
    import bpy
    # Installing a new version over an already-enabled copy (or a stale
    # module left in the session) re-runs register() while the old classes
    # are still in bpy.types, which raises "already registered as a
    # subclass". Clean up any prior registration first so this is idempotent.
    if hasattr(bpy.types.Scene, "ps_props"):
        try:
            unregister()
        except Exception:
            pass
    from .ui_panel import (PSProperties, PS_PT_panel, PSPlantListItem,
                           PSPlantList, PS_UL_plants, PS_MT_presets,
                           register_category_menus, _depsgraph_sync_plant_list)
    from .operators import (PS_OT_add_plant, PS_OT_regrow, PS_OT_step_day,
                            PS_OT_delete_plant, PS_OT_random_seed,
                            PS_OT_load_preset, PS_OT_save_preset,
                            PS_OT_wizard_step, PS_OT_export_plant_config)
    from .animator import PS_OT_animate_growth
    from .wizard import PSWizardKnobs, _cancel_timer

    classes = [
        PSProperties,
        PSPlantListItem,
        PSPlantList,
        PSWizardKnobs,
        PS_UL_plants,
        PS_MT_presets,
        PS_PT_panel,
        PS_OT_add_plant,
        PS_OT_regrow,
        PS_OT_step_day,
        PS_OT_delete_plant,
        PS_OT_random_seed,
        PS_OT_load_preset,
        PS_OT_save_preset,
        PS_OT_wizard_step,
        PS_OT_animate_growth,
        PS_OT_export_plant_config,
    ]
    for cls in classes:
        # unregister any stale copy of this class (left over from a previous
        # version of the addon or an interrupted install) before registering
        # so install-over-enabled never raises "already registered"
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass
        bpy.utils.register_class(cls)
    register_category_menus()
    bpy.types.Scene.ps_props = bpy.props.PointerProperty(type=PSProperties)
    bpy.types.Scene.ps_wizard_knobs = bpy.props.PointerProperty(type=PSWizardKnobs)
    bpy.types.Scene.ps_plant_list = bpy.props.PointerProperty(type=PSPlantList)
    if _depsgraph_sync_plant_list not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(_depsgraph_sync_plant_list)


def unregister():
    import bpy
    from .ui_panel import (PSProperties, PS_PT_panel, PSPlantListItem,
                           PSPlantList, PS_UL_plants, _depsgraph_sync_plant_list)
    from .operators import (PS_OT_add_plant, PS_OT_regrow, PS_OT_step_day,
                            PS_OT_delete_plant, PS_OT_random_seed,
                            PS_OT_load_preset, PS_OT_save_preset,
                            PS_OT_wizard_step, PS_OT_export_plant_config)
    from .animator import PS_OT_animate_growth
    from .wizard import PSWizardKnobs, _cancel_timer

    _cancel_timer()

    # Defensive cleanup: never raise mid-unregister so the addon can always
    # be re-registered cleanly (including partial/stale registration state).
    try:
        if _depsgraph_sync_plant_list in bpy.app.handlers.depsgraph_update_post:
            bpy.app.handlers.depsgraph_update_post.remove(_depsgraph_sync_plant_list)
    except Exception:
        pass

    classes = [
        PSProperties,
        PSPlantListItem,
        PSPlantList,
        PSWizardKnobs,
        PS_UL_plants,
        PS_PT_panel,
        PS_OT_add_plant,
        PS_OT_regrow,
        PS_OT_step_day,
        PS_OT_delete_plant,
        PS_OT_random_seed,
        PS_OT_load_preset,
        PS_OT_save_preset,
        PS_OT_wizard_step,
        PS_OT_animate_growth,
        PS_OT_export_plant_config,
    ]
    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass
    for name in ("ps_props", "ps_wizard_knobs", "ps_plant_list"):
        try:
            delattr(bpy.types.Scene, name)
        except AttributeError:
            pass


if __name__ == "__main__":
    register()
