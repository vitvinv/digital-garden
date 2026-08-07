"""Phase 2 tests: mesh output from grown plants."""

import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from blender_addon.core.factory import grow_species
from blender_addon.core.plant_library import SpeciesLibrary
from blender_addon.core.mesh_buffer import MeshBuffer
from blender_addon.core.turtle import MeshTurtle
from blender_addon.core.draw import draw_plant
from blender_addon.core.tdo_parser import TdoLibrary, Tdo, AssetError

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
        # "Piney bushy plant" references 'Default tdo' placeholder objects.
        # With embedded 3D object blocks parsed, those resolve to the real
        # embedded geometry and the plant draws (no AssetError).
        buf, _ = mesh_for("Piney bushy plant", 120)
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


class TestTdoEmbedding:
    """Embedded 3D object blocks in .pla files drive leaf/flower shapes."""

    DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")

    def _species(self, name):
        lib = SpeciesLibrary(self.DATA_DIR)
        sp = lib.get(name)
        assert sp is not None, f"species '{name}' missing from bundled data"
        return sp

    def test_embedded_leaf_tdo_parsed(self):
        # sunflower's leaf ref was clobbered to 'Default' before the parser
        # consumed embedded blocks; now it must be the embedded Tdo object
        # named 'Leaf, sunflower' with real geometry.
        sp = self._species("sunflower")
        lt = sp.params.leafTdoParams.object3D
        assert isinstance(lt, Tdo), f"expected embedded Tdo, got {lt!r}"
        assert lt.name == "Leaf, sunflower"
        assert len(lt.points) >= 3
        assert len(lt.triangles) >= 1

    def test_seedling_params_do_not_clobber_leaf(self):
        # pSeedlingLeaf.leafTdoParams.* must land on params.seedlingTdoParams
        # (root container), NOT on the leaf container.
        sp = self._species("maiden grass")
        lt = sp.params.leafTdoParams.object3D
        assert isinstance(lt, Tdo)
        assert lt.name == "Leaf, grassy 2"
        st = sp.params.seedlingTdoParams
        assert st is not None and st.object3D is not None

    def test_flower_petal_scale_parsed(self):
        # registry access uses 'ScaleAtFullSize' (capital S) — must land on
        # scaleAtFullSize, not stay 0.
        sp = self._species("gilia")
        row = sp.params.flowers["kGenderFemale"]["tdoParams"]["kFirstPetals"]
        assert getattr(row, "scaleAtFullSize", 0.0) == 4.0
        assert getattr(row, "object3D", None) is not None

    @pytest.mark.parametrize("name", [
        "sunflower", "corn", "onion", "carrot", "clover", "wild pink",
        "violet", "snapdragon", "buttercup", "Daylily", "Piney bushy plant",
        "maiden grass", "gilia",
    ])
    def test_previously_broken_species_draw(self, name):
        # all these failed with AssetError or NameError before the fixes
        buf, plant = mesh_for(name, 120)
        verts, faces = buf.stats()
        assert verts > 0, f"{name}: empty mesh"
        assert faces > 0, f"{name}: no faces"

    def test_k_activity_free_does_not_crash(self):
        # kActivityFree was referenced but not imported in inflorescence.py
        from blender_addon.core.traverser import PdTraverser
        from blender_addon.core.meristem import kActivityFree
        lib = SpeciesLibrary(self.DATA_DIR)
        sp = lib.get("violet")
        tdo_lib = TdoLibrary.from_file(TDO_PATH)
        plant = grow_species(sp, 150, seed=280, tdo_library=tdo_lib)
        traverser = PdTraverser(plant)
        traverser.traverseWholePlant(kActivityFree)
        assert plant.age == 150
