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
    "version": (0, 1, 0),
    "blender": (4, 2, 0),
    "location": "View3D > Sidebar > PlantStudio",
    "description": "PlantStudio plant growth simulator: 63 species, deterministic growth, garden GLB export",
    "category": "Add Mesh",
}


def register():
    import bpy
    from .ui_panel import PSProperties, PS_PT_panel
    from .operators import (PS_OT_add_plant, PS_OT_regrow, PS_OT_step_day,
                            PS_OT_delete_plant, PS_OT_random_seed)
    from .export_glb import PS_OT_export_garden
    from .animator import PS_OT_animate_growth
    from .wizard import (PSWizardKnobs, PS_OT_wizard, PS_OT_wizard_stop,
                         PS_OT_wizard_select, PS_OT_wizard_add)

    classes = [
        PSProperties,
        PSWizardKnobs,
        PS_PT_panel,
        PS_OT_add_plant,
        PS_OT_regrow,
        PS_OT_step_day,
        PS_OT_delete_plant,
        PS_OT_random_seed,
        PS_OT_export_garden,
        PS_OT_animate_growth,
        PS_OT_wizard,
        PS_OT_wizard_stop,
        PS_OT_wizard_select,
        PS_OT_wizard_add,
    ]
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.ps_props = bpy.props.PointerProperty(type=PSProperties)
    bpy.types.Scene.ps_wizard_knobs = bpy.props.PointerProperty(type=PSWizardKnobs)


def unregister():
    import bpy
    from .ui_panel import PSProperties, PS_PT_panel
    from .operators import (PS_OT_add_plant, PS_OT_regrow, PS_OT_step_day,
                            PS_OT_delete_plant, PS_OT_random_seed)
    from .export_glb import PS_OT_export_garden
    from .animator import PS_OT_animate_growth
    from .wizard import (PSWizardKnobs, PS_OT_wizard, PS_OT_wizard_stop,
                         PS_OT_wizard_select, PS_OT_wizard_add)

    classes = [
        PSProperties,
        PSWizardKnobs,
        PS_PT_panel,
        PS_OT_add_plant,
        PS_OT_regrow,
        PS_OT_step_day,
        PS_OT_delete_plant,
        PS_OT_random_seed,
        PS_OT_export_garden,
        PS_OT_animate_growth,
        PS_OT_wizard,
        PS_OT_wizard_stop,
        PS_OT_wizard_select,
        PS_OT_wizard_add,
    ]
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    del bpy.types.Scene.ps_props
    del bpy.types.Scene.ps_wizard_knobs


if __name__ == "__main__":
    register()
