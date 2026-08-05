"""
Plant Designer — real-time interactive plant / garden design tool.

Lets you adjust species parameters with sliders and number inputs, see
the plant update live in the PlantGL 3D viewer, and compose multiple
plants into one garden scene. Exports to GLB (for the AR scene) and to
growth-config.json (source of truth for the growth pipeline).

Determinism is preserved: every slider value set is just a deterministic
`generate()` call — the same inputs always reproduce the same plant.

Installation (one time, on your desktop machine):

    conda create -n pgl python=3.10 openalea.plantgl -c openalea3 -c conda-forge
    conda activate pgl
    pip install trimesh numpy pyside6        # PySide6 if PlantGL is Qt6-based
    # or: pip install pyqt5                  # PyQt5 if PlantGL is Qt5-based

Run:

    conda activate pgl
    python scripts/designer.py
"""

import os
import sys
import json
import tempfile
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import numpy as np
import trimesh

from species import SPECIES, DESIGN_PARAMS
from generate import build_plant_scene, generate

# ── PlantGL + Qt imports (GUI required for this tool) ──

try:
    from openalea.plantgl.all import Scene, Shape, Translated, Material
    HAS_PLANTGL = True
except ImportError as e:
    HAS_PLANTGL = False
    print(f"ERROR: PlantGL not available: {e}")
    print("Install it with:")
    print("  conda create -n pgl python=3.10 openalea.plantgl -c openalea3 -c conda-forge")
    sys.exit(1)

try:
    from openalea.plantgl.gui import pglviewer
    from openalea.plantgl.gui.qt import QtWidgets, QtCore
except ImportError as e:
    print(f"ERROR: PlantGL GUI (Qt) not available: {e}")
    print("Ensure the conda env has a Qt binding: pip install pyside6 (or pyqt5)")
    sys.exit(1)

Qt = QtCore.Qt


class CompatPglViewer(pglviewer.PglViewer):
    """
    PlantGL 3.21.x's PglViewer calls self.updateGL() (removed in
    PyQGLViewer 1.3.x for Qt5). Add a compatibility shim.
    """

    def updateGL(self):
        self.update()


# ── Data model helpers ──

def new_plant(species="fern", seed=42, day_n=60, position=None, overrides=None):
    return {
        "name": f"{species}-1",
        "species": species,
        "seed": seed,
        "day_n": day_n,
        "position": list(position) if position else [0.0, 0.0, 0.0],
        "overrides": dict(overrides) if overrides else {},
    }


# ── Qt application ──

