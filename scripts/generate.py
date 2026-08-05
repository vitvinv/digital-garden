"""
Deterministic procedural plant mesh generation using PlantGL.

generate(species, seed, day_n, neighbor_state) -> dict
  Uses PlantGL for semi-realistic plant geometry (extrusions, revolutions).
  Same (species, seed, day_n) always produces byte-identical mesh data.
"""

import math
import hashlib
import json
import os
import random
import numpy as np
import trimesh

from species import SPECIES, growth_scale, apply_neighbor_discount, apply_overrides

# ── PlantGL imports (available inside Docker container) ──

try:
    from openalea.plantgl.all import (
        Scene, Shape, Material, Discretizer,
        TriangleSet, QuadSet, FaceSet, Extrusion, Revolution, Frustum,
        Cylinder, Sphere, Translated, AxisRotated,
        Polyline, Polyline2D, BezierCurve, BezierCurve2D,
        Vector3, Vector2, Group,
    )
    from openalea.plantgl.math import norm as pgl_norm
    try:
        from openalea.plantgl.all import discretize
        HAS_DISCRETIZE = True
    except ImportError:
        HAS_DISCRETIZE = False
    HAS_PLANTGL = True
except ImportError:
    HAS_PLANTGL = False
    HAS_DISCRETIZE = False


class DeterministicRNG:
    """PRNG deterministically seeded from (species, seed, day_n, overrides)."""

    def __init__(self, species, seed, day_n, overrides=None):
        key = f"{species}:{seed}:{day_n}:{_overrides_key(overrides)}"
        seed_int = int(hashlib.sha256(key.encode()).hexdigest(), 16) % (2**31)
        self.rng = random.Random(seed_int)

    def uniform(self, lo, hi):
        return self.rng.uniform(lo, hi)

    def gauss(self, mu, sigma):
        return self.rng.gauss(mu, sigma)

    def choice(self, seq):
        return self.rng.choice(seq)


def _overrides_key(overrides):
    """Canonical string for an overrides dict (deterministic ordering)."""
    if not overrides:
        return ""
    return json.dumps(overrides, sort_keys=True, separators=(",", ":"))


def _vec3(x, y, z):
    return Vector3(float(x), float(y), float(z))


def _vec2(x, y):
    return Vector2(float(x), float(y))


def _circle_profile(radius, segments=16):
    """Create a 2D circle profile for extrusions/revolutions."""
    return Polyline2D.Circle(float(radius), segments)


def _line_path(start, end):
    """Create a 3D path from start to end."""
    return Polyline([_vec3(*start), _vec3(*end)])


def _split_index(idx):
    """Return list of ints from an Index3/Index4/Index polygon (via str repr)."""
    s = str(idx)
    start = s.find("[")
    if start < 0:
        start = s.find("(")
    end = s.rfind("]")
    if end < 0:
        end = s.rfind(")")
    return [int(x) for x in s[start + 1:end].replace(" ", "").split(",")]


def _append_faces(all_faces, offset, vals):
    """Append triangulated faces for a polygon (fan triangulation)."""
    if len(vals) == 3:
        all_faces.append([offset + vals[0], offset + vals[1], offset + vals[2]])
    elif len(vals) >= 4:
        for i in range(1, len(vals) - 1):
            all_faces.append([offset + vals[0], offset + vals[i], offset + vals[i + 1]])


def _extract_mesh(scene):
    """
    Discretize a PlantGL scene and return a trimesh.Trimesh.

    Uses pgl.discretize(geometry) per shape — works on PlantGL versions
    where scene.apply(Discretizer()) does not convert in place (e.g. 3.21.x).
    Handles TriangleSet, QuadSet and FaceSet output (fan-triangulated).
    """
    all_verts = []
    all_faces = []
    offset = 0

    for shape in scene:
        if HAS_DISCRETIZE:
            tri = discretize(shape.geometry)
        else:
            tri = shape.geometry
        if not isinstance(tri, (TriangleSet, QuadSet, FaceSet)):
            continue
        pts = [(p.x, p.y, p.z) for p in tri.pointList]
        all_verts.extend(pts)

        for idx in tri.indexList:
            vals = _split_index(idx)
            _append_faces(all_faces, offset, vals)
        offset += len(pts)

    if not all_verts:
        return trimesh.creation.icosphere(radius=0.01)

    return trimesh.Trimesh(
        vertices=np.array(all_verts, dtype=np.float32),
        faces=np.array(all_faces, dtype=np.uint32),
    )


def _stem_shape(start, end, radius, segments=12):
    """Create a cylinder-like stem between two 3D points."""
    path = _line_path(start, end)
    profile = _circle_profile(float(radius), segments)
    return Shape(Extrusion(path, profile), Material())


