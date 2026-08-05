"""Tests for deterministic plant mesh generation."""

import sys
import os
import json
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import numpy as np
import species
import generate


SEEDS = [0, 42, 999]
DAYS = [1, 7, 30, 90, 180]
ALL_SPECIES = list(species.SPECIES.keys())


class TestGrowthCurve:
    def test_day_zero_returns_tiny(self):
        for name, params in species.SPECIES.items():
            s = species.growth_scale(params, 0)
            assert s < 0.1, f"{name} at day 0 should be tiny, got {s}"

    def test_growth_monotonic(self):
        for name, params in species.SPECIES.items():
            prev = 0
            for d in range(0, 365, 10):
                s = species.growth_scale(params, d)
                assert s >= prev, f"{name} growth not monotonic at day {d}"
                prev = s

    def test_day_negative_capped(self):
        for name, params in species.SPECIES.items():
            s = species.growth_scale(params, -5)
            assert s < 0.1, f"{name} at negative day should be tiny"

    def test_maturity_near_one(self):
        for name, params in species.SPECIES.items():
            s = species.growth_scale(params, 365 * 10)
            assert 0.95 < s <= 1.0, f"{name} should be near 1.0 at old age, got {s}"


class TestDeterministicRNG:
    def test_same_seed_same_sequence(self):
        rng1 = generate.DeterministicRNG("fern", 42, 30)
        rng2 = generate.DeterministicRNG("fern", 42, 30)

        seq1 = [rng1.uniform(0, 1) for _ in range(100)]
        seq2 = [rng2.uniform(0, 1) for _ in range(100)]
        assert seq1 == seq2

    def test_different_seed_different_sequence(self):
        rng1 = generate.DeterministicRNG("fern", 42, 30)
        rng2 = generate.DeterministicRNG("fern", 43, 30)

        seq1 = [rng1.uniform(0, 1) for _ in range(50)]
        seq2 = [rng2.uniform(0, 1) for _ in range(50)]
        assert seq1 != seq2

    def test_different_day_different_sequence(self):
        rng1 = generate.DeterministicRNG("fern", 42, 30)
        rng2 = generate.DeterministicRNG("fern", 42, 31)

        seq1 = [rng1.uniform(0, 1) for _ in range(50)]
        seq2 = [rng2.uniform(0, 1) for _ in range(50)]
        assert seq1 != seq2

    def test_different_species_different_sequence(self):
        rng1 = generate.DeterministicRNG("fern", 42, 30)
        rng2 = generate.DeterministicRNG("succulent", 42, 30)

        seq1 = [rng1.uniform(0, 1) for _ in range(50)]
        seq2 = [rng2.uniform(0, 1) for _ in range(50)]
        assert seq1 != seq2


class TestGenerateDeterminism:
    @pytest.mark.parametrize("species_name", ALL_SPECIES)
    @pytest.mark.parametrize("seed", SEEDS)
    @pytest.mark.parametrize("day", DAYS)
    def test_idempotent(self, species_name, seed, day):
        """Same inputs produce byte-identical vertex data."""
        r1 = generate.generate(species_name, seed, day)
        r2 = generate.generate(species_name, seed, day)

        assert len(r1["mesh"].vertices) == len(r2["mesh"].vertices)
        assert len(r1["mesh"].faces) == len(r2["mesh"].faces)
        assert r1["vertices"] == r2["vertices"]
        assert r1["faces"] == r2["faces"]
        assert np.allclose(r1["mesh"].vertices, r2["mesh"].vertices)
        assert np.array_equal(r1["mesh"].faces, r2["mesh"].faces)

    @pytest.mark.parametrize("species_name", ALL_SPECIES)
    def test_different_seed_divergent(self, species_name):
        """Different seeds at same day produce different meshes."""
        r1 = generate.generate(species_name, 10, 60)
        r2 = generate.generate(species_name, 99, 60)

        v1 = r1["mesh"].vertices
        v2 = r2["mesh"].vertices
        if len(v1) != len(v2):
            diff = True  # different vertex counts -> different meshes
        else:
            diff = not np.allclose(v1, v2)
        assert diff, f"{species_name}: different seeds should produce different meshes"


class TestGenerateGrowth:
    @pytest.mark.parametrize("species_name", ALL_SPECIES)
    def test_larger_plant_at_later_day(self, species_name):
        """Plant at day 90 is larger than at day 7."""
        r_early = generate.generate(species_name, 42, 7)
        r_late = generate.generate(species_name, 42, 90)

        assert r_late["height"] > r_early["height"], \
            f"{species_name}: height at day 90 ({r_late['height']:.3f}) <= day 7 ({r_early['height']:.3f})"
        assert r_late["vertices"] >= r_early["vertices"], \
            f"{species_name}: vertices at day 90 ({r_late['vertices']}) < day 7 ({r_early['vertices']})"


class TestNeighborDiscount:
    def test_no_neighbor_full_growth(self):
        r = generate.generate("fern", 42, 60, neighbor_state=None)
        assert r["height"] > 0.1

    def test_zero_overlap_full_growth(self):
        r = generate.generate("fern", 42, 60, neighbor_state={"total_overlap": 0.0})
        assert r["height"] > 0.1

    def test_full_overlap_reduced_growth(self):
        r = generate.generate("fern", 42, 60, neighbor_state={"total_overlap": 1.0})
        r_ref = generate.generate("fern", 42, 60, neighbor_state=None)
        assert r["height"] < r_ref["height"], "Full overlap should reduce height"

    def test_overlap_cannot_reduce_below_10_percent(self):
        r = generate.generate("fern", 42, 60, neighbor_state={"total_overlap": 1.0})
        r_min = generate.generate("fern", 42, 60, neighbor_state={"total_overlap": 0.0})
        assert r["height"] >= r_min["height"] * 0.09  # ~10% floor


class TestCanopyRadius:
    def test_species_default(self):
        for name, params in species.SPECIES.items():
            assert params.get_canopy_radius() == params.max_canopy_radius

    def test_override(self):
        assert species.SPECIES["fern"].get_canopy_radius(0.8) == 0.8

    def test_ignore_zero_override(self):
        assert species.SPECIES["fern"].get_canopy_radius(0.0) == species.SPECIES["fern"].max_canopy_radius


class TestErrors:
    def test_unknown_species_raises(self):
        with pytest.raises(ValueError, match="Unknown species"):
            generate.generate("dragon_tree", 42, 30)

    def test_empty_result_returns_sphere(self):
        """If mesh generation produces empty, we get a tiny sphere (not crash)."""
        r = generate.generate("fern", 42, 0)
        assert r["mesh"].vertices.size > 0
