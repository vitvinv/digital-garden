"""
Species parameter definitions for the digital garden.

Each species defines:
  - Growth curve (S-curve): midpoint day + steepness
  - Maximum dimensions at full maturity
  - Procedural generation parameters specific to the plant archetype
  - Default canopy radius (used for neighbor overlap)
"""

import math

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
