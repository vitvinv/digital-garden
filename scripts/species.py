"""
Species parameter definitions for the digital garden.

Each species defines:
  - Growth curve (S-curve): midpoint day + steepness
  - Maximum dimensions at full maturity
  - Procedural generation parameters specific to the plant archetype
  - Default canopy radius (used for neighbor overlap)
"""

import math
import copy


class SpeciesParams:
    def __init__(self, name, max_height, max_canopy_radius, growth_midpoint,
                 growth_steepness, **kwargs):
        self.name = name
        self.max_height = max_height
        self.max_canopy_radius = max_canopy_radius
        self.growth_midpoint = growth_midpoint
        self.growth_steepness = growth_steepness
        # Store all extra kwargs as attributes
        for k, v in kwargs.items():
            setattr(self, k, v)

    def get_canopy_radius(self, override=None):
        if override is not None and override > 0:
            return float(override)
        return self.max_canopy_radius


def apply_overrides(params, overrides):
    """
    Return a copy of params with attribute overrides applied.

    overrides: dict of {attribute_name: value} or None.
    The original params object is never mutated — determinism is preserved.
    """
    if not overrides:
        return params
    modified = copy.copy(params)
    for key, value in overrides.items():
        if hasattr(modified, key):
            setattr(modified, key, value)
    return modified


SPECIES = {
    "fern": SpeciesParams(
        name="fern",
        max_height=0.8,
        max_canopy_radius=0.4,
        growth_midpoint=60.0,
        growth_steepness=0.06,
        # Fern-specific
        frond_count=9,
        frond_length=0.5,
        frond_angle_spread=0.65,       # radians from vertical
        leaflet_pairs=12,
        leaflet_size=0.04,
        stem_radius=0.015,
    ),
    "succulent": SpeciesParams(
        name="succulent",
        max_height=0.25,
        max_canopy_radius=0.25,
        growth_midpoint=80.0,
        growth_steepness=0.04,
        # Succulent-specific
        leaf_count=16,
        leaf_length=0.18,
        leaf_width=0.06,
        leaf_thickness=0.03,
        rosette_tiers=4,
        leaf_angle_spread=0.45,
    ),
    "shrub": SpeciesParams(
        name="shrub",
        max_height=0.6,
        max_canopy_radius=0.5,
        growth_midpoint=70.0,
        growth_steepness=0.05,
        # Shrub-specific
        stem_count=5,
        branch_depth=2,
        branch_angle_spread=0.5,
        branch_length_factor=0.6,
        leaf_size=0.04,
        leaf_density=6,
        stem_radius=0.02,
    ),
}


def growth_scale(params, day_n):
    """
    Logistic S-curve growth: 0 at day 0, approaches 1.0 at maturity.
    scale = 1 / (1 + exp(-k * (day_n - midpoint)))
    """
    if day_n <= 0:
        return 0.001  # Tiny but non-zero (seedling)
    return 1.0 / (1.0 + math.exp(-params.growth_steepness * (day_n - params.growth_midpoint)))


def apply_neighbor_discount(scale, neighbor_state):
    """
    Reduce growth scale based on canopy overlap with neighbors.
    Minimum 10% growth even in heavy crowding.
    """
    if neighbor_state is None:
        return scale
    overlap = neighbor_state.get("total_overlap", 0.0)
    discount = max(0.1, 1.0 - overlap)
    return scale * discount


# ── Designer parameter schema ──
# Per species: list of (attribute_name, label, min, max, step)
# The Plant Designer exposes these as sliders/number inputs in real-time.

DESIGN_PARAMS = {
    "fern": [
        ("max_height", "Height", 0.1, 1.5, 0.01),
        ("max_canopy_radius", "Canopy radius", 0.05, 1.0, 0.01),
        ("frond_count", "Frond count", 2, 24, 1),
        ("frond_length", "Frond length", 0.1, 1.0, 0.01),
        ("frond_angle_spread", "Frond spread", 0.1, 1.3, 0.01),
        ("leaflet_pairs", "Leaflet pairs", 2, 30, 1),
        ("leaflet_size", "Leaflet size", 0.01, 0.15, 0.005),
        ("stem_radius", "Stem radius", 0.005, 0.06, 0.002),
        ("growth_midpoint", "Growth midpoint (days)", 10, 300, 5),
        ("growth_steepness", "Growth speed", 0.01, 0.2, 0.005),
    ],
    "succulent": [
        ("max_height", "Height", 0.05, 0.6, 0.01),
        ("max_canopy_radius", "Canopy radius", 0.05, 0.8, 0.01),
        ("leaf_count", "Leaf count", 4, 40, 1),
        ("leaf_length", "Leaf length", 0.05, 0.5, 0.01),
        ("leaf_width", "Leaf width", 0.02, 0.2, 0.01),
        ("leaf_thickness", "Leaf thickness", 0.01, 0.12, 0.005),
        ("rosette_tiers", "Rosette tiers", 1, 8, 1),
        ("leaf_angle_spread", "Leaf angle", 0.1, 1.0, 0.01),
        ("growth_midpoint", "Growth midpoint (days)", 10, 300, 5),
        ("growth_steepness", "Growth speed", 0.01, 0.2, 0.005),
    ],
    "shrub": [
        ("max_height", "Height", 0.1, 1.5, 0.01),
        ("max_canopy_radius", "Canopy radius", 0.05, 1.2, 0.01),
        ("stem_count", "Stem count", 1, 12, 1),
        ("branch_depth", "Branch depth", 1, 5, 1),
        ("branch_angle_spread", "Branch angle", 0.1, 1.0, 0.01),
        ("branch_length_factor", "Branch length", 0.2, 1.0, 0.01),
        ("leaf_size", "Leaf size", 0.01, 0.15, 0.005),
        ("leaf_density", "Leaf density", 1, 20, 1),
        ("stem_radius", "Stem radius", 0.005, 0.08, 0.002),
        ("growth_midpoint", "Growth midpoint (days)", 10, 300, 5),
        ("growth_steepness", "Growth speed", 0.01, 0.2, 0.005),
    ],
}
