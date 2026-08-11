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
from blender_addon.core.mesh_buffer import PIPE_FACES
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


class TestPipeOptimization:
    """Tube face reduction + frame-continuity welding of pipe seams."""

    def test_default_pipe_faces_is_three(self):
        assert PIPE_FACES == 3

    def test_single_pipe_face_count(self):
        buf = MeshBuffer()
        buf.add_pipe((0, 0, 0), (1, 0, 0), 0.5, 0.5, 3,
                     (100, 200, 100), cap_start=True, cap_end=True)
        _, faces = buf.stats()
        # n=3: 3 side quads (6 tris) + 2 caps (1 tri each) = 8
        assert faces == 8

    def test_bent_pipe_joint_is_welded(self):
        # Two consecutive pipes with different directions sharing a joint.
        # Frame continuity reuses the previous end-ring basis, so the joint
        # ring is a single shared n-gon (n=3), not two rotated rings (2n).
        buf = MeshBuffer()
        color = (100, 200, 100)
        b1 = MeshBuffer._perpendicular_basis(1, 0, 0)  # along +X
        b2 = MeshBuffer._perpendicular_basis(0, 1, 0)  # along +Y
        buf.add_pipe((0, 0, 0), (1, 0, 0), 0.5, 0.5, 3, color,
                     basis_start=b1, basis_end=b1,
                     cap_start=False, cap_end=False)
        buf.add_pipe((1, 0, 0), (1, 1, 0), 0.5, 0.5, 3, color,
                     basis_start=b1, basis_end=b2,   # reuse b1 at the joint
                     cap_start=False, cap_end=False)
        # start ring (3) + shared joint ring (3) + end ring (3) = 9 verts.
        # Without welding the joint would be 2n=6 -> 12 total.
        assert len(buf.vertices) == 9


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


class TestFruitRipeness:
    """P3a: unripe fruit draws with alternateFaceColor, ripe with faceColor."""

    def test_unripe_fruit_uses_alternate_color(self):
        # tomato: first fruit sets ~day 75 (after the linearGrowthResult fix
        # restored the original's realistic growth); at day 75 every fruit is
        # unripe, so the mesh must contain the alternate (unripe) color, not
        # the ripe one.
        buf, plant = mesh_for("tomato", 75)
        colors = set(buf.face_colors)
        alt = plant.params.pFruit.tdoParams.alternateFaceColor
        face = plant.params.pFruit.tdoParams.faceColor
        assert alt is not None and face is not None
        assert alt in colors, "unripe fruit color missing from mesh"
        assert face not in colors, "no fruit should be ripe yet at day 75"

    def test_ripe_fruit_uses_face_color(self):
        # all tomato fruit is ripe by day 90: unripe color gone, ripe present
        buf, plant = mesh_for("tomato", 90)
        colors = set(buf.face_colors)
        alt = plant.params.pFruit.tdoParams.alternateFaceColor
        face = plant.params.pFruit.tdoParams.faceColor
        assert alt is not None and face is not None
        assert alt not in colors, "no fruit should be unripe at day 90"
        assert face in colors, "ripe fruit color missing from mesh"


class TestInflorescenceBranching:
    """P3b: inflorescences walk real branch structure (raceme/panicle),
    not a fixed 8-slot fan — a branched inflorescence must spread vertices."""

    def test_branched_inflorescence_mesh_is_non_degenerate(self):
        import copy
        from blender_addon.core.factory import create_plant

        lib = SpeciesLibrary(DATA_DIR)
        sp = lib.get("gilia")
        tdo_lib = TdoLibrary.from_file(TDO_PATH)
        params = copy.deepcopy(sp.params)
        # inflorescence-level params now live in params.inflors (separate from
        # pFlower, matching the original model)
        pi = params.inflors["kGenderFemale"]
        pi["numBranches"] = 2
        pi["numFlowersPerBranch"] = 2
        pi["numFlowersOnMainBranch"] = 4
        params.pGeneral.numApicalInflors = 1
        params.pGeneral.numAxillaryInflors = 4

        plant = create_plant(params, seed=280, tdo_library=tdo_lib)
        plant.growTo(150)
        buffer = MeshBuffer()
        turtle = MeshTurtle(buffer)
        turtle.setScale_pixelsPerMm(0.1)
        draw_plant(plant, turtle)
        verts, faces = buffer.stats()
        assert verts > 0 and faces > 0
        xs = [v[0] for v in buffer.vertices]
        ys = [v[1] for v in buffer.vertices]
        # distinct branch positions: inflorescence spans more than a point
        assert max(xs) - min(xs) > 0.5
        assert max(ys) - min(ys) > 0.5


class TestPlaValidation:
    """P5c: bundled .pla data must have no *unresolved* TDO references.

    Known naming mismatches ('Default' vs 'Default 3D object') are tolerated
    because their geometry is embedded and draws fine; anything actually
    missing from the library is a data bug."""
    DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
    TDO_PATH = os.path.join(os.path.dirname(__file__), "..", "data",
                            "3D object library.tdo")

    def test_no_unresolved_tdo_refs(self):
        from blender_addon.tools.validate_pla import (iter_tdo_refs,
                                                      validate_dir)
        tdo_lib = TdoLibrary.from_file(self.TDO_PATH)
        unresolved = []
        mismatches = []
        validate_dir(self.DATA_DIR, tdo_lib, unresolved, mismatches,
                     allow_mismatch={"Default", "Default tdo"})
        assert not unresolved, (
            f"unresolved TDO references in bundled data: {unresolved}")
