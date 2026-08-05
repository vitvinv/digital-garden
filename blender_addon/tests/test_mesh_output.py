"""Phase 2 tests: mesh output from grown plants."""

import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.factory import grow_species
from core.plant_library import SpeciesLibrary
from core.mesh_buffer import MeshBuffer
from core.turtle import MeshTurtle
from core.draw import draw_plant
from core.tdo_parser import TdoLibrary

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "..",
                        "examples", "PlantStudio-master", "for-olpc-python")
TDO_PATH = os.path.join(DATA_DIR, "3D object library.tdo")


@pytest.fixture(scope="module")
def lib():
    return SpeciesLibrary(DATA_DIR)


def mesh_for(species_name, day, seed=280):
    lib = SpeciesLibrary(DATA_DIR)
    species = lib.get(species_name)
    tdo_lib = TdoLibrary.from_file(TDO_PATH)
    plant = grow_species(species, day, seed=seed, tdo_library=tdo_lib)
    buffer = MeshBuffer()
    turtle = MeshTurtle(buffer)
    turtle.setScale_pixelsPerMm(0.1)
    draw_plant(plant, turtle)
    return buffer, plant


class TestMeshOutput:
    def test_maiden_grass_mesh(self):
        buf, plant = mesh_for("maiden grass", 60)
        verts, faces = buf.stats()
        assert verts > 0
        assert faces > 0
        assert len(buf.face_colors) == faces

    def test_bushy_plant_mesh(self):
        buf, plant = mesh_for("Piney bushy plant", 120)
        verts, faces = buf.stats()
        assert verts > 0
        assert faces > 0

    def test_mesh_deterministic(self):
        buf1, _ = mesh_for("maiden grass", 60)
        buf2, _ = mesh_for("maiden grass", 60)
        assert buf1.vertices == buf2.vertices
        assert buf1.faces == buf2.faces

    def test_mesh_bounds_reasonable(self):
        buf, plant = mesh_for("maiden grass", 60)
        xs = [v[0] for v in buf.vertices]
        ys = [v[1] for v in buf.vertices]
        zs = [v[2] for v in buf.vertices]
        # plant should be upright, mostly above origin
        assert max(zs) > 0
        assert min(zs) >= -20
        # not degenerate
        assert max(xs) - min(xs) > 0.1

    def test_colors_present(self):
        buf, _ = mesh_for("maiden grass", 60)
        colors = set(buf.face_colors)
        assert len(colors) >= 1

    def test_grown_larger_than_young(self):
        buf_young, _ = mesh_for("maiden grass", 10)
        buf_old, _ = mesh_for("maiden grass", 90)
        assert len(buf_old.vertices) > len(buf_young.vertices)
