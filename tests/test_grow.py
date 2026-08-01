"""Tests for grow.py — config parsing, day_n computation, neighbor overlap."""

import sys
import os
import json
import tempfile
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import grow
import generate
import species as sp


class TestComputeDayN:
    def test_today_minus_planted(self):
        d = grow.compute_day_n("2026-07-01", today=date(2026, 8, 1))
        assert d == 31

    def test_zero_days(self):
        d = grow.compute_day_n("2026-08-01", today=date(2026, 8, 1))
        assert d == 0

    def test_future_date_zero(self):
        d = grow.compute_day_n("2026-09-01", today=date(2026, 8, 1))
        assert d == 0

    def test_negative_days_clamped(self):
        d = grow.compute_day_n("2027-01-01", today=date(2026, 8, 1))
        assert d == 0


class TestNeighborState:
    def test_single_plant_no_neighbors(self):
        plants = [{"planted_date": "2026-06-01", "species": "fern", "position": [0, 0, 0]}]
        ns = grow.compute_neighbor_state(plants[0], plants)
        assert ns is None

    def test_two_far_plants_no_overlap(self):
        plants = [
            {"planted_date": "2026-06-01", "species": "fern", "position": [0, 0, 0]},
            {"planted_date": "2026-06-01", "species": "shrub", "position": [5, 0, 5]},
        ]
        ns = grow.compute_neighbor_state(plants[0], plants)
        assert ns is None

    def test_two_close_plants_overlap(self):
        plants = [
            {"planted_date": "2026-06-01", "species": "fern", "position": [0, 0, 0]},
            {"planted_date": "2026-06-01", "species": "fern", "position": [0.1, 0, 0]},
        ]
        ns = grow.compute_neighbor_state(plants[0], plants)
        assert ns is not None
        assert ns["total_overlap"] > 0
        assert ns["neighbor_count"] == 1


class TestLoadConfig:
    def test_valid_config(self):
        cfg = {"gardens": {"test": {"image_target": "test", "plants": []}}}
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(cfg, f)
            path = f.name
        try:
            result = grow.load_config(path)
            assert result == cfg
        finally:
            os.unlink(path)

    def test_missing_gardens_key(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({}, f)
            path = f.name
        try:
            with pytest.raises(ValueError, match="gardens"):
                grow.load_config(path)
        finally:
            os.unlink(path)


class TestGrowIdempotency:
    def test_grow_twice_same_output(self):
        """Running generate() twice for the same plant produces identical results."""
        r1 = generate.generate("fern", 42, 30)
        r2 = generate.generate("fern", 42, 30)
        assert r1["vertices"] == r2["vertices"]
        assert r1["faces"] == r2["faces"]
        assert r1["height"] == pytest.approx(r2["height"])
