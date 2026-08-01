"""
Deterministic procedural plant mesh generation using PlantGL.

generate(species, seed, day_n, neighbor_state) -> dict
  Uses PlantGL for semi-realistic plant geometry (extrusions, revolutions).
  Same (species, seed, day_n) always produces byte-identical mesh data.
"""

import math
import hashlib
import os
import random
import numpy as np
import trimesh

from species import SPECIES, growth_scale, apply_neighbor_discount

# PlantGL imports — available only inside the Docker container
try:
    from openalea.plantgl.all import (Scene, Shape, Material, Tesselator,
                                       TriangleSet, Polyline, Extrusion,
                                       Revolution, Vector3, Vector4)
    from openalea.plantgl.math import norm as pgl_norm
    HAS_PLANTGL = True
except ImportError:
    HAS_PLANTGL = False


class DeterministicRNG:
    """PRNG deterministically seeded from (species, seed, day_n)."""

    def __init__(self, species, seed, day_n):
        key = f"{species}:{seed}:{day_n}"
        seed_int = int(hashlib.sha256(key.encode()).hexdigest(), 16) % (2**31)
        self.rng = random.Random(seed_int)

    def uniform(self, lo, hi):
        return self.rng.uniform(lo, hi)

    def gauss(self, mu, sigma):
        return self.rng.gauss(mu, sigma)

    def choice(self, seq):
        return self.rng.choice(seq)


def _pgl_vec(x, y, z):
    return Vector3(float(x), float(y), float(z))


def _extract_mesh(scene):
    """Tessellate a PlantGL scene and return vertices + faces as numpy arrays."""
    tesselator = Tesselator()
    tri_scene = tesselator.process(scene)

    all_verts = []
    all_faces = []
    offset = 0

    for shape in tri_scene:
        geom = shape.geometry
        if not isinstance(geom, TriangleSet):
            continue
        pts = [(p.x, p.y, p.z) for p in geom.pointList]
        all_verts.extend(pts)

        for idx in geom.indexList:
            all_faces.append([offset + idx.x, offset + idx.y, offset + idx.z])
        offset += len(pts)

    if not all_verts:
        return trimesh.creation.icosphere(radius=0.01)

    return trimesh.Trimesh(
        vertices=np.array(all_verts, dtype=np.float32),
        faces=np.array(all_faces, dtype=np.uint32),
    )


def _circle_profile(radius, segments=8):
    """Return a Polyline approximating a circle in the XZ plane."""
    pts = []
    for i in range(segments):
        angle = i * 2.0 * math.pi / segments
        pts.append(_pgl_vec(math.cos(angle) * radius, 0, math.sin(angle) * radius))
    pts.append(pts[0])
    return Polyline(pts)


def _tapered_profile(bottom_radius, top_radius, height, segments=8):
    """Return a Polyline for a tapered cylinder profile."""
    pts = []
    for i in range(segments + 1):
        angle = i * 2.0 * math.pi / segments
        t = float(i) / segments
        r = bottom_radius + (top_radius - bottom_radius) * t
        pts.append(_pgl_vec(math.cos(angle) * r, t * height, math.sin(angle) * r))
    return Polyline(pts)