class PlantDesigner(QtWidgets.QWidget):
    """
    Plant Designer main window.

    Note: uses QWidget (not QMainWindow) as root — the PlantGL
    QGLViewer crashes on show() when embedded in QMainWindow on
    the Qt5/PyQGLViewer Windows stack.
    """

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Plant Designer")
        self.resize(1200, 750)

        self.plants = [new_plant()]
        self.selected_index = 0
        self._updating = False
        self._plant_counter = 1

        self._build_ui()
        self._refresh_plant_list()
        self._load_controls()
        self._refresh_viewer()

    # ── UI construction ──

    def _build_ui(self):
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        splitter = QtWidgets.QSplitter(Qt.Horizontal)

        # Left: 3D viewer
        self.viewer = CompatPglViewer()
        splitter.addWidget(self.viewer)

        # Right: control panel
        panel = QtWidgets.QWidget()
        panel.setFixedWidth(360)
        panel_layout = QtWidgets.QVBoxLayout(panel)
        panel_layout.setContentsMargins(8, 8, 8, 8)

        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(panel)
        splitter.addWidget(scroll)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        root.addWidget(splitter, 1)

        # Plant list
        list_label = QtWidgets.QLabel("Plants in garden")
        panel_layout.addWidget(list_label)
        self.plant_list = QtWidgets.QListWidget()
        self.plant_list.currentRowChanged.connect(self._on_select_plant)
        panel_layout.addWidget(self.plant_list, 1)

        btn_row = QtWidgets.QHBoxLayout()
        self.add_btn = QtWidgets.QPushButton("+ Add")
        self.dup_btn = QtWidgets.QPushButton("Duplicate")
        self.rm_btn = QtWidgets.QPushButton("- Remove")
        self.add_btn.clicked.connect(self._on_add)
        self.dup_btn.clicked.connect(self._on_duplicate)
        self.rm_btn.clicked.connect(self._on_remove)
        btn_row.addWidget(self.add_btn)
        btn_row.addWidget(self.dup_btn)
        btn_row.addWidget(self.rm_btn)
        panel_layout.addLayout(btn_row)

        # Plant properties
        props = QtWidgets.QGroupBox("Plant")
        props_layout = QtWidgets.QFormLayout(props)

        self.species_combo = QtWidgets.QComboBox()
        self.species_combo.addItems(list(SPECIES.keys()))
        self.species_combo.currentTextChanged.connect(self._on_species_changed)
        props_layout.addRow("Species", self.species_combo)

        seed_row = QtWidgets.QHBoxLayout()
        self.seed_spin = QtWidgets.QSpinBox()
        self.seed_spin.setRange(0, 999999)
        self.seed_spin.valueChanged.connect(self._on_control_changed)
        rand_btn = QtWidgets.QPushButton("Random")
        rand_btn.clicked.connect(self._on_random_seed)
        seed_row.addWidget(self.seed_spin)
        seed_row.addWidget(rand_btn)
        props_layout.addRow("Seed", seed_row)

        self.day_spin = QtWidgets.QSpinBox()
        self.day_spin.setRange(0, 3650)
        self.day_spin.valueChanged.connect(self._on_control_changed)
        props_layout.addRow("Day", self.day_spin)

        self.color_combo = QtWidgets.QComboBox()
        self.color_combo.addItems([
            "Leaf: green", "Leaf: brown", "Leaf: red",
            "Leaf: olive", "Leaf: blue", "Leaf: magenta",
        ])
        self.color_combo.currentIndexChanged.connect(self._on_control_changed)
        props_layout.addRow("Leaf color", self.color_combo)

        self.pos_x = QtWidgets.QDoubleSpinBox()
        self.pos_x.setRange(-5, 5)
        self.pos_x.setSingleStep(0.05)
        self.pos_x.valueChanged.connect(self._on_control_changed)
        props_layout.addRow("Position X", self.pos_x)

        self.pos_z = QtWidgets.QDoubleSpinBox()
        self.pos_z.setRange(-5, 5)
        self.pos_z.setSingleStep(0.05)
        self.pos_z.valueChanged.connect(self._on_control_changed)
        props_layout.addRow("Position Z", self.pos_z)

        panel_layout.addWidget(props)

        # Parameter sliders
        self.params_box = QtWidgets.QGroupBox("Parameters")
        self.params_layout = QtWidgets.QVBoxLayout(self.params_box)
        panel_layout.addWidget(self.params_box)

        # Actions
        action_row = QtWidgets.QHBoxLayout()
        export_btn = QtWidgets.QPushButton("Export GLB")
        export_btn.clicked.connect(self._on_export_glb)
        save_btn = QtWidgets.QPushButton("Save config")
        save_btn.clicked.connect(self._on_save_config)
        fit_btn = QtWidgets.QPushButton("Fit view")
        fit_btn.clicked.connect(self._on_fit_view)
        action_row.addWidget(export_btn)
        action_row.addWidget(save_btn)
        action_row.addWidget(fit_btn)
        panel_layout.addLayout(action_row)

        self.status = QtWidgets.QLabel("Ready")
        self.status.setContentsMargins(4, 4, 4, 4)
        panel_layout.addWidget(self.status)

    # ── Sliders (rebuilt when species changes) ──

    def _rebuild_param_sliders(self):
        while self.params_layout.count():
            item = self.params_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        species = self.plants[self.selected_index]["species"]
        self._slider_widgets = {}
        for attr, label, lo, hi, step in DESIGN_PARAMS.get(species, []):
            row = QtWidgets.QHBoxLayout()
            lbl = QtWidgets.QLabel(label)
            lbl.setFixedWidth(150)
            slider = QtWidgets.QSlider(Qt.Horizontal)
            slider.setRange(0, 1000)
            spin = QtWidgets.QDoubleSpinBox()
            spin.setRange(float(lo), float(hi))
            spin.setSingleStep(float(step))
            spin.setDecimals(3)

            def _slider_to_spin(value, attr=attr, slider=slider, spin=spin, lo=lo, hi=hi):
                if self._updating:
                    return
                self._updating = True
                spin.setValue(float(lo) + value * (float(hi) - float(lo)) / 1000.0)
                self._updating = False
                self._on_control_changed()

            def _spin_to_slider(value, slider=slider, lo=lo, hi=hi):
                if self._updating:
                    return
                self._updating = True
                slider.setValue(int((float(value) - float(lo)) / (float(hi) - float(lo)) * 1000))
                self._updating = False
                self._on_control_changed()

            slider.valueChanged.connect(_slider_to_spin)
            spin.valueChanged.connect(_spin_to_slider)
            row.addWidget(lbl)
            row.addWidget(slider, 1)
            row.addWidget(spin)
            self._slider_widgets[attr] = (slider, spin, lo, hi)
            self.params_layout.addLayout(row)

    # ── Control population ──

    def _load_controls(self):
        plant = self.plants[self.selected_index]
        self._updating = True
        self.species_combo.setCurrentText(plant["species"])
        self.seed_spin.setValue(plant["seed"])
        self.day_spin.setValue(plant["day_n"])
        self.pos_x.setValue(plant["position"][0])
        self.pos_z.setValue(plant["position"][2])
        leaf_color = int(plant["overrides"].get("leaf_color", 2))
        self.color_combo.setCurrentIndex(max(0, min(5, leaf_color - 1)))
        self._rebuild_param_sliders()
        for attr, (slider, spin, lo, hi) in self._slider_widgets.items():
            val = plant["overrides"].get(attr)
            if val is None:
                val = getattr(SPECIES[plant["species"]], attr)
            slider.setValue(int((float(val) - lo) / (hi - lo) * 1000))
            spin.setValue(float(val))
        self._updating = False

    # ── View refresh ──

    def _refresh_viewer(self):
        scene = Scene()
        for plant in self.plants:
            try:
                pscene, _, _ = build_plant_scene(
                    plant["species"], plant["seed"], plant["day_n"],
                    None, plant["overrides"] or None,
                )
            except Exception as e:
                self.status.setText(f"Error: {e}")
                return
            px, py, pz = plant["position"]
            for shape in pscene:
                geom = Translated((px, py, pz), shape.geometry)
                appearance = getattr(shape, "appearance", None) or Material()
                scene.add(Shape(geom, appearance))
        self.viewer.display(scene)

    # ── Signals ──

    def _refresh_plant_list(self):
        self._updating = True
        self.plant_list.clear()
        for i, plant in enumerate(self.plants):
            pos = plant["position"]
            self.plant_list.addItem(
                f"{plant['name']}  ({plant['species']}, seed {plant['seed']}, "
                f"day {plant['day_n']}, @{pos[0]:.2f},{pos[2]:.2f})"
            )
        self.plant_list.setCurrentRow(self.selected_index)
        self._updating = False

    def _on_select_plant(self, row):
        if self._updating or row < 0:
            return
        self.selected_index = row
        self._load_controls()

    def _on_add(self):
        self._plant_counter += 1
        template = self.plants[self.selected_index]
        plant = new_plant(
            species=template["species"],
            seed=template["seed"] + self._plant_counter,
            day_n=template["day_n"],
            position=[template["position"][0] + 0.3, 0.0, template["position"][2]],
        )
        self.plants.append(plant)
        self.selected_index = len(self.plants) - 1
        self._refresh_plant_list()
        self._load_controls()
        self._refresh_viewer()

    def _on_duplicate(self):
        src = self.plants[self.selected_index]
        plant = json.loads(json.dumps(src))
        plant["name"] = f"{plant['species']}-{len(self.plants) + 1}"
        plant["position"] = [plant["position"][0] + 0.3, 0.0, plant["position"][2]]
        self.plants.append(plant)
        self.selected_index = len(self.plants) - 1
        self._refresh_plant_list()
        self._load_controls()
        self._refresh_viewer()

    def _on_remove(self):
        if len(self.plants) <= 1:
            self.status.setText("Cannot remove the last plant")
            return
        del self.plants[self.selected_index]
        self.selected_index = min(self.selected_index, len(self.plants) - 1)
        self._refresh_plant_list()
        self._load_controls()
        self._refresh_viewer()

    def _on_random_seed(self):
        import random
        self.seed_spin.setValue(random.randint(0, 99999))

    def _on_species_changed(self, species):
        if self._updating:
            return
        self.plants[self.selected_index]["species"] = species
        self.plants[self.selected_index]["overrides"] = {}
        self._load_controls()
        self._refresh_plant_list()
        self._refresh_viewer()

    def _on_control_changed(self):
        if self._updating:
            return
        plant = self.plants[self.selected_index]
        plant["seed"] = self.seed_spin.value()
        plant["day_n"] = self.day_spin.value()
        plant["position"] = [self.pos_x.value(), 0.0, self.pos_z.value()]
        plant["overrides"]["leaf_color"] = self.color_combo.currentIndex() + 1
        for attr, (slider, spin, lo, hi) in getattr(self, "_slider_widgets", {}).items():
            val = spin.value()
            plant["overrides"][attr] = val
        self._refresh_plant_list()
        self._refresh_viewer()

    def _on_fit_view(self):
        self.viewer.display(self.viewer.scene)

    # ── Export ──

    def _build_garden_trimesh_scene(self):
        scene = trimesh.Scene()
        for plant in self.plants:
            result = generate(
                plant["species"], plant["seed"], plant["day_n"],
                None, plant["overrides"] or None,
            )
            mesh = result["mesh"]
            # Direct vertex offset — apply_transform crashes with
            # trimesh 5.0.0 + numpy 2.2.6 (pgl conda env)
            mesh.vertices = mesh.vertices + np.asarray(plant["position"], dtype=np.float64)
            scene.add_geometry(mesh, node_name=plant["name"], geom_name=plant["name"])
        return scene

    def _on_export_glb(self):
        default_dir = ROOT / "digital-garden-AR" / "src" / "assets" / "gardens"
        default_dir.mkdir(parents=True, exist_ok=True)
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Export garden GLB", str(default_dir / "garden.glb"), "GLB (*.glb)")
        if not path:
            return
        try:
            scene = self._build_garden_trimesh_scene()
            scene.export(path, file_type="glb")
            self.status.setText(f"Exported {len(self.plants)} plant(s) to {path}")
        except Exception as e:
            self.status.setText(f"Export failed: {e}")

    def _on_save_config(self):
        slug, ok = QtWidgets.QInputDialog.getText(self, "Garden slug",
                                                  "Garden slug (lowercase, dashes):",
                                                  text="my-garden")
        if not ok or not slug.strip():
            return
        slug = slug.strip().lower().replace(" ", "-")

        config_path = ROOT / "growth-config.json"
        if config_path.exists():
            try:
                cfg = json.loads(config_path.read_text())
            except Exception:
                cfg = {}
        else:
            cfg = {}
        cfg.setdefault("gardens", {})

        today = date.today()
        plants_out = []
        for plant in self.plants:
            planted = (today - timedelta(days=plant["day_n"])).isoformat()
            entry = {
                "plant_slot": plant["name"],
                "species": plant["species"],
                "seed": plant["seed"],
                "planted_date": planted,
                "mutation_strength": 0.0,
                "position": plant["position"],
                "canopy_radius": None,
            }
            if plant["overrides"]:
                entry["overrides"] = dict(plant["overrides"])
            plants_out.append(entry)

        cfg["gardens"][slug] = {
            "image_target": cfg["gardens"].get(slug, {}).get("image_target", ""),
            "plants": plants_out,
        }
        config_path.write_text(json.dumps(cfg, indent=2) + "\n")
        self.status.setText(f"Saved {len(plants_out)} plant(s) to {config_path}")


def main():
    app = QtWidgets.QApplication(sys.argv)
    win = PlantDesigner()
    win.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
