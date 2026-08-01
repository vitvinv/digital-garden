"""
Deterministic procedural plant mesh generation.

generate(species, seed, day_n, neighbor_state) -> dict
  Same (species, seed, day_n) always produces byte-identical mesh data.
  Different seeds produce divergent plants of the same species.
  Larger day_n produces bigger plants (S-curve growth).

Uses trimesh for geometry construction. PlantGL backend can be
swapped in later without changing the public interface.
"""

import math
import random
import hashlib
import numpy as np
import trimesh

from species import SPECIES, growth_scale, apply_neighbor_discount


class DeterministicRNG:
    """
    PRNG deterministically seeded from (species, seed, day_n).
    Uses Python's random.Random with a hash-derived seed.
    """

    def __init__(self, species, seed, day_n):
        key = f"{species}:{seed}:{day_n}"
        seed_int = int(hashlib.sha256(key.encode()).hexdigest(), 16) % (2**31)
        self.rng = random.Random(seed_int)
        self._np_rng = np.random.RandomState(seed_int)

    def uniform(self, lo, hi):
        return self.rng.uniform(lo, hi)

    def choice(self, seq):
        return self.rng.choice(seq)

    def gauss(self, mu, sigma):
        return self.rng.gauss(mu, sigma)

    def np_uniform(self, lo, hi, size=None):
        return self._np_rng.uniform(lo, hi, size)


def cylinder_between(start, end, radius, sections=8):
    """Create a cylinder mesh between two 3D points."""
    start = np.asarray(start, dtype=np.float64)
    end = np.asarray(end, dtype=np.float64)

    length = np.linalg.norm(end - start)
    if length < 1e-8:
        return trimesh.Trimesh()

    mid = (start + end) / 2.0
    direction = (end - start) / length

    cyl = trimesh.creation.cylinder(radius=radius, height=length, sections=sections)

    z_axis = np.array([0.0, 0.0, 1.0])
    if np.allclose(direction, z_axis):
        rotation = np.eye(4)
    elif np.allclose(direction, -z_axis):
        rotation = trimesh.transformations.rotation_matrix(math.pi, [1, 0, 0])
    else:
        rot_axis = np.cross(z_axis, direction)
        rot_axis = rot_axis / np.linalg.norm(rot_axis)
        angle = math.acos(np.dot(z_axis, direction))
        rotation = trimesh.transformations.rotation_matrix(angle, rot_axis)

    rotation[:3, 3] = mid
    cyl.apply_transform(rotation)
    return cyl


def build_fern(params, rng, scale):
    """
    Fern: central stem with compound fronds in a spiral.
    Each frond = rachis (midrib) + paired leaflets.
    """
    stem_height = params.max_height * scale
    stem_radius = params.stem_radius * scale
    frond_length = params.frond_length * scale
    leaflet_size = params.leaflet_size * scale

    stem = cylinder_between(
        [0, 0, 0],
        [0, stem_height, 0],
        stem_radius,
        sections=6,
    )

    meshes = [stem]
    frond_count = max(1, int(params.frond_count * scale))

    for i in range(frond_count):
        y = stem_height * (0.15 + 0.7 * i / max(1, frond_count - 1))
        angle = (i / frond_count) * math.pi * 2.7 + rng.gauss(0, 0.12)  # spiral + jitter
        spread = params.frond_angle_spread + rng.gauss(0, 0.08)
        this_frond_len = frond_length * rng.uniform(0.85, 1.15)

        rachis_tip = np.array([
            math.cos(angle) * this_frond_len * math.sin(spread),
            y + this_frond_len * math.cos(spread),
            math.sin(angle) * this_frond_len * math.sin(spread),
        ])
        rachis_start = np.array([0, y, 0])

        # Rachis as thin cylinder
        rachis = cylinder_between(rachis_start, rachis_tip, stem_radius * 0.3, sections=4)
        meshes.append(rachis)

        # Leaflets along rachis
        leaflet_pairs = max(2, int(params.leaflet_pairs * scale))
        for j in range(1, leaflet_pairs + 1):
            t = j / (leaflet_pairs + 1)
            base = rachis_start + t * (rachis_tip - rachis_start)
            rachis_dir = rachis_tip - rachis_start
            rachis_dir = rachis_dir / (np.linalg.norm(rachis_dir) + 1e-8)

            # Perpendicular direction in XY plane
            perp = np.array([-rachis_dir[2], 0, rachis_dir[0]])
            perp = perp / (np.linalg.norm(perp) + 1e-8)

            leaf_len = leaflet_size * (1.0 - 0.5 * abs(t - 0.5) * 2) * rng.uniform(0.9, 1.1)
            leaf_w = leaflet_size * 0.25 * rng.uniform(0.8, 1.2)

            # Two leaflets (left and right)
            for sign in [1, -1]:
                jitter = np.array([rng.gauss(0, 0.002), rng.gauss(0, 0.003), rng.gauss(0, 0.002)])
                leaf_tip = base + sign * perp * leaf_len + rachis_dir * leaf_w + jitter
                leaf = cylinder_between(base, leaf_tip, stem_radius * 0.08 * rng.uniform(0.8, 1.2), sections=3)
                meshes.append(leaf)

    combined = trimesh.util.concatenate(meshes)
    return combined


