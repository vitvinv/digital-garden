"""Tests for parameter overrides (Plant Designer feature)."""

import sys
import os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import species
import generate

ALL_SPECIES = list(species.SPECIES.keys())


class TestApplyOverrides:
    def test_none_returns_same_object(self):
        params = species.SPECIES["fern"]
        assert species.apply_overrides(params, None) is params

    def test_empty_dict_returns_same_object(self):
        params = species.SPECIES["fern"]
        assert species.apply_overrides(params, {}) is params

    def test_changes_attribute(self):
        params = species.apply_overrides(species.SPECIES["fern"], {"max_height": 1.2})
        assert params.max_height == pytest.approx(1.2)

    def test_original_not_mutated(self):
        original = species.SPECIES["fern"]
        species.apply_overrides(original, {"max_height": 1.2})
        assert original.max_height == pytest.approx(0.8)

    def test_unknown_attribute_ignored(self):
        params = species.apply_overrides(species.SPECIES["fern"], {"nonexistent": 5})
        assert not hasattr(params, "nonexistent")


class TestGenerateOverrides:
    @pytest.mark.parametrize("species_name", ALL_SPECIES)
    def test_overrides_deterministic(self, species_name):
        """Same overrides → identical mesh."""
        ov = {"max_height": 1.1, "growth_midpoint": 90.0}
        r1 = generate.generate(species_name, 42, 60, overrides=ov)
        r2 = generate.generate(species_name, 42, 60, overrides=ov)
        assert r1["vertices"] == r2["vertices"]
        assert r1["faces"] == r2["faces"]
        assert r1["height"] == pytest.approx(r2["height"])

    @pytest.mark.parametrize("species_name", ALL_SPECIES)
    def test_overrides_change_mesh(self, species_name):
        """Different overrides → different plant (at least height differs)."""
        r_default = generate.generate(species_name, 42, 60)
        r_tall = generate.generate(species_name, 42, 60, overrides={"max_height": 2.0})
        assert r_tall["height"] > r_default["height"]

    @pytest.mark.parametrize("species_name", ALL_SPECIES)
    def test_no_overrides_same_as_before(self, species_name):
        """overrides=None must behave exactly like the original call."""
        r1 = generate.generate(species_name, 42, 60, overrides=None)
        r2 = generate.generate(species_name, 42, 60)
        assert r1["vertices"] == r2["vertices"]
        assert r1["height"] == pytest.approx(r2["height"])


class TestDesignParams:
    @pytest.mark.parametrize("species_name", ALL_SPECIES)
    def test_all_attributes_exist(self, species_name):
        params = species.SPECIES[species_name]
        for attr, _label, _lo, _hi, _step in species.DESIGN_PARAMS[species_name]:
            assert hasattr(params, attr), f"{species_name}: unknown attr '{attr}'"

    @pytest.mark.parametrize("species_name", ALL_SPECIES)
    def test_ranges_valid(self, species_name):
        for attr, _label, lo, hi, step in species.DESIGN_PARAMS[species_name]:
            assert lo < hi, f"{species_name}: bad range for {attr}"
            assert step > 0, f"{species_name}: bad step for {attr}"

    def test_every_species_has_schema(self):
        assert set(species.DESIGN_PARAMS.keys()) == set(species.SPECIES.keys())