def build_fern(params, rng, scale):
    """Fern: central stem with compound fronds in a spiral."""
    stem_height = params.max_height * scale
    stem_radius = params.stem_radius * scale
    frond_length = params.frond_length * scale

    scene = Scene()
    stem_profile = _circle_profile(stem_radius, 8)
    stem_path = Polyline([_pgl_vec(0, 0, 0), _pgl_vec(0, stem_height, 0)])
    stem_shape = Shape(Extrusion(stem_profile, stem_path), Material())
    scene.add(stem_shape)

    frond_count = max(1, int(params.frond_count * scale))

    for i in range(frond_count):
        y = stem_height * (0.15 + 0.7 * i / max(1, frond_count - 1))
        angle = (i / frond_count) * math.pi * 2.7 + rng.gauss(0, 0.12)
        spread = params.frond_angle_spread + rng.gauss(0, 0.08)
        this_frond_len = frond_length * rng.uniform(0.85, 1.15)

        tip = _pgl_vec(
            math.cos(angle) * this_frond_len * math.sin(spread),
            y + this_frond_len * math.cos(spread),
            math.sin(angle) * this_frond_len * math.sin(spread),
        )
        start = _pgl_vec(0, y, 0)

        rachis_profile = _circle_profile(stem_radius * 0.3, 5)
        rachis_path = Polyline([start, tip])
        scene.add(Shape(Extrusion(rachis_profile, rachis_path), Material()))

        # Leaflets
        leaflet_pairs = max(2, int(params.leaflet_pairs * scale))
        leaflet_size = params.leaflet_size * scale
        direction = (tip.x - start.x, tip.y - start.y, tip.z - start.z)
        dir_len = math.sqrt(sum(d*d for d in direction))
        if dir_len == 0:
            continue
        dx, dy, dz = [d / dir_len for d in direction]
        perp_x = -dz
        perp_z = dx
        perp_len = math.sqrt(perp_x * perp_x + perp_z * perp_z)
        if perp_len > 0:
            perp_x /= perp_len
            perp_z /= perp_len

        for j in range(1, leaflet_pairs + 1):
            t = j / (leaflet_pairs + 1)
            bx = start.x + t * (tip.x - start.x)
            by = start.y + t * (tip.y - start.y)
            bz = start.z + t * (tip.z - start.z)
            half = 1.0 - 0.5 * abs(t - 0.5) * 2
            ll = leaflet_size * half * rng.uniform(0.9, 1.1)

            for sign in [1, -1]:
                lx = bx + sign * perp_x * ll
                ly = by + dy * leaflet_size * 0.3 * rng.uniform(0.8, 1.2)
                lz = bz + sign * perp_z * ll
                leaf_base = _pgl_vec(bx, by, bz)
                leaf_tip = _pgl_vec(lx, ly, lz)
                leaf_profile = _circle_profile(stem_radius * 0.06 * rng.uniform(0.7, 1.3), 4)
                leaf_path = Polyline([leaf_base, leaf_tip])
                scene.add(Shape(Extrusion(leaf_profile, leaf_path), Material()))

    return scene


