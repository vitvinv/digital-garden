"""Compare semantic PlantStudio output with the Blender addon output.

This audit deliberately does not require equal polygon or vertex counts. The
Blender addon uses simplified geometry by design. It compares semantic leaf
presence and silhouette dimensions, and reports addon-only topology counts as
informational diagnostics.

Typical workflow:
    python scripts/compare_plant_geometry.py --init-manifest
    # Put the original PlantStudio OBJ exports at the paths in the manifest.
    python scripts/compare_plant_geometry.py

The manifest keeps duplicate source names unambiguous with IDs such as
``Garden flowers.pla#1``.
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import math
import re
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from plantstudio_blender.core.draw import kExportPartFlower, kExportPartFruit, kExportPartLeaf
from plantstudio_blender.core.factory import grow_species
from plantstudio_blender.core.mesh_buffer import MeshBuffer
from plantstudio_blender.core.plant_library import SpeciesLibrary
from plantstudio_blender.core.pla_parser import parse_pla_file
from plantstudio_blender.core.tdo_parser import TdoLibrary
from plantstudio_blender.core.turtle import MeshTurtle
from plantstudio_blender.core.draw import draw_plant
from scripts.compare_plant_settings import extract_occurrences


DEFAULT_OUTPUT_DIR = ROOT / "reports" / "plant_geometry"
DEFAULT_MANIFEST = DEFAULT_OUTPUT_DIR / "manifest.json"
DEFAULT_ORIGINAL_DIR = ROOT / "examples" / "PlantStudio2"
DEFAULT_ADDON_DIR = ROOT / "plantstudio_blender" / "data"
DEFAULT_REGISTRY = ROOT / "plantstudio_blender" / "core" / "param_registry.json"
DEFAULT_SCALE_TO_METERS = 0.001
DEFAULT_HEIGHT_AXIS = "x"

LONG_COLUMNS = [
    "occurrence_id", "source_file", "source_occurrence_index", "plant_name",
    "obj_file", "metric", "original_value", "addon_value", "difference",
    "relative_difference", "tolerance", "status", "evidence", "source_age",
    "manifest_age", "addon_age", "source_seed", "manifest_seed", "addon_seed",
    "source_line", "obj_group_names", "notes",
]

SUMMARY_COLUMNS = [
    "occurrence_id", "source_file", "source_occurrence_index", "plant_name",
    "obj_file", "obj_exists", "source_age", "manifest_age", "addon_age",
    "source_seed", "manifest_seed", "addon_seed", "original_leaf_count",
    "original_leaf_count_quality", "addon_model_leaf_count",
    "addon_active_leaf_count", "addon_visible_leaf_count",
    "addon_suppressed_leaf_count", "addon_fallen_leaf_count",
    "original_height_m", "addon_height_m", "height_difference_m",
    "overall_status", "status_counts", "cause", "notes",
]


@dataclass
class ObjGroup:
    name: str
    object_name: str
    group_name: str
    face_count: int = 0


@dataclass
class ObjDocument:
    vertices: list[tuple[float, float, float]]
    groups: list[ObjGroup]
    explicit_groups: bool


@dataclass
class AddonMeasurement:
    values: dict[str, Any]
    group_names: list[str]
    error: str = ""


@dataclass
class SourceInfo:
    name: str
    age: int | None
    seed: int | None
    source_line: int | None


def _number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _integer(value: Any) -> int | None:
    number = _number(value)
    return int(number) if number is not None else None


def _format_number(value: Any) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return format(value, ".12g")
    return str(value)


def _safe_relative_difference(original: float | None, addon: float | None) -> float | None:
    if original is None or addon is None:
        return None
    return abs(addon - original) / max(abs(original), 1e-12)


def iter_parts(plant):
    """Yield each grown plant part once, including leaves and flowers."""
    if plant.firstPhytomer is None:
        return
    stack = [plant.firstPhytomer]
    seen = set()
    while stack:
        part = stack.pop()
        if part is None or id(part) in seen:
            continue
        seen.add(id(part))
        yield part
        stack.extend([
            getattr(part, "leftBranchPlantPart", None),
            getattr(part, "rightBranchPlantPart", None),
            getattr(part, "nextPlantPart", None),
            getattr(part, "leftLeaf", None),
            getattr(part, "rightLeaf", None),
        ])
        stack.extend(getattr(part, "flowers", []) or [])


def _count_addon_parts(plant) -> dict[str, int]:
    parts = list(iter_parts(plant) or [])
    leaves = [part for part in parts if type(part).__name__ == "PdLeaf"]
    active_leaves = [leaf for leaf in leaves if not getattr(leaf, "hasFallenOff", False)]
    seedling = [leaf for leaf in leaves if getattr(leaf, "isSeedlingLeaf", False)]
    ordinary = [leaf for leaf in leaves if not getattr(leaf, "isSeedlingLeaf", False)]
    flowers = [part for part in parts if type(part).__name__ == "PdFlowerFruit"]
    fruit = [part for part in flowers if getattr(part, "stage", "bud") in {"unripe_fruit", "ripe_fruit"}]
    internodes = [part for part in parts if type(part).__name__ == "PdInternode"]
    meristems = [part for part in parts if type(part).__name__ == "PdMeristem"]
    branch_roots = []
    for internode in internodes:
        parent = getattr(internode, "phytomerAttachedTo", None)
        if parent is not None and (
                getattr(parent, "leftBranchPlantPart", None) is internode
                or getattr(parent, "rightBranchPlantPart", None) is internode):
            branch_roots.append(internode)
    return {
        "model_leaf_count": len(leaves),
        "model_ordinary_leaf_count": len(ordinary),
        "model_seedling_leaf_count": len(seedling),
        "active_leaf_count": len(active_leaves),
        "active_ordinary_leaf_count": sum(
            not getattr(leaf, "isSeedlingLeaf", False) for leaf in active_leaves
        ),
        "active_seedling_leaf_count": sum(
            getattr(leaf, "isSeedlingLeaf", False) for leaf in active_leaves
        ),
        "fallen_leaf_count": len(leaves) - len(active_leaves),
        "internode_count": len(internodes),
        "branch_count": len(branch_roots),
        "meristem_count": len(meristems),
        "flower_count": len(flowers),
        "fruit_count": len(fruit),
        "bud_count": sum(getattr(flower, "stage", "bud") == "bud" for flower in flowers),
        "open_flower_count": sum(getattr(flower, "stage", "bud") == "open" for flower in flowers),
        "unripe_fruit_count": sum(getattr(flower, "stage", "bud") == "unripe_fruit" for flower in flowers),
        "ripe_fruit_count": sum(getattr(flower, "stage", "bud") == "ripe_fruit" for flower in flowers),
    }


def _bounds(vertices: list[tuple[float, float, float]]) -> tuple[float, float, float]:
    if not vertices:
        return 0.0, 0.0, 0.0
    axes = list(zip(*vertices))
    return tuple(max(axis) - min(axis) for axis in axes)


def _addon_measurement(species, age: int, seed: int, tdo_library: TdoLibrary) -> AddonMeasurement:
    try:
        plant = grow_species(species, age, seed=seed, tdo_library=tdo_library)
        part_counts = _count_addon_parts(plant)
        buffer = MeshBuffer()
        turtle = MeshTurtle(buffer)
        turtle.setScale_pixelsPerMm(0.001)
        draw_plant(plant, turtle)
        drawn_leaf_ids = {
            record.get("semantic_id")
            for record in buffer.triangle_set_records
            if record.get("part_id") == kExportPartLeaf
            and record.get("semantic_id")
            and record.get("triangles", 0) > 0
            and record.get("scale", 0) > 0
        }
        drawn_seedling_ids = {
            record["semantic_id"]
            for record in buffer.semantic_records
            if record.get("kind") == "seedling_leaf"
            and record.get("semantic_id") in drawn_leaf_ids
        }
        drawn_ordinary_ids = drawn_leaf_ids - drawn_seedling_ids
        semantic_statuses = Counter(record.get("status") for record in buffer.semantic_records)
        width, depth, height = _bounds(buffer.vertices)
        part_counts.update({
            "visible_leaf_count": len(drawn_leaf_ids),
            "visible_ordinary_leaf_count": len(drawn_ordinary_ids),
            "visible_seedling_leaf_count": len(drawn_seedling_ids),
            "suppressed_leaf_count": max(
                0, part_counts["active_leaf_count"] - len(drawn_leaf_ids)
            ),
            "suppressed_draw_count": semantic_statuses["suppressed_draw"],
            "suppressed_fallen_count": semantic_statuses["suppressed_fallen"],
            "height_m": height,
            "width_m": width,
            "depth_m": depth,
            "vertex_count_info": len(buffer.vertices),
            "face_count_info": len(buffer.faces),
            "flower_triangle_record_count_info": sum(
                record.get("triangles", 0)
                for record in buffer.triangle_set_records
                if record.get("part_id") == kExportPartFlower
            ),
            "fruit_triangle_record_count_info": sum(
                record.get("triangles", 0)
                for record in buffer.triangle_set_records
                if record.get("part_id") == kExportPartFruit
            ),
        })
        return AddonMeasurement(part_counts, [], "")
    except Exception as exc:  # the report must identify the failing occurrence
        return AddonMeasurement({}, [], f"{type(exc).__name__}: {exc}")


def parse_obj(path: Path) -> ObjDocument:
    """Parse the subset of Wavefront OBJ needed for semantic measurements."""
    vertices: list[tuple[float, float, float]] = []
    groups: dict[tuple[str, str], ObjGroup] = {}
    object_name = "default"
    group_name = "default"
    explicit_groups = False

    for raw_line in path.read_text(encoding="latin-1").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        keyword = parts[0].lower()
        if keyword == "v" and len(parts) >= 4:
            vertices.append((float(parts[1]), float(parts[2]), float(parts[3])))
        elif keyword == "o" and len(parts) >= 2:
            object_name = " ".join(parts[1:])
            group_name = object_name
        elif keyword == "g" and len(parts) >= 2:
            explicit_groups = True
            group_name = " ".join(parts[1:])
        elif keyword == "f" and len(parts) >= 4:
            key = (object_name, group_name)
            group = groups.setdefault(key, ObjGroup(
                name=f"{object_name}:{group_name}",
                object_name=object_name,
                group_name=group_name,
            ))
            group.face_count += max(1, len(parts) - 3)

    return ObjDocument(vertices, list(groups.values()), explicit_groups)


def classify_group(name: str) -> str | None:
    """Classify PlantStudio export names without counting polygon fragments."""
    normalized = re.sub(r"[^a-z0-9]+", " ", name.casefold()).strip()
    compact = normalized.replace(" ", "")
    if "stipule" in normalized:
        return "stipule"
    if "seedlingleaf" in compact or "1stleaf" in compact or "firstleaf" in compact:
        return "seedling_leaf"
    if re.search(r"\bleaf(?:let)?s?\b", normalized) or "leaflet" in compact:
        return "leaf"
    if "fruit" in normalized:
        return "fruit"
    if any(token in normalized for token in ("flower", "petal", "sepal", "bud")):
        return "flower"
    if any(token in normalized for token in ("internode", "petiole", "stem", "stalk", "branch")):
        return "stem"
    return None


def obj_semantics(document: ObjDocument, entry: dict[str, Any]) -> dict[str, Any]:
    semantic_groups = [
        (group, classify_group(group.group_name) or classify_group(group.name))
        for group in document.groups if group.face_count > 0
    ]
    counts = Counter(kind for _group, kind in semantic_groups if kind)
    leaf_groups = [group.name for group, kind in semantic_groups if kind in {"leaf", "seedling_leaf"}]
    quality = entry.get("leaf_count_quality", "")
    if not quality:
        grouping = str(entry.get("export_grouping", "")).casefold()
        if "plant_part" in grouping or "leaf_parent" in grouping:
            quality = "reliable" if leaf_groups else "unavailable"
        else:
            quality = "ambiguous" if leaf_groups else "unavailable"
    scale = _number(entry.get("plantstudio_scale_to_meters")) or DEFAULT_SCALE_TO_METERS
    axis = str(entry.get("height_axis", DEFAULT_HEIGHT_AXIS)).casefold()
    axis_index = {"x": 0, "y": 1, "z": 2}.get(axis, 0)
    dimensions = _bounds(document.vertices)
    height = dimensions[axis_index] * scale
    return {
        "leaf_count": counts["leaf"] + counts["seedling_leaf"],
        "ordinary_leaf_count": counts["leaf"],
        "seedling_leaf_count": counts["seedling_leaf"],
        "flower_count": counts["flower"],
        "fruit_count": counts["fruit"],
        "stem_group_count": counts["stem"],
        "height_m": height,
        "width_m": dimensions[(axis_index + 1) % 3] * scale,
        "depth_m": dimensions[(axis_index + 2) % 3] * scale,
        "vertex_count_info": len(document.vertices),
        "face_count_info": sum(group.face_count for group in document.groups),
        "leaf_count_quality": quality,
        "group_names": [group.name for group, _kind in semantic_groups],
        "leaf_group_names": leaf_groups,
        "semantic_group_count": len(semantic_groups),
    }


def _source_info(original_dir: Path, filename: str, index: int, registry: dict[str, dict[str, Any]]) -> SourceInfo:
    path = original_dir / filename
    occurrences = extract_occurrences(path, registry) if path.exists() else []
    if index > len(occurrences):
        return SourceInfo("<missing>", None, None, None)
    occurrence = occurrences[index - 1]
    age = _integer(occurrence.settings.get("kStateAge").raw_value
                   if occurrence.settings.get("kStateAge") else None)
    seed = _integer(occurrence.settings.get("kGeneralStartingSeedForRandomNumberGenerator").raw_value
                    if occurrence.settings.get("kGeneralStartingSeedForRandomNumberGenerator") else None)
    return SourceInfo(occurrence.name, age, seed, occurrence.start_line)


def build_manifest_template(original_dir: Path, registry_path: Path,
                            obj_directory: str = "original_obj") -> dict[str, Any]:
    """Build an entry for every original source occurrence."""
    registry_list = json.loads(registry_path.read_text(encoding="utf-8"))
    registry = {entry["id"]: entry for entry in registry_list if entry.get("id") != "header"}
    entries = []
    for source_path in sorted(original_dir.glob("*.pla")):
        occurrences = extract_occurrences(source_path, registry)
        for index, occurrence in enumerate(occurrences, 1):
            age_setting = occurrence.settings.get("kStateAge")
            seed_setting = occurrence.settings.get("kGeneralStartingSeedForRandomNumberGenerator")
            entries.append({
                "occurrence_id": f"{source_path.name}#{index}",
                "source_file": source_path.name,
                "occurrence_index": index,
                "plant_name": occurrence.name,
                "saved_age": _integer(age_setting.raw_value if age_setting else None),
                "starting_seed": _integer(seed_setting.raw_value if seed_setting else None),
                "obj_file": f"{obj_directory}/{source_path.stem}__{index:03d}.obj",
                "plantstudio_scale_to_meters": DEFAULT_SCALE_TO_METERS,
                "height_axis": DEFAULT_HEIGHT_AXIS,
                "export_grouping": "by_plant_part",
                "leaf_count_quality": "reliable",
            })
    return {
        "version": 1,
        "description": "PlantStudio OBJ baseline for semantic output comparison.",
        "defaults": {
            "plantstudio_scale_to_meters": DEFAULT_SCALE_TO_METERS,
            "height_axis": DEFAULT_HEIGHT_AXIS,
            "export_grouping": "by_plant_part",
            "leaf_count_quality": "reliable",
        },
        "occurrences": entries,
    }


def write_manifest_template(path: Path, original_dir: Path, registry_path: Path) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    manifest = build_manifest_template(original_dir, registry_path)
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def load_manifest(path: Path, original_dir: Path, registry_path: Path) -> tuple[dict[str, Any], bool]:
    if not path.exists():
        return build_manifest_template(original_dir, registry_path), False
    return json.loads(path.read_text(encoding="utf-8")), True


def _entry_for_occurrence(manifest: dict[str, Any], occurrence_id: str) -> dict[str, Any] | None:
    defaults = manifest.get("defaults", {})
    for raw_entry in manifest.get("occurrences", []):
        if raw_entry.get("occurrence_id") == occurrence_id:
            entry = dict(defaults)
            entry.update(raw_entry)
            return entry
    return None


def _metric_row(base: dict[str, str], metric: str, original: Any, addon: Any,
                status: str, tolerance: Any = "", evidence: str = "", notes: str = "") -> dict[str, str]:
    original_number = _number(original)
    addon_number = _number(addon)
    difference = None
    relative = None
    if original_number is not None and addon_number is not None:
        difference = addon_number - original_number
        relative = _safe_relative_difference(original_number, addon_number)
    row = dict(base)
    row.update({
        "metric": metric,
        "original_value": _format_number(original),
        "addon_value": _format_number(addon),
        "difference": _format_number(difference),
        "relative_difference": _format_number(relative),
        "tolerance": _format_number(tolerance),
        "status": status,
        "evidence": evidence,
        "notes": notes,
    })
    return row


def _compare_dimension(metric: str, original: Any, addon: Any,
                       abs_tolerance: float, rel_tolerance: float,
                       base: dict[str, str], evidence: str) -> dict[str, str]:
    original_number = _number(original)
    addon_number = _number(addon)
    if original_number is None:
        return _metric_row(base, metric, original, addon, "missing_original_export", evidence=evidence)
    if addon_number is None:
        return _metric_row(base, metric, original, addon, "addon_error", evidence=evidence)
    tolerance = max(abs_tolerance, abs(original_number) * rel_tolerance)
    status = "match" if abs(addon_number - original_number) <= tolerance else (
        "height_mismatch" if metric == "height_m" else "silhouette_mismatch"
    )
    return _metric_row(base, metric, original, addon, status, tolerance=tolerance, evidence=evidence)


def _compare_leaf_metric(metric: str, original: Any, addon: Any, quality: str,
                         base: dict[str, str], evidence: str,
                         lower_status: str = "leaf_missing_from_model") -> dict[str, str]:
    if quality != "reliable":
        status = "ambiguous_original_count" if quality == "ambiguous" else "missing_original_export"
        return _metric_row(base, metric, original, addon, status, evidence=evidence)
    if original is None:
        return _metric_row(base, metric, original, addon, "missing_original_export", evidence=evidence)
    if addon is None:
        return _metric_row(base, metric, original, addon, "addon_error", evidence=evidence)
    status = "match" if int(original) == int(addon) else (
        lower_status if int(addon) < int(original)
        else "extra_addon_leaf"
    )
    return _metric_row(base, metric, original, addon, status, evidence=evidence)


def compare_occurrence(entry: dict[str, Any], source: SourceInfo, addon: AddonMeasurement,
                       obj: ObjDocument | None, obj_path: Path, source_dir: Path,
                       manifest_exists: bool, abs_tolerance: float,
                       rel_tolerance: float) -> tuple[list[dict[str, str]], dict[str, str]]:
    occurrence_id = entry["occurrence_id"]
    base = {
        "occurrence_id": occurrence_id,
        "source_file": entry.get("source_file", ""),
        "source_occurrence_index": str(entry.get("occurrence_index", "")),
        "plant_name": source.name,
        "obj_file": str(entry.get("obj_file", "")),
        "source_age": _format_number(source.age),
        "manifest_age": _format_number(entry.get("saved_age")),
        "addon_age": _format_number(entry.get("saved_age")),
        "source_seed": _format_number(source.seed),
        "manifest_seed": _format_number(entry.get("starting_seed")),
        "addon_seed": _format_number(entry.get("starting_seed")),
        "source_line": _format_number(source.source_line),
        "obj_group_names": "; ".join(obj_semantics(obj, entry)["group_names"] if obj else []),
    }
    rows: list[dict[str, str]] = []
    notes: list[str] = []
    if not manifest_exists:
        notes.append("manifest missing; generated in-memory template")
    if source.age is not None and entry.get("saved_age") is not None and source.age != _integer(entry.get("saved_age")):
        rows.append(_metric_row(base, "saved_age", source.age, entry.get("saved_age"), "metadata_mismatch",
                                 evidence="source .pla kStateAge versus manifest saved_age"))
    if source.seed is not None and entry.get("starting_seed") is not None and source.seed != _integer(entry.get("starting_seed")):
        rows.append(_metric_row(base, "starting_seed", source.seed, entry.get("starting_seed"), "metadata_mismatch",
                                 evidence="source .pla kGeneralStartingSeedForRandomNumberGenerator versus manifest starting_seed"))
    if addon.error:
        rows.append(_metric_row(base, "addon_run", "", "", "addon_error", evidence=addon.error))
    obj_values = obj_semantics(obj, entry) if obj else {}
    obj_exists = obj is not None
    addon_values = addon.values
    leaf_quality = obj_values.get("leaf_count_quality", "unavailable")
    leaf_evidence = "; ".join(obj_values.get("leaf_group_names", [])) or "no leaf groups"
    rows.extend([
        _compare_leaf_metric("leaf_count", obj_values.get("leaf_count"),
                             addon_values.get("active_leaf_count"), leaf_quality, base, leaf_evidence,
                             lower_status="leaf_missing_from_model"),
        _compare_leaf_metric("ordinary_leaf_count", obj_values.get("ordinary_leaf_count"),
                             addon_values.get("active_ordinary_leaf_count"), leaf_quality, base, leaf_evidence,
                             lower_status="leaf_missing_from_model"),
        _compare_leaf_metric("seedling_leaf_count", obj_values.get("seedling_leaf_count"),
                             addon_values.get("active_seedling_leaf_count"), leaf_quality, base, leaf_evidence,
                             lower_status="leaf_missing_from_model"),
        _compare_leaf_metric("visible_leaf_count", obj_values.get("leaf_count"),
                             addon_values.get("visible_leaf_count"), leaf_quality, base, leaf_evidence,
                             lower_status="leaf_suppressed_in_draw"),
    ])
    if obj_values.get("leaf_count") is not None and leaf_quality == "reliable":
        active = addon_values.get("active_leaf_count")
        visible = addon_values.get("visible_leaf_count")
        if active is not None and visible is not None and visible < int(obj_values["leaf_count"]):
            status = "leaf_suppressed_in_draw" if active >= int(obj_values["leaf_count"]) else "leaf_missing_from_model"
            rows.append(_metric_row(base, "leaf_presence_diagnosis", obj_values["leaf_count"], visible,
                                    status, evidence=f"active={active}; visible={visible}; fallen={addon_values.get('fallen_leaf_count', 0)}"))
    for metric in ("height_m", "width_m", "depth_m"):
        rows.append(_compare_dimension(metric, obj_values.get(metric), addon_values.get(metric),
                                       abs_tolerance, rel_tolerance, base,
                                       f"OBJ bounds versus addon MeshBuffer bounds; height axis={entry.get('height_axis', 'x')}"))
    for metric in ("model_leaf_count", "active_leaf_count", "visible_leaf_count", "suppressed_leaf_count",
                   "fallen_leaf_count", "internode_count", "branch_count", "meristem_count",
                   "flower_count", "fruit_count", "bud_count", "open_flower_count",
                   "unripe_fruit_count", "ripe_fruit_count", "vertex_count_info", "face_count_info"):
        rows.append(_metric_row(base, metric, "", addon_values.get(metric), "informational",
                                evidence="addon structural/render diagnostic only",
                                notes="not compared to OBJ topology" if metric.endswith("_info") else ""))

    statuses = Counter(row["status"] for row in rows)
    if not obj_exists:
        overall = "missing_original_export"
        cause = "Add the PlantStudio OBJ at the manifest path."
    elif addon.error:
        overall = "addon_error"
        cause = addon.error
    elif statuses["metadata_mismatch"]:
        overall = "metadata_mismatch"
        cause = "Manifest age or seed does not match the source .pla occurrence."
    elif statuses["leaf_missing_from_model"] or any(
            row["status"] == "leaf_missing_from_model" for row in rows):
        overall = "leaf_missing_from_model"
        cause = "The addon growth tree created fewer active leaves than the PlantStudio export."
    elif statuses["leaf_suppressed_in_draw"]:
        overall = "leaf_suppressed_in_draw"
        cause = "The addon model has the leaf, but the draw path did not emit it."
    elif statuses["extra_addon_leaf"]:
        overall = "extra_addon_leaf"
        cause = "The addon rendered more semantic leaves than the PlantStudio export."
    elif statuses["height_mismatch"]:
        overall = "height_mismatch"
        cause = "Plant extent differs after applying the manifest coordinate scale and axis."
    elif statuses["silhouette_mismatch"]:
        overall = "silhouette_mismatch"
        cause = "Plant width or depth differs after coordinate normalization."
    elif statuses["ambiguous_original_count"]:
        overall = "ambiguous_original_count"
        cause = "The OBJ does not preserve enough parent-part naming to prove leaf parity."
    else:
        overall = "match"
        cause = "Semantic leaf presence and silhouette dimensions match within tolerance."

    summary = {
        "occurrence_id": occurrence_id,
        "source_file": entry.get("source_file", ""),
        "source_occurrence_index": str(entry.get("occurrence_index", "")),
        "plant_name": source.name,
        "obj_file": str(entry.get("obj_file", "")),
        "obj_exists": str(obj_exists).lower(),
        "source_age": _format_number(source.age),
        "manifest_age": _format_number(entry.get("saved_age")),
        "addon_age": _format_number(entry.get("saved_age")),
        "source_seed": _format_number(source.seed),
        "manifest_seed": _format_number(entry.get("starting_seed")),
        "addon_seed": _format_number(entry.get("starting_seed")),
        "original_leaf_count": _format_number(obj_values.get("leaf_count")),
        "original_leaf_count_quality": leaf_quality,
        "addon_model_leaf_count": _format_number(addon_values.get("model_leaf_count")),
        "addon_active_leaf_count": _format_number(addon_values.get("active_leaf_count")),
        "addon_visible_leaf_count": _format_number(addon_values.get("visible_leaf_count")),
        "addon_suppressed_leaf_count": _format_number(addon_values.get("suppressed_leaf_count")),
        "addon_fallen_leaf_count": _format_number(addon_values.get("fallen_leaf_count")),
        "original_height_m": _format_number(obj_values.get("height_m")),
        "addon_height_m": _format_number(addon_values.get("height_m")),
        "height_difference_m": _format_number(
            (_number(addon_values.get("height_m")) - _number(obj_values.get("height_m")))
            if _number(addon_values.get("height_m")) is not None and _number(obj_values.get("height_m")) is not None else None
        ),
        "overall_status": overall,
        "status_counts": json.dumps(dict(statuses), sort_keys=True),
        "cause": cause,
        "notes": "; ".join(notes),
    }
    return rows, summary


def run_geometry_audit(original_dir: Path, addon_dir: Path, registry_path: Path,
                       manifest_path: Path, output_dir: Path,
                       abs_tolerance: float = 0.005,
                       rel_tolerance: float = 0.05) -> dict[str, Any]:
    registry_list = json.loads(registry_path.read_text(encoding="utf-8"))
    registry = {entry["id"]: entry for entry in registry_list if entry.get("id") != "header"}
    manifest, manifest_exists = load_manifest(manifest_path, original_dir, registry_path)
    tdo_path = addon_dir / "3D object library.tdo"
    tdo_library = TdoLibrary.from_file(str(tdo_path)) if tdo_path.exists() else TdoLibrary()
    library = SpeciesLibrary(str(addon_dir))
    long_rows: list[dict[str, str]] = []
    summary_rows: list[dict[str, str]] = []

    for raw_entry in manifest.get("occurrences", []):
        entry = dict(manifest.get("defaults", {}))
        entry.update(raw_entry)
        occurrence_id = entry.get("occurrence_id", "")
        source_file = entry.get("source_file", "")
        index = _integer(entry.get("occurrence_index")) or 1
        source = _source_info(original_dir, source_file, index, registry)
        addon_species_list = parse_pla_file(str(addon_dir / source_file)) if (addon_dir / source_file).exists() else []
        species = addon_species_list[index - 1] if index <= len(addon_species_list) else None
        age = _integer(entry.get("saved_age"))
        seed = _integer(entry.get("starting_seed"))
        if age is None:
            age = source.age
        if seed is None:
            seed = source.seed
        addon = (
            _addon_measurement(species, age, seed, tdo_library)
            if species is not None and age is not None and seed is not None
            else AddonMeasurement({}, [], "missing addon species, age, or seed")
        )
        obj_path = manifest_path.parent / str(entry.get("obj_file", ""))
        obj = parse_obj(obj_path) if obj_path.exists() else None
        rows, summary = compare_occurrence(
            entry, source, addon, obj, obj_path, original_dir, manifest_exists,
            abs_tolerance, rel_tolerance
        )
        long_rows.extend(rows)
        summary_rows.append(summary)

    output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(output_dir / "plant_geometry_long.csv", long_rows, LONG_COLUMNS)
    write_csv(output_dir / "plant_geometry_summary.csv", summary_rows, SUMMARY_COLUMNS)
    write_html(output_dir / "plant_geometry_report.html", long_rows, summary_rows)
    return {
        "manifest_exists": manifest_exists,
        "manifest_entries": len(summary_rows),
        "long_rows": long_rows,
        "summary_rows": summary_rows,
        "output_dir": output_dir,
    }


def write_csv(path: Path, rows: list[dict[str, str]], columns: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_html(path: Path, long_rows: list[dict[str, str]], summary_rows: list[dict[str, str]]) -> None:
    statuses = Counter(row["overall_status"] for row in summary_rows)
    cards = "".join(
        f'<div class="card"><strong>{html.escape(label)}</strong><span>{value}</span></div>'
        for label, value in (
            ("Occurrences", len(summary_rows)),
            ("Missing exports", sum(row["overall_status"] == "missing_original_export" for row in summary_rows)),
            ("Leaf issues", sum(row["overall_status"] in {"leaf_missing_from_model", "leaf_suppressed_in_draw", "extra_addon_leaf"} for row in summary_rows)),
            ("Height issues", sum(row["overall_status"] == "height_mismatch" for row in summary_rows)),
            ("Matches", statuses["match"]),
        )
    )
    summary_head = "".join(f"<th>{html.escape(column)}</th>" for column in SUMMARY_COLUMNS)
    summary_body = "".join(
        f'<tr class="{html.escape(row["overall_status"])}">'
        + "".join(f"<td>{html.escape(row.get(column, ""))}</td>" for column in SUMMARY_COLUMNS)
        + "</tr>"
        for row in summary_rows
    )
    detail_head = "".join(f"<th>{html.escape(column)}</th>" for column in LONG_COLUMNS)
    detail_body = "".join(
        f'<tr data-status="{html.escape(row["status"])}" data-search="{html.escape(" ".join(row.get(column, "") for column in LONG_COLUMNS).lower())}">'
        + "".join(f"<td>{html.escape(row.get(column, ""))}</td>" for column in LONG_COLUMNS)
        + "</tr>"
        for row in long_rows
    )
    document = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>PlantStudio semantic geometry audit</title>
<style>
:root {{ font-family: system-ui, sans-serif; color: #20272d; background: #f4f6f7; }}
body {{ margin: 0; padding: 24px; }}
h1 {{ margin: 0 0 8px; }}
p {{ max-width: 1000px; }}
.cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(145px, 1fr)); gap: 10px; margin: 20px 0; }}
.card {{ background: white; border: 1px solid #d5dde1; border-radius: 6px; padding: 12px; }}
.card strong, .card span {{ display: block; }} .card span {{ font-size: 1.4rem; margin-top: 4px; }}
section {{ background: white; border: 1px solid #d5dde1; border-radius: 6px; padding: 16px; margin: 18px 0; overflow: auto; }}
.controls {{ display: flex; flex-wrap: wrap; gap: 10px; margin-bottom: 12px; }}
input, select {{ padding: 8px; border: 1px solid #aeb8be; border-radius: 4px; min-width: 220px; }}
table {{ width: 100%; border-collapse: collapse; font-size: 12px; }}
th, td {{ border-bottom: 1px solid #e1e6e9; padding: 6px 8px; text-align: left; vertical-align: top; white-space: nowrap; }}
th {{ position: sticky; top: 0; background: #edf1f3; }}
tr.height_mismatch td, tr.leaf_missing_from_model td, tr.leaf_suppressed_in_draw td, tr.extra_addon_leaf td {{ background: #fff0f0; }}
tr.missing_original_export td, tr.ambiguous_original_count td {{ background: #fff9e6; }}
.hidden {{ display: none; }} small {{ color: #5e6970; }}
</style></head><body>
<h1>PlantStudio semantic output audit</h1>
<p>Semantic presence and silhouette comparison. Polygon and vertex counts are informational only because the Blender addon intentionally uses simplified geometry.</p>
<div class="cards">{cards}</div>
<section><h2>Occurrence summary</h2><p><small>Statuses: {html.escape(dict(statuses).__repr__())}</small></p>
<table><thead><tr>{summary_head}</tr></thead><tbody>{summary_body}</tbody></table></section>
<section><h2>Metric detail</h2><div class="controls"><label>Search <input id="search" type="search" placeholder="plant, metric, cause..."></label><label>Status <select id="status"><option value="">All statuses</option><option>match</option><option>leaf_missing_from_model</option><option>leaf_suppressed_in_draw</option><option>extra_addon_leaf</option><option>height_mismatch</option><option>silhouette_mismatch</option><option>missing_original_export</option><option>ambiguous_original_count</option><option>addon_error</option></select></label></div><p><small id="count"></small></p><table id="detail"><thead><tr>{detail_head}</tr></thead><tbody>{detail_body}</tbody></table></section>
<script>
const rows = Array.from(document.querySelectorAll('#detail tbody tr'));
const search = document.querySelector('#search'); const status = document.querySelector('#status'); const count = document.querySelector('#count');
function apply() {{ const needle = search.value.toLowerCase(); const selected = status.value; let visible = 0; rows.forEach(row => {{ const show = (!needle || row.dataset.search.includes(needle)) && (!selected || row.dataset.status === selected); row.classList.toggle('hidden', !show); if (show) visible += 1; }}); count.textContent = `${{visible}} of ${{rows.length}} metric rows visible`; }}
search.addEventListener('input', apply); status.addEventListener('change', apply); apply();
</script></body></html>"""
    path.write_text(document, encoding="utf-8", newline="\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--original-dir", type=Path, default=DEFAULT_ORIGINAL_DIR)
    parser.add_argument("--addon-dir", type=Path, default=DEFAULT_ADDON_DIR)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--init-manifest", action="store_true",
                        help="write a complete 76-occurrence manifest template and exit")
    parser.add_argument("--height-absolute-tolerance", type=float, default=0.005)
    parser.add_argument("--height-relative-tolerance", type=float, default=0.05)
    args = parser.parse_args(argv)
    if args.init_manifest:
        manifest = write_manifest_template(args.manifest, args.original_dir, args.registry)
        print(f"Wrote manifest template with {len(manifest['occurrences'])} occurrences: {args.manifest}")
        print("Export the original PlantStudio OBJ files to the manifest paths, then rerun without --init-manifest.")
        return 0
    result = run_geometry_audit(
        args.original_dir, args.addon_dir, args.registry, args.manifest, args.output_dir,
        args.height_absolute_tolerance, args.height_relative_tolerance,
    )
    counts = Counter(row["overall_status"] for row in result["summary_rows"])
    print(f"Compared {result['manifest_entries']} occurrences; statuses: {dict(counts)}")
    print(f"Reports: {result['output_dir']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