def build_fern(params, rng, scale):
    """Fern: central stem with compound fronds in a spiral."""
    stem_height = params.max_height * scale
    stem_radius = params.stem_radius * scale
    frond_length = params.frond_length * scale

    scene = Scene()
    scene.add(_stem_shape((0, 0, 0), (0, stem_height, 0), stem_radius, 12))

    frond_count = max(1, int(params.frond_count * scale))

    for i in range(frond_count):
        y = stem_height * (0.15 + 0.7 * i / max(1, frond_count - 1))
        angle = (i / frond_count) * math.pi * 2.7 + rng.gauss(0, 0.12)
        spread = params.frond_angle_spread + rng.gauss(0, 0.08)
        this_fl = frond_length * rng.uniform(0.85, 1.15)

        tip = (
            math.cos(angle) * this_fl * math.sin(spread),
            y + this_fl * math.cos(spread),
            math.sin(angle) * this_fl * math.sin(spread),
        )
        start = (0, y, 0)

        # Rachis as thin stem
        scene.add(_stem_shape(start, tip, stem_radius * 0.25, 8))

        # Leaflets along rachis
        leaflet_pairs = max(2, int(params.leaflet_pairs * scale))
        leaflet_size = params.leaflet_size * scale

        sx, sy, sz = start
        tx, ty, tz = tip
        dx, dy, dz = tx - sx, ty - sy, tz - sz
        dlen = math.sqrt(dx * dx + dy * dy + dz * dz)
        if dlen < 1e-8:
            continue
        dx, dy, dz = dx / dlen, dy / dlen, dz / dlen

        perp_x = -dz
        perp_z = dx
        perp_len = math.sqrt(perp_x * perp_x + perp_z * perp_z)
        if perp_len > 0:
            perp_x /= perp_len
            perp_z /= perp_len

        for j in range(1, leaflet_pairs + 1):
            t = j / (leaflet_pairs + 1)
            bx = sx + t * (tx - sx)
            by = sy + t * (ty - sy)
            bz = sz + t * (tz - sz)
            half = 1.0 - 0.5 * abs(t - 0.5) * 2
            ll = leaflet_size * half * rng.uniform(0.9, 1.1)

            for sign in [1, -1]:
                lx = bx + sign * perp_x * ll
                ly = by + dy * leaflet_size * 0.3 * rng.uniform(0.8, 1.2)
                lz = bz + sign * perp_z * ll
                leaflet_path = _line_path((bx, by, bz), (lx, ly, lz))
                lr = stem_radius * 0.06 * rng.uniform(0.7, 1.3)
                scene.add(Shape(Extrusion(leaflet_path, _circle_profile(lr, 4)), Material()))

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
        ti = tier / max(1, tiers - 1)
        n = leaves_per_tier
        tier_radius = leaf_length * 0.3 * ti
        tier_angle = spread * (1.0 - ti * 0.6)

        for j in range(n):
            rot_angle = (j / n) * math.pi * 2 + rng.uniform(-0.1, 0.1)

            base = (
                math.cos(rot_angle) * tier_radius,
                tier_radius * 0.1,
                math.sin(rot_angle) * tier_radius,
            )
            tip = (
                math.cos(rot_angle) * (tier_radius + leaf_length * math.sin(tier_angle)),
                leaf_length * math.cos(tier_angle),
                math.sin(rot_angle) * (tier_radius + leaf_length * math.sin(tier_angle)),
            )
            mid = (
                (base[0] + tip[0]) / 2,
                (base[1] + tip[1]) / 2 + leaf_thickness * 0.4,
                (base[2] + tip[2]) / 2,
            )

            # Build a fleshy leaf using a 3-point 2D profile + Revolution
            profile_2d = Polyline2D([
                _vec2(0, 0),
                _vec2(leaf_width * 0.5, leaf_thickness * 0.3),
                _vec2(0, leaf_length),
                _vec2(-leaf_width * 0.5, leaf_thickness * 0.3),
                _vec2(0, 0),
            ])

            # Revolution of the 2D profile creates a rotationally symmetric shape.
            # Scale it to be flat (squash Z) and orient it correctly.
            rev_geom = Revolution(profile_2d, slices=8)

            # Build the leaf geometry: a tapered frustum from base to tip
            # Use Frustum for a tapered triangular shape
            leaf_path = _line_path(base, tip)
            base_r = leaf_width * 0.5 * rng.uniform(0.8, 1.2)
            tip_r = leaf_width * 0.05 * rng.uniform(0.5, 1.5)

            # Create the leaf as a tapered extrusion
            leaf_geom = Frustum(
                radius=float(base_r),
                height=float(leaf_length),
                taper=float(tip_r / max(base_r, 0.001)),
                slices=8,
            )
            # Position and orient the leaf
            positioned = Translated(*base, leaf_geom)
            # Orient toward tip direction
            dx = tip[0] - base[0]
            dy = tip[1] - base[1]
            dz = tip[2] - base[2]
            dlen = math.sqrt(dx * dx + dy * dy + dz * dz)
            if dlen > 0:
                axis = _vec3(-dz, 0, dx)  # perpendicular
                axis_len = math.sqrt(axis.x**2 + axis.z**2)
                if axis_len > 0:
                    axis = _vec3(axis.x / axis_len, 0, axis.z / axis_len)
                    angle = math.acos(max(-1, min(1, dy / dlen)))
                    positioned = AxisRotated(axis, float(angle), positioned)

            scene.add(Shape(positioned, Material()))

    return scene


