"""Tests for the L-Py backend (skipped when lpy is unavailable)."""

import sys
import os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import generate
import species as sp

HAS_LPY = generate.HAS_LPY
HAS_PLANTGL = generate.HAS_PLANTGL

pytestmark = pytest.mark.skipif(
    not HAS_LPY or not HAS_PLANTGL,
    reason="L-Py / PlantGL not available in this environment",
)

ALL_SPECIES = list(sp.SPECIES.keys())


class TestLpyContext:
    @pytest.mark.parametrize("species_name", ALL_SPECIES)
    def test_context_has_seed_and_scaled_params(self, species_name):
        params = sp.SPECIES[species_name]
        ctx = generate.lpy_context(species_name, params, 42, 0.5)
        assert ctx["SEED"] == 42
        assert len(ctx) > 3  # more than just SEED

    @pytest.mark.parametrize("species_name", ALL_SPECIES)
    def test_context_deterministic(self, species_name):
        params = sp.SPECIES[species_name]
        c1 = generate.lpy_context(species_name, params, 42, 0.5)
        c2 = generate.lpy_context(species_name, params, 42, 0.5)
        assert c1 == c2

    @pytest.mark.parametrize("species_name", ALL_SPECIES)
    def test_scale_affects_values(self, species_name):
        params = sp.SPECIES[species_name]
        small = generate.lpy_context(species_name, params, 42, 0.2)
        large = generate.lpy_context(species_name, params, 42, 0.9)
        for key in small:
            if key == "SEED":
                continue
            if isinstance(small[key], (int, float)) and isinstance(large[key], (int, float)):
                assert large[key] >= small[key], f"{species_name}: {key} not scaled"


class TestLpyScene:
    @pytest.mark.parametrize("species_name", ALL_SPECIES)
    def test_scene_builds(self, species_name):
        params = sp.SPECIES[species_name]
        scene = generate.build_lpy_scene(species_name, params, 42, 0.8)
        assert scene is not None
        assert len(scene) > 0

    @pytest.mark.parametrize("species_name", ALL_SPECIES)
    def test_generate_deterministic(self, species_name):
        r1 = generate.generate(species_name, 42, 60)
        r2 = generate.generate(species_name, 42, 60)
        assert r1["vertices"] == r2["vertices"]
        assert r1["faces"] == r2["faces"]

    @pytest.mark.parametrize("species_name", ALL_SPECIES)
    def test_generate_uses_lpy_scene_not_fallback(self, species_name):
        """Mesh should be larger than the 642-vert fallback sphere."""
        r = generate.generate(species_name, 42, 60)
        assert r["vertices"] != 642, f"{species_name}: fallback sphere used, L-Py not active"

    def test_different_seeds_diverge(self):
        a = generate.generate("fern", 42, 60)["mesh"].vertices
        b = generate.generate("fern", 43, 60)["mesh"].vertices
        assert not (a == b).all()

    def test_overrides_flow_into_lpy(self):
        r_default = generate.generate("fern", 42, 60)
        r_tall = generate.generate("fern", 42, 60, overrides={"max_height": 1.5})
        assert r_tall["height"] > r_default["height"]

    def test_struct_override_changes_mesh(self):
        r_default = generate.generate("fern", 42, 60)
        r_more = generate.generate("fern", 42, 60,
                                   overrides={"frond_count": 15, "leaflet_pairs": 20})
        assert r_more["vertices"] != r_default["vertices"]