def build_succulent(params, rng, scale):
    """
    Succulent: rosette of thick, triangular leaves in concentric tiers.
    """
    leaf_count = max(4, int(params.leaf_count * scale))
    leaf_length = params.leaf_length * scale
    leaf_width = params.leaf_width * scale
    leaf_thickness = params.leaf_thickness * scale
    tiers = max(1, int(params.rosette_tiers * scale))
    spread = params.leaf_angle_spread

    meshes = []
    center = np.array([0.0, 0.0, 0.0])

    leaf_idx = 0
    for tier in range(tiers):
        t = tier / max(1, tiers - 1)
        tier_leaves = max(2, leaf_count // tiers)
        tier_radius = leaf_length * 0.3 * t
        tier_angle = spread * (1.0 - t * 0.6)

        for j in range(tier_leaves):
            rot_angle = (j / tier_leaves) * math.pi * 2 + rng.uniform(-0.1, 0.1)

            leaf_base = np.array([
                math.cos(rot_angle) * tier_radius,
                tier_radius * 0.1,
                math.sin(rot_angle) * tier_radius,
            ])

            leaf_tip = np.array([
                math.cos(rot_angle) * (tier_radius + leaf_length * math.sin(tier_angle)),
                leaf_length * math.cos(tier_angle),
                math.sin(rot_angle) * (tier_radius + leaf_length * math.sin(tier_angle)),
            ])

            leaf_mid = leaf_base + (leaf_tip - leaf_base) * 0.5 + np.array([
                0, leaf_thickness * 0.3, 0,
            ])

            # Build leaf as a tapered shape using 6 control points
            perp = np.cross(leaf_tip - leaf_base, [0, 1, 0])
            perp = perp / (np.linalg.norm(perp) + 1e-8) * leaf_width * 0.5

            # Quad mesh forming a diamond leaf shape
            verts = np.array([
                leaf_base,
                leaf_mid + perp,
                leaf_tip,
                leaf_mid - perp,
            ])
            faces = np.array([
                [0, 1, 2],
                [0, 2, 3],
                [0, 3, 1],
                [1, 3, 2],
            ])
            leaf_mesh = trimesh.Trimesh(vertices=verts, faces=faces)
            meshes.append(leaf_mesh)
            leaf_idx += 1

    combined = trimesh.util.concatenate(meshes)
    return combined


def build_shrub_branch(start, direction, length, radius, depth, params, rng, scale):
    """Recursive branch building for shrub."""
    end = start + direction * length

    meshes = [cylinder_between(start, end, radius, sections=5)]

    if depth <= 0:
        # Add leaves at tips
        leaf_size = params.leaf_size * scale * (0.5 + rng.uniform(0, 0.5))
        density = max(1, int(params.leaf_density * scale))
        for _ in range(density):
            leaf_dir = np.array([
                rng.gauss(0, 0.5),
                rng.gauss(0.3, 0.3),
                rng.gauss(0, 0.5),
            ])
            leaf_dir = leaf_dir / (np.linalg.norm(leaf_dir) + 1e-8)
            leaf_tip = end + leaf_dir * leaf_size
            leaf = cylinder_between(end, leaf_tip, radius * 0.15, sections=3)
            meshes.append(leaf)
        return trimesh.util.concatenate(meshes)

    # Branch into 2-3 child branches
    branch_count = rng.choice([2, 2, 3])
    for _ in range(branch_count):
        child_dir = direction + np.array([
            rng.gauss(0, params.branch_angle_spread),
            rng.uniform(0.1, 0.5),
            rng.gauss(0, params.branch_angle_spread),
        ])
        child_dir = child_dir / (np.linalg.norm(child_dir) + 1e-8)
        child_len = length * params.branch_length_factor
        child_radius = radius * 0.55
        child_mesh = build_shrub_branch(
            end, child_dir, child_len, child_radius,
            depth - 1, params, rng, scale,
        )
        meshes.append(child_mesh)

    return trimesh.util.concatenate(meshes)


def build_shrub(params, rng, scale):
    """Shrub: multiple stems from base with recursive branching."""
    stem_count = max(1, int(params.stem_count * scale))
    stem_radius = params.stem_radius * scale
    stem_height = params.max_height * scale * 0.7

    meshes = []
    for _ in range(stem_count):
        direction = np.array([
            rng.gauss(0, 0.15),
            1.0,
            rng.gauss(0, 0.15),
        ])
        direction = direction / np.linalg.norm(direction)
        start_offset = np.array([
            rng.gauss(0, 0.02),
            0.0,
            rng.gauss(0, 0.02),
        ])
        shrub_mesh = build_shrub_branch(
            start_offset, direction, stem_height, stem_radius,
            params.branch_depth, params, rng, scale,
        )
        meshes.append(shrub_mesh)

    return trimesh.util.concatenate(meshes)


BUILDERS = {
    "fern": build_fern,
    "succulent": build_succulent,
    "shrub": build_shrub,
}


def generate(species, seed, day_n, neighbor_state=None):
    """
    Deterministic plant mesh generator.

    Args:
        species: str, one of SPECIES keys
        seed: int, genetic seed
        day_n: int, days since planting
        neighbor_state: dict or None, {"total_overlap": float, "neighbor_count": int}

    Returns:
        dict with keys: mesh (trimesh.Trimesh), vertices, faces, height, canopy_radius
    """
    if species not in SPECIES:
        raise ValueError(f"Unknown species '{species}'. Known: {list(SPECIES.keys())}")

    params = SPECIES[species]
    rng = DeterministicRNG(species, seed, day_n)

    scale = growth_scale(params, day_n)
    scale = apply_neighbor_discount(scale, neighbor_state)

    builder = BUILDERS[species]
    mesh = builder(params, rng, scale)

    if mesh.vertices.size == 0:
        mesh = trimesh.creation.icosphere(radius=0.01)

    return {
        "mesh": mesh,
        "vertices": int(len(mesh.vertices)),
        "faces": int(len(mesh.faces)),
        "height": float(params.max_height * scale),
        "canopy_radius": float(params.get_canopy_radius(
            neighbor_state.get("canopy_override") if neighbor_state else None
        ) * scale),
    }