def build_succulent(params, rng, scale):
    """Succulent: rosette of thick, fleshy leaves radiating from center."""
    leaf_count = max(4, int(params.leaf_count * scale))
    leaf_length = params.leaf_length * scale
    leaf_width = params.leaf_width * scale
    leaf_thickness = params.leaf_thickness * scale
    tiers = max(1, int(params.rosette_tiers * scale))
    spread = params.leaf_angle_spread

    scene = Scene()
    leaves_per_tier = max(2, leaf_count // tiers)

    for tier in range(tiers):
        t = tier / max(1, tiers - 1)
        n = leaves_per_tier
        tier_radius = leaf_length * 0.3 * t
        tier_angle = spread * (1.0 - t * 0.6)

        for j in range(n):
            rot_angle = (j / n) * math.pi * 2 + rng.uniform(-0.1, 0.1)

            base = _pgl_vec(
                math.cos(rot_angle) * tier_radius,
                tier_radius * 0.1,
                math.sin(rot_angle) * tier_radius,
            )
            tip = _pgl_vec(
                math.cos(rot_angle) * (tier_radius + leaf_length * math.sin(tier_angle)),
                leaf_length * math.cos(tier_angle),
                math.sin(rot_angle) * (tier_radius + leaf_length * math.sin(tier_angle)),
            )

            # Build a fleshy leaf with variable cross-section along its length
            leaf_dir = _pgl_vec(tip.x - base.x, tip.y - base.y, tip.z - base.z)
            leaf_len = math.sqrt(leaf_dir.x**2 + leaf_dir.y**2 + leaf_dir.z**2)
            if leaf_len == 0:
                continue

            # Cross-section: diamond shape that tapers toward tip
            nx, ny, nz = leaf_dir.x / leaf_len, leaf_dir.y / leaf_len, leaf_dir.z / leaf_len
            hw = leaf_width * 0.5
            ht = leaf_thickness * 0.5

            # Build a simple diamond profile for each cross-section along the leaf
            segments = 6
            for s_idx in range(segments):
                s = s_idx / segments
                cur_hw = hw * (1.0 - s * 0.85) * (0.8 + rng.uniform(0, 0.4))
                cur_ht = ht * (1.0 - s * 0.9) * (0.8 + rng.uniform(0, 0.4))
                cur_x = base.x + nx * leaf_len * s
                cur_y = base.y + ny * leaf_len * s
                cur_z = base.z + nz * leaf_len * s

                # Diamond cross-section in plane perpendicular to leaf direction
                diamond = Polyline([
                    _pgl_vec(cur_x + cur_hw, cur_y, cur_z),
                    _pgl_vec(cur_x, cur_y + cur_ht, cur_z),
                    _pgl_vec(cur_x - cur_hw, cur_y, cur_z),
                    _pgl_vec(cur_x, cur_y - cur_ht, cur_z),
                    _pgl_vec(cur_x + cur_hw, cur_y, cur_z),
                ])
                # Extrude diamond profile by a tiny amount along leaf direction
                mini_path = Polyline([
                    _pgl_vec(cur_x, cur_y, cur_z),
                    _pgl_vec(cur_x + nx * leaf_len * (1.0 / segments + 0.01),
                            cur_y + ny * leaf_len * (1.0 / segments + 0.01),
                            cur_z + nz * leaf_len * (1.0 / segments + 0.01)),
                ])
                scene.add(Shape(Extrusion(diamond, mini_path), Material()))

    return scene


def build_shrub(params, rng, scale):
    """Shrub: multiple stems from base with recursive branching."""
    stem_count = max(1, int(params.stem_count * scale))
    stem_radius = params.stem_radius * scale
    stem_height = params.max_height * scale * 0.7

    scene = Scene()

    for _ in range(stem_count):
        d = _pgl_vec(rng.gauss(0, 0.15), 1.0, rng.gauss(0, 0.15))
        mag = math.sqrt(d.x**2 + d.y**2 + d.z**2)
        d = _pgl_vec(d.x / mag, d.y / mag, d.z / mag)

        ox = rng.gauss(0, 0.03)
        oz = rng.gauss(0, 0.03)
        _build_shrub_branch(
            scene, _pgl_vec(ox, 0, oz), d, stem_height, stem_radius,
            params.branch_depth, params, rng, scale,
        )

    return scene


def _build_shrub_branch(scene, start, direction, length, radius, depth,
                        params, rng, scale):
    """Recursive branch building for shrub."""
    tip = _pgl_vec(
        start.x + direction.x * length,
        start.y + direction.y * length,
        start.z + direction.z * length,
    )

    profile = _circle_profile(float(radius), 6)
    path = Polyline([start, tip])
    scene.add(Shape(Extrusion(profile, path), Material()))

    if depth <= 0:
        # Add leaves at tips
        leaf_size = params.leaf_size * scale * (0.5 + rng.uniform(0, 0.5))
        density = max(1, int(params.leaf_density * scale))
        for _ in range(density):
            ld = _pgl_vec(rng.gauss(0, 0.5), rng.gauss(0.3, 0.3), rng.gauss(0, 0.5))
            mag = math.sqrt(ld.x**2 + ld.y**2 + ld.z**2)
            if mag == 0:
                continue
            ld = _pgl_vec(ld.x / mag, ld.y / mag, ld.z / mag)
            leaf_tip = _pgl_vec(
                tip.x + ld.x * leaf_size,
                tip.y + ld.y * leaf_size,
                tip.z + ld.z * leaf_size,
            )
            leaf_profile = _circle_profile(float(radius) * 0.15, 4)
            leaf_path = Polyline([tip, leaf_tip])
            scene.add(Shape(Extrusion(leaf_profile, leaf_path), Material()))
        return

    branch_count = rng.choice([2, 2, 3])
    for _ in range(branch_count):
        cd = _pgl_vec(
            direction.x + rng.gauss(0, params.branch_angle_spread),
            direction.y + rng.uniform(0.1, 0.5),
            direction.z + rng.gauss(0, params.branch_angle_spread),
        )
        mag = math.sqrt(cd.x**2 + cd.y**2 + cd.z**2)
        cd = _pgl_vec(cd.x / mag, cd.y / mag, cd.z / mag)

        child_len = length * params.branch_length_factor * rng.uniform(0.8, 1.2)
        child_radius = radius * 0.55
        _build_shrub_branch(
            scene, tip, cd, child_len, child_radius,
            depth - 1, params, rng, scale,
        )


BUILDERS = {
    "fern": build_fern,
    "succulent": build_succulent,
    "shrub": build_shrub,
}


def generate(species, seed, day_n, neighbor_state=None):
    """
    Deterministic plant mesh generator using PlantGL geometry.

    Args:
        species: str, one of SPECIES keys
        seed: int, genetic seed
        day_n: int, days since planting
        neighbor_state: dict or None, canopy overlap info

    Returns:
        dict: mesh (trimesh.Trimesh), vertices, faces, height, canopy_radius
    """
    if not HAS_PLANTGL:
        raise ImportError("PlantGL not available. Run inside the Docker container.")

    if species not in SPECIES:
        raise ValueError(f"Unknown species '{species}'. Known: {list(SPECIES.keys())}")

    params = SPECIES[species]
    rng = DeterministicRNG(species, seed, day_n)

    scale = growth_scale(params, day_n)
    scale = apply_neighbor_discount(scale, neighbor_state)

    builder = BUILDERS[species]
    scene = builder(params, rng, scale)

    mesh = _extract_mesh(scene)

    return {
        "mesh": mesh,
        "vertices": int(len(mesh.vertices)),
        "faces": int(len(mesh.faces)),
        "height": float(params.max_height * scale),
        "canopy_radius": float(params.get_canopy_radius(
            neighbor_state.get("canopy_override") if neighbor_state else None
        ) * scale),
    }


# ── trimesh fallback (used when PlantGL is not available) ──

def _cylinder_between(start, end, radius, sections=8):
    """trimesh cylinder between two 3D points."""
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


def _build_fern_tm(params, rng, scale):
    stem_h = params.max_height * scale
    sr = params.stem_radius * scale
    fl = params.frond_length * scale
    ls = params.leaflet_size * scale
    meshes = [_cylinder_between([0, 0, 0], [0, stem_h, 0], sr, 6)]
    fc = max(1, int(params.frond_count * scale))
    for i in range(fc):
        y = stem_h * (0.15 + 0.7 * i / max(1, fc - 1))
        angle = (i / fc) * math.pi * 2.7 + rng.gauss(0, 0.12)
        spread = params.frond_angle_spread + rng.gauss(0, 0.08)
        tfl = fl * rng.uniform(0.85, 1.15)
        tip = np.array([math.cos(angle) * tfl * math.sin(spread),
                        y + tfl * math.cos(spread),
                        math.sin(angle) * tfl * math.sin(spread)])
        start = np.array([0, y, 0])
        meshes.append(_cylinder_between(start, tip, sr * 0.3, 4))
        lps = max(2, int(params.leaflet_pairs * scale))
        for j in range(1, lps + 1):
            t = j / (lps + 1)
            base = start + t * (tip - start)
            d = tip - start; d = d / (np.linalg.norm(d) + 1e-8)
            perp = np.array([-d[2], 0, d[0]]); perp = perp / (np.linalg.norm(perp) + 1e-8)
            ll = ls * (1.0 - 0.5 * abs(t - 0.5) * 2) * rng.uniform(0.9, 1.1)
            lw = ls * 0.25 * rng.uniform(0.8, 1.2)
            for sgn in [1, -1]:
                jit = np.array([rng.gauss(0, 0.002), rng.gauss(0, 0.003), rng.gauss(0, 0.002)])
                lt = base + sgn * perp * ll + d * lw + jit
                meshes.append(_cylinder_between(base, lt, sr * 0.08 * rng.uniform(0.8, 1.2), 3))
    return trimesh.util.concatenate(meshes)


def _build_succulent_tm(params, rng, scale):
    lc = max(4, int(params.leaf_count * scale))
    ll = params.leaf_length * scale
    lw = params.leaf_width * scale
    lt = params.leaf_thickness * scale
    tiers = max(1, int(params.rosette_tiers * scale))
    spread = params.leaf_angle_spread
    meshes = []
    for tier in range(tiers):
        t = tier / max(1, tiers - 1)
        n = lc // tiers
        tr = ll * 0.3 * t
        ta = spread * (1.0 - t * 0.6)
        for j in range(n):
            ra = (j / n) * math.pi * 2 + rng.uniform(-0.1, 0.1)
            lb = np.array([math.cos(ra) * tr, tr * 0.1, math.sin(ra) * tr])
            lt2 = np.array([math.cos(ra) * (tr + ll * math.sin(ta)),
                           ll * math.cos(ta),
                           math.sin(ra) * (tr + ll * math.sin(ta))])
            lm = lb + (lt2 - lb) * 0.5 + np.array([0, lt * 0.3, 0])
            perp = np.cross(lt2 - lb, [0, 1, 0])
            perp = perp / (np.linalg.norm(perp) + 1e-8) * lw * 0.5
            verts = np.array([lb, lm + perp, lt2, lm - perp])
            faces = np.array([[0, 1, 2], [0, 2, 3], [0, 3, 1], [1, 3, 2]])
            meshes.append(trimesh.Trimesh(vertices=verts, faces=faces))
    return trimesh.util.concatenate(meshes)


def _build_shrub_tm(params, rng, scale):
    sc = max(1, int(params.stem_count * scale))
    sr2 = params.stem_radius * scale
    sh2 = params.max_height * scale * 0.7
    def _branch(start, direction, length, radius, depth):
        end = start + direction * length
        meshes = [_cylinder_between(start, end, radius, 5)]
        if depth <= 0:
            ls2 = params.leaf_size * scale * (0.5 + rng.uniform(0, 0.5))
            dens = max(1, int(params.leaf_density * scale))
            for _ in range(dens):
                ld = np.array([rng.gauss(0, 0.5), rng.gauss(0.3, 0.3), rng.gauss(0, 0.5)])
                ld = ld / (np.linalg.norm(ld) + 1e-8)
                lt3 = end + ld * ls2
                meshes.append(_cylinder_between(end, lt3, radius * 0.15, 3))
            return trimesh.util.concatenate(meshes)
        bc = rng.choice([2, 2, 3])
        for _ in range(bc):
            cd = direction + np.array([rng.gauss(0, params.branch_angle_spread),
                                       rng.uniform(0.1, 0.5),
                                       rng.gauss(0, params.branch_angle_spread)])
            cd = cd / np.linalg.norm(cd)
            cl = length * params.branch_length_factor
            cr = radius * 0.55
            meshes.append(_branch(end, cd, cl, cr, depth - 1))
        return trimesh.util.concatenate(meshes)
    meshes = []
    for _ in range(sc):
        d = np.array([rng.gauss(0, 0.15), 1.0, rng.gauss(0, 0.15)])
        d = d / np.linalg.norm(d)
        off = np.array([rng.gauss(0, 0.03), 0.0, rng.gauss(0, 0.03)])
        meshes.append(_branch(off, d, sh2, sr2, params.branch_depth))
    return trimesh.util.concatenate(meshes)


TM_BUILDERS = {
    "fern": _build_fern_tm,
    "succulent": _build_succulent_tm,
    "shrub": _build_shrub_tm,
}


def generate_fallback(species, seed, day_n, neighbor_state=None):
    """Trimesh-based fallback generator (used when PlantGL not available)."""
    if species not in SPECIES:
        raise ValueError(f"Unknown species '{species}'.")
    params = SPECIES[species]
    rng = DeterministicRNG(species, seed, day_n)
    scale = growth_scale(params, day_n)
    scale = apply_neighbor_discount(scale, neighbor_state)
    mesh = TM_BUILDERS[species](params, rng, scale)
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


# ── smart dispatch ──

_USE_PLANTGL = HAS_PLANTGL and (os.environ.get("PLANTGL_FALLBACK", "").lower() != "true")

if not _USE_PLANTGL:
    generate = generate_fallback