def build_shrub(params, rng, scale):
    """Shrub: multiple stems from base with recursive branching."""
    stem_count = max(1, int(params.stem_count * scale))
    stem_radius = params.stem_radius * scale
    stem_height = params.max_height * scale * 0.7

    scene = Scene()

    for _ in range(stem_count):
        dx = rng.gauss(0, 0.15)
        dz = rng.gauss(0, 0.15)
        mag = math.sqrt(dx * dx + 1.0 + dz * dz)
        d = (dx / mag, 1.0 / mag, dz / mag)
        ox = rng.gauss(0, 0.03)
        oz = rng.gauss(0, 0.03)
        _build_shrub_branch(scene, (ox, 0, oz), d, stem_height, stem_radius,
                            params.branch_depth, params, rng, scale)

    return scene


def _build_shrub_branch(scene, start, direction, length, radius, depth,
                        params, rng, scale):
    """Recursive branch building for shrub using PlantGL primitives."""
    sx, sy, sz = start
    dx, dy, dz = direction
    tx = sx + dx * length
    ty = sy + dy * length
    tz = sz + dz * length
    tip = (tx, ty, tz)

    scene.add(_stem_shape(start, tip, float(radius), 8))

    if depth <= 0:
        leaf_size = params.leaf_size * scale * (0.5 + rng.uniform(0, 0.5))
        density = max(1, int(params.leaf_density * scale))
        for _ in range(density):
            ldx = rng.gauss(0, 0.5)
            ldy = rng.gauss(0.3, 0.3)
            ldz = rng.gauss(0, 0.5)
            lm = math.sqrt(ldx * ldx + ldy * ldy + ldz * ldz)
            if lm < 1e-8:
                continue
            ldx /= lm; ldy /= lm; ldz /= lm
            leaf_tip = (tx + ldx * leaf_size, ty + ldy * leaf_size, tz + ldz * leaf_size)
            scene.add(_stem_shape(tip, leaf_tip, float(radius) * 0.12, 4))
        return

    branch_count = rng.choice([2, 2, 3])
    for _ in range(branch_count):
        cdx = dx + rng.gauss(0, params.branch_angle_spread)
        cdy = dy + rng.uniform(0.1, 0.5)
        cdz = dz + rng.gauss(0, params.branch_angle_spread)
        cm = math.sqrt(cdx * cdx + cdy * cdy + cdz * cdz)
        cd = (cdx / cm, cdy / cm, cdz / cm)
        child_len = length * params.branch_length_factor * rng.uniform(0.8, 1.2)
        child_radius = radius * 0.55
        _build_shrub_branch(scene, tip, cd, child_len, child_radius,
                            depth - 1, params, rng, scale)


BUILDERS = {
    "fern": build_fern,
    "succulent": build_succulent,
    "shrub": build_shrub,
}


def build_plant_scene(species, seed, day_n, neighbor_state=None, overrides=None):
    """
    Build a PlantGL Scene for one plant (deterministic, no tessellation).

    Used by generate() and by the Plant Designer for real-time preview.
    overrides: dict of species attribute overrides, or None.
    """
    if not HAS_PLANTGL:
        raise ImportError("PlantGL not available. Run inside the Docker container.")

    if species not in SPECIES:
        raise ValueError(f"Unknown species '{species}'. Known: {list(SPECIES.keys())}")

    params = apply_overrides(SPECIES[species], overrides)
    rng = DeterministicRNG(species, seed, day_n, overrides)

    scale = growth_scale(params, day_n)
    scale = apply_neighbor_discount(scale, neighbor_state)

    builder = BUILDERS[species]
    scene = builder(params, rng, scale)
    return scene, params, scale


def generate(species, seed, day_n, neighbor_state=None, overrides=None):
    """Deterministic plant mesh generator using PlantGL geometry."""
    scene, params, scale = build_plant_scene(species, seed, day_n,
                                             neighbor_state, overrides)

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


def generate_fallback(species, seed, day_n, neighbor_state=None, overrides=None):
    """Trimesh-based fallback generator."""
    if species not in SPECIES:
        raise ValueError(f"Unknown species '{species}'.")
    params = apply_overrides(SPECIES[species], overrides)
    rng = DeterministicRNG(species, seed, day_n, overrides)
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


_USE_PLANTGL = HAS_PLANTGL and (os.environ.get("PLANTGL_FALLBACK", "").lower() != "true")

if not _USE_PLANTGL:
    generate = generate_fallback
