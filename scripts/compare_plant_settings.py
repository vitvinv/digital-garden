"""Compare original PlantStudio settings with the Blender addon pipeline.

The report is deliberately source-aware. It reads raw .pla occurrences directly,
then reads the same occurrence through the current plantstudio_blender parser and
normalizer. This makes parser and normalization discrepancies visible instead of
assuming that identical input files imply identical behavior.

Usage:
    python scripts/compare_plant_settings.py
    python scripts/compare_plant_settings.py --output-dir reports/plant_settings
    python scripts/compare_plant_settings.py --fixture
"""

from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import html
import json
import math
import os
import re
import shutil
import sys
import tempfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from plantstudio_blender.core.math3d import SCurve
from plantstudio_blender.core.normalize import normalize_params
from plantstudio_blender.core.pla_parser import parse_color, parse_pla_file
from plantstudio_blender.core.tdo_parser import Tdo, TdoLibrary, parse_tdo_compact, parse_tdo_text


MISSING = object()
HEADER_RE = re.compile(r"^\[([^\]]+)\]\s+start PlantStudio plant", re.IGNORECASE)
PARAM_RE = re.compile(r"^.*?\[([^\]]+)\]\s*=\s*(.*)$")

LONG_COLUMNS = [
    "occurrence_id", "canonical_name", "canonical_key", "source_collection",
    "source_file", "source_occurrence_index", "plant_name", "field_no",
    "field_id", "field_name", "field_type", "transfer", "access",
    "original_presence", "original_line", "original_line_end",
    "original_raw_value", "original_parsed_value", "original_effective_value",
    "addon_presence", "addon_line", "addon_line_end", "addon_parsed_value",
    "addon_normalized_presence", "addon_normalized_value", "parser_status",
    "normalization_status", "status", "notes",
]

SUMMARY_COLUMNS = [
    "occurrence_id", "canonical_name", "canonical_key", "source_collection",
    "source_file", "source_occurrence_index", "plant_name", "field_count",
    "match_count", "numeric_tolerance_count", "format_only_count",
    "mismatch_count", "missing_count", "unsupported_count", "parse_error_count",
    "parser_gap_count", "normalization_change_count", "overall_status",
]

OCCURRENCE_COLUMNS = [
    "occurrence_id", "canonical_name", "canonical_key", "source_collection",
    "source_file", "source_occurrence_index", "plant_name", "source_sha256",
    "addon_sha256", "source_start_line", "source_end_line", "addon_start_line",
    "addon_end_line", "source_name_match", "duplicate_field_count",
]

CANONICAL_COLUMNS = [
    "canonical_name", "canonical_key", "variant_count", "variant_names",
    "occurrence_count", "occurrence_ids", "source_files", "field_count",
    "match_count", "numeric_tolerance_count", "format_only_count",
    "mismatch_count", "missing_count", "unsupported_count", "parse_error_count",
    "overall_status",
]


@dataclass
class RawSetting:
    field_id: str
    raw_value: str
    line_no: int
    end_line: int
    embedded_tdo: Tdo | None = None


@dataclass
class RawOccurrence:
    name: str
    source_file: str
    occurrence_index: int
    start_line: int
    end_line: int
    sha256: str
    settings: dict[str, RawSetting]
    duplicate_fields: tuple[str, ...] = ()


@dataclass(frozen=True)
class TdoValue:
    name: str
    geometry: tuple[Any, Any] | None
    source_kind: str


@dataclass
class OccurrenceData:
    source: RawOccurrence | None
    addon_species: Any = None
    addon_parse_error: str = ""
    addon_normalized_params: Any = None
    addon_raw: RawOccurrence | None = None


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _geometry_signature(tdo: Tdo | None) -> tuple[Any, Any] | None:
    if tdo is None:
        return None
    points = tuple(tuple(round(float(value), 9) for value in point) for point in tdo.points)
    triangles = tuple(tuple(int(value) for value in triangle) for triangle in tdo.triangles)
    return points, triangles


def _tdo_value(value: Any, library: TdoLibrary | None = None, source_kind: str = "parsed") -> TdoValue | object:
    if value is MISSING or value is None:
        return MISSING
    if isinstance(value, Tdo):
        return TdoValue(value.name, _geometry_signature(value), source_kind)
    if isinstance(value, str):
        name = value.strip()
        if not name:
            return MISSING
        library_tdo = library.get(name) if library is not None else None
        return TdoValue(name, _geometry_signature(library_tdo), "library_ref" if library_tdo else "name_ref")
    return TdoValue(str(value), None, source_kind)


def _parse_scalar(raw: str, field_type: int, library: TdoLibrary | None = None,
                  embedded_tdo: Tdo | None = None) -> Any:
    text = str(raw).strip()
    if field_type == 5:
        if embedded_tdo is not None:
            return _tdo_value(embedded_tdo, library, "embedded")
        compact_tdo = parse_tdo_compact(text)
        if compact_tdo is not None:
            return _tdo_value(compact_tdo, library, "compact_default")
        return _tdo_value(text, library, "name_ref")
    if field_type == 3:
        return parse_color(text)
    if field_type == 4:
        return text.lower() in ("true", "yes", "1", "t")
    if field_type in (2, 8):
        try:
            return int(float(text.split()[0]))
        except (IndexError, ValueError):
            return text
    if field_type == 6:
        try:
            return int(float(text.split()[0]))
        except (IndexError, ValueError):
            return text
    if field_type == 1:
        parts = text.split()
        try:
            numbers = [float(part) for part in parts]
        except ValueError:
            return text
        return numbers[0] if len(numbers) == 1 else numbers
    return text


def extract_occurrences(path: Path, registry: dict[str, dict],
                        tdo_library: TdoLibrary | None = None) -> list[RawOccurrence]:
    """Extract every raw plant occurrence and its registry setting lines."""
    lines = path.read_text(encoding="latin-1").splitlines()
    occurrences: list[RawOccurrence] = []
    current: RawOccurrence | None = None
    occurrence_index = 0
    duplicate_fields: list[str] = []
    i = 0

    def finish(end_line: int) -> None:
        nonlocal current, duplicate_fields
        if current is None:
            return
        current.end_line = max(current.start_line, end_line)
        current.duplicate_fields = tuple(sorted(set(duplicate_fields)))
        occurrences.append(current)
        current = None
        duplicate_fields = []

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        header = HEADER_RE.match(stripped)
        if header:
            if current is not None:
                finish(i)
            occurrence_index += 1
            current = RawOccurrence(
                name=header.group(1),
                source_file=path.name,
                occurrence_index=occurrence_index,
                start_line=i + 1,
                end_line=i + 1,
                sha256=_sha256(path),
                settings={},
            )
            i += 1
            continue

        if current is None:
            i += 1
            continue
        match = PARAM_RE.match(stripped)
        if not match:
            i += 1
            continue

        field_id = match.group(1)
        raw_value = match.group(2).strip()
        entry = registry.get(field_id)
        line_no = i + 1
        i += 1
        if entry is None:
            continue

        embedded_tdo = None
        end_line = line_no
        if entry.get("type") == 5 and i < len(lines):
            if lines[i].strip().lower().startswith("start 3d object"):
                i += 1
                block: list[str] = []
                while i < len(lines) and "end 3D object" not in lines[i]:
                    block.append(lines[i])
                    i += 1
                if i < len(lines):
                    end_line = i + 1
                    i += 1
                parsed_tdos = parse_tdo_text("\n".join(block))
                embedded_tdo = parsed_tdos[0] if parsed_tdos else None

        if field_id in current.settings:
            duplicate_fields.append(field_id)
        current.settings[field_id] = RawSetting(
            field_id=field_id,
            raw_value=raw_value,
            line_no=line_no,
            end_line=end_line,
            embedded_tdo=embedded_tdo,
        )

    if current is not None:
        finish(len(lines))
    return occurrences


def _lookup(container: Any, key: str) -> Any:
    if container is MISSING or container is None:
        return MISSING
    if isinstance(container, dict):
        if key in container:
            return container[key]
        lowered = key.lower()
        for candidate, value in container.items():
            if str(candidate).lower() == lowered:
                return value
        return MISSING
    if hasattr(container, key):
        return getattr(container, key)
    lowered = key.lower()
    for candidate in vars(container):
        if candidate.lower() == lowered:
            return getattr(container, candidate)
    return MISSING


def _walk(container: Any, segments: Iterable[str]) -> Any:
    current = container
    for segment in segments:
        bracket = re.match(r"^([^\[]+)\[([^\]]+)\]$", segment)
        if bracket:
            current = _lookup(current, bracket.group(1))
            current = _lookup(current, bracket.group(2))
        else:
            current = _lookup(current, segment)
        if current is MISSING:
            return MISSING
    return current


def resolve_access(params: Any, access: str) -> Any:
    """Resolve a registry access path against parsed or normalized params."""
    parts = access.split(".")
    base = parts[0]

    flower = re.match(r"^(pFlower|pInflor)\[([^\]]+)\]$", base)
    if flower:
        root = params.flowers if flower.group(1) == "pFlower" else params.inflors
        container = _lookup(root, flower.group(2))
        return _walk(container, parts[1:])

    if base == "basePoint_mm":
        return _walk(_lookup(params, "pGeneral"), parts[1:]) if len(parts) > 1 else MISSING
    if base in {"age", "drawingScale_PixelsPerMm", "hidden", "selectedWhenLastSaved",
                "xRotation", "yRotation", "zRotation"}:
        return _lookup(_lookup(params, "pGeneral"), base)

    special_roots = {
        ("pLeaf", "leafTdoParams"): "leafTdoParams",
        ("pLeaf", "stipuleTdoParams"): "stipuleTdoParams",
        ("pSeedlingLeaf", "leafTdoParams"): "seedlingTdoParams",
    }
    if len(parts) > 1 and (base, parts[1]) in special_roots:
        return _walk(_lookup(params, special_roots[(base, parts[1])]), parts[2:])
    if base == "pAxillaryBud" and len(parts) > 1 and parts[1] == "tdoParams":
        return _walk(_lookup(params, base), parts[2:])

    return _walk(_lookup(params, base), parts[1:])


def _scurve_list(value: SCurve) -> list[float]:
    return [float(value.x1), float(value.y1), float(value.x2), float(value.y2)]


def canonicalize(value: Any, field_type: int,
                 library: TdoLibrary | None = None) -> Any:
    """Convert parser/normalizer values to stable comparison values."""
    if value is MISSING or value is None:
        return MISSING
    if field_type == 5:
        if isinstance(value, TdoValue):
            return value
        return _tdo_value(value, library)
    if isinstance(value, SCurve):
        return _scurve_list(value)
    if field_type == 3 and isinstance(value, str):
        return parse_color(value)
    if field_type == 4 and isinstance(value, str):
        return value.lower() in ("true", "yes", "1", "t")
    if field_type in (2, 6, 8) and isinstance(value, (int, float)):
        return int(value)
    if field_type in (2, 6, 8) and isinstance(value, str):
        try:
            return int(float(value.split()[0]))
        except (IndexError, ValueError):
            return value
    if field_type == 1 and isinstance(value, str):
        parts = value.split()
        try:
            numbers = [float(part) for part in parts]
        except ValueError:
            return value
        return numbers[0] if len(numbers) == 1 else numbers
    if isinstance(value, tuple):
        return tuple(value)
    return value


def display_value(value: Any) -> str:
    if value is MISSING:
        return "<missing>"
    if isinstance(value, TdoValue):
        geometry = "embedded" if value.geometry else "no-geometry"
        return f"{value.name} [{geometry}; {value.source_kind}]"
    if isinstance(value, SCurve):
        return json.dumps(_scurve_list(value), separators=(",", ":"))
    if isinstance(value, (tuple, list)):
        return json.dumps(value, separators=(",", ":"), ensure_ascii=True)
    if isinstance(value, float):
        return format(value, ".15g")
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _json_value(value: Any) -> Any:
    if value is MISSING:
        return None
    if isinstance(value, TdoValue):
        return {
            "name": value.name,
            "geometry": value.geometry,
            "source_kind": value.source_kind,
        }
    if isinstance(value, SCurve):
        return _scurve_list(value)
    if isinstance(value, tuple):
        return list(value)
    return value


def _numeric_equal(a: Any, b: Any, tolerance: float) -> tuple[bool, bool]:
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        if len(a) != len(b):
            return False, False
        exact = all(float(x) == float(y) for x, y in zip(a, b))
        close = all(math.isclose(float(x), float(y), rel_tol=tolerance, abs_tol=tolerance)
                    for x, y in zip(a, b))
        return exact, close
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        exact = float(a) == float(b)
        close = math.isclose(float(a), float(b), rel_tol=tolerance, abs_tol=tolerance)
        return exact, close
    return False, False


def compare_values(original: Any, addon: Any, field_type: int,
                   tolerance: float = 1e-9) -> str:
    """Return a searchable comparison status for canonical values."""
    if original is MISSING and addon is MISSING:
        return "match"
    if original is MISSING:
        return "missing_original"
    if addon is MISSING:
        return "missing_addon"

    if field_type == 5:
        if isinstance(original, TdoValue) and isinstance(addon, TdoValue):
            if original.geometry is not None and addon.geometry is not None:
                if original.geometry == addon.geometry:
                    return "match" if original.name == addon.name else "format_only"
            return "match" if original.name == addon.name else "mismatch"
        return "match" if original == addon else "mismatch"

    if field_type in (1, 2, 6, 8) and (
            isinstance(original, (int, float, list, tuple))
            and isinstance(addon, (int, float, list, tuple))):
        exact, close = _numeric_equal(original, addon, tolerance)
        if exact:
            return "match"
        if close:
            return "numeric_tolerance"
        return "mismatch"

    if original == addon:
        return "match"
    if isinstance(original, str) and isinstance(addon, str) and " ".join(original.split()) == " ".join(addon.split()):
        return "format_only"
    return "mismatch"


def _entry_default(entry: dict[str, Any], library: TdoLibrary) -> Any:
    raw = entry.get("default")
    if raw is None:
        return MISSING
    return _parse_scalar(str(raw), int(entry.get("type", 0)), library)


def _status_counts(rows: list[dict[str, str]]) -> Counter:
    return Counter(row["status"] for row in rows)


def _overall_status(counts: Counter) -> str:
    if counts["parse_error"]:
        return "parse_error"
    if counts["mismatch"]:
        return "mismatch"
    if (counts["missing_addon"] or counts["missing_original"]
            or counts["unsupported"] or counts["parser_gap"]):
        return "incomplete"
    if counts["numeric_tolerance"] or counts["format_only"]:
        return "equivalent_nonexact"
    return "match"


def _source_collection(path: str) -> str:
    return Path(path).stem


def _canonical_key(name: str) -> str:
    return name.casefold()


def _make_occurrence_data(original_path: Path, addon_path: Path,
                          registry: dict[str, dict], library: TdoLibrary) -> tuple[list[RawOccurrence], list[RawOccurrence], dict[int, Any], dict[int, Any], str]:
    original = extract_occurrences(original_path, registry, library)
    addon_raw = extract_occurrences(addon_path, registry, library) if addon_path.exists() else []
    addon_species: dict[int, Any] = {}
    addon_normalized: dict[int, Any] = {}
    parse_error = ""
    if addon_path.exists():
        try:
            parsed = parse_pla_file(str(addon_path))
            for index, species in enumerate(parsed, 1):
                addon_species[index] = species
                normalized = copy.deepcopy(species.params)
                normalize_params(normalized)
                addon_normalized[index] = normalized
        except Exception as exc:  # report parser failures instead of aborting the audit
            parse_error = f"{type(exc).__name__}: {exc}"
    return original, addon_raw, addon_species, addon_normalized, parse_error


def build_rows(original_dir: Path, addon_dir: Path, registry: dict[str, dict],
               library: TdoLibrary) -> tuple[list[dict[str, str]], list[dict[str, str]], list[dict[str, str]], list[dict[str, str]]]:
    """Build long-form rows, occurrence summaries, and canonical summaries."""
    long_rows: list[dict[str, str]] = []
    summary_rows: list[dict[str, str]] = []
    occurrence_rows: list[dict[str, str]] = []
    paired: dict[tuple[str, int], OccurrenceData] = {}

    filenames = sorted({p.name for p in original_dir.glob("*.pla")} |
                       {p.name for p in addon_dir.glob("*.pla")})
    for filename in filenames:
        original_path = original_dir / filename
        addon_path = addon_dir / filename
        original, addon_raw, addon_species, addon_normalized, parse_error = _make_occurrence_data(
            original_path, addon_path, registry, library)
        max_occurrences = max(len(original), len(addon_raw), len(addon_species))
        for index in range(1, max_occurrences + 1):
            source = original[index - 1] if index <= len(original) else None
            addon_source = addon_raw[index - 1] if index <= len(addon_raw) else None
            paired[(filename, index)] = OccurrenceData(
                source=source,
                addon_species=addon_species.get(index),
                addon_parse_error=parse_error,
                addon_normalized_params=addon_normalized.get(index),
                addon_raw=addon_source,
            )

    for (filename, index), data in sorted(paired.items()):
        source = data.source
        addon_source = data.addon_raw
        name = source.name if source else (addon_source.name if addon_source else "<missing>")
        addon_name = addon_source.name if addon_source else "<missing>"
        occurrence_id = f"{filename}#{index}"
        canonical_key = _canonical_key(name)
        source_settings = source.settings if source else {}
        addon_settings = addon_source.settings if addon_source else {}
        field_rows: list[dict[str, str]] = []

        for field_no, entry in enumerate((e for e in registry.values() if e.get("id") != "header"), 1):
            field_id = entry["id"]
            field_type = int(entry.get("type", 0))
            source_setting = source_settings.get(field_id)
            addon_setting = addon_settings.get(field_id)
            original_explicit = source_setting is not None
            original_parsed = (
                _parse_scalar(source_setting.raw_value, field_type, library, source_setting.embedded_tdo)
                if source_setting else MISSING
            )
            original_effective = original_parsed if original_explicit else _entry_default(entry, library)
            addon_params = data.addon_species.params if data.addon_species is not None else None
            normalized_params = data.addon_normalized_params
            addon_parsed_raw = resolve_access(addon_params, entry["access"]) if addon_params is not None else MISSING
            addon_normalized_raw = resolve_access(normalized_params, entry["access"]) if normalized_params is not None else MISSING
            addon_parsed = canonicalize(addon_parsed_raw, field_type, library)
            addon_normalized = canonicalize(addon_normalized_raw, field_type, library)
            original_effective = canonicalize(original_effective, field_type, library)
            original_parsed = canonicalize(original_parsed, field_type, library)

            if data.addon_parse_error:
                parser_status = normalization_status = status = "parse_error"
            else:
                parser_status = compare_values(original_effective, addon_parsed, field_type)
                final_status = compare_values(original_effective, addon_normalized, field_type)
                if (parser_status == "missing_addon"
                        and not original_explicit
                        and final_status == "match"):
                    parser_status = "implicit_default"
                if addon_parsed is MISSING and addon_normalized is not MISSING:
                    normalization_status = (
                        "default_injected" if final_status == "match"
                        else "normalization_from_missing")
                elif addon_normalized is MISSING and addon_parsed is not MISSING:
                    normalization_status = "normalized_missing"
                else:
                    normalization_status = compare_values(addon_parsed, addon_normalized, field_type)
                status = final_status
                if addon_normalized is MISSING and addon_parsed is not MISSING:
                    status = "unsupported"
                elif addon_normalized is MISSING and original_effective is not MISSING:
                    status = "missing_addon"

            notes: list[str] = []
            if not original_explicit:
                notes.append("original registry default expanded")
            if source_setting and source_setting.embedded_tdo:
                notes.append("original embedded TDO")
            if addon_setting and addon_setting.embedded_tdo:
                notes.append("addon embedded TDO")
            if source and field_id in source.duplicate_fields:
                notes.append("duplicate source field; last value used")
            if name != addon_name and addon_name != "<missing>":
                notes.append("plant name differs between occurrences")
            if status == "format_only":
                notes.append("same TDO geometry or equivalent representation")

            row = {
                "occurrence_id": occurrence_id,
                "canonical_name": name,
                "canonical_key": canonical_key,
                "source_collection": _source_collection(filename),
                "source_file": filename,
                "source_occurrence_index": str(index),
                "plant_name": name,
                "field_no": str(entry.get("field_no", field_no)),
                "field_id": field_id,
                "field_name": entry.get("name", ""),
                "field_type": str(field_type),
                "transfer": str(entry.get("transfer", "")),
                "access": entry.get("access", ""),
                "original_presence": "explicit" if original_explicit else (
                    "implicit_default" if original_effective is not MISSING else "missing"),
                "original_line": str(source_setting.line_no if source_setting else ""),
                "original_line_end": str(source_setting.end_line if source_setting else ""),
                "original_raw_value": source_setting.raw_value if source_setting else str(entry.get("default", "")),
                "original_parsed_value": display_value(original_parsed),
                "original_effective_value": display_value(original_effective),
                "addon_presence": "explicit" if addon_setting else "missing",
                "addon_line": str(addon_setting.line_no if addon_setting else ""),
                "addon_line_end": str(addon_setting.end_line if addon_setting else ""),
                "addon_parsed_value": display_value(addon_parsed),
                "addon_normalized_presence": "explicit" if addon_setting else (
                    "implicit_default" if addon_normalized is not MISSING else "missing"),
                "addon_normalized_value": display_value(addon_normalized),
                "parser_status": parser_status,
                "normalization_status": normalization_status,
                "status": status,
                "notes": "; ".join(notes),
            }
            long_rows.append(row)
            field_rows.append(row)

        counts = _status_counts(field_rows)
        source_sha = source.sha256 if source else ""
        addon_sha = _sha256(addon_dir / filename) if (addon_dir / filename).exists() else ""
        parser_gap_count = sum(1 for row in field_rows
                               if row["parser_status"] in {
                                   "missing_addon", "missing_original", "unsupported",
                               })
        normalization_change_count = sum(1 for row in field_rows
                                         if row["normalization_status"] not in {
                                             "match", "default_injected",
                                         })
        counts["parser_gap"] = parser_gap_count
        occurrence_rows.append({
            "occurrence_id": occurrence_id,
            "canonical_name": name,
            "canonical_key": canonical_key,
            "source_collection": _source_collection(filename),
            "source_file": filename,
            "source_occurrence_index": str(index),
            "plant_name": name,
            "source_sha256": source_sha,
            "addon_sha256": addon_sha,
            "source_start_line": str(source.start_line if source else ""),
            "source_end_line": str(source.end_line if source else ""),
            "addon_start_line": str(addon_source.start_line if addon_source else ""),
            "addon_end_line": str(addon_source.end_line if addon_source else ""),
            "source_name_match": str(bool(source and addon_source and source.name == addon_source.name)).lower(),
            "duplicate_field_count": str(len(source.duplicate_fields) if source else 0),
        })
        summary_rows.append({
            "occurrence_id": occurrence_id,
            "canonical_name": name,
            "canonical_key": canonical_key,
            "source_collection": _source_collection(filename),
            "source_file": filename,
            "source_occurrence_index": str(index),
            "plant_name": name,
            "field_count": str(len(field_rows)),
            "match_count": str(counts["match"]),
            "numeric_tolerance_count": str(counts["numeric_tolerance"]),
            "format_only_count": str(counts["format_only"]),
            "mismatch_count": str(counts["mismatch"]),
            "missing_count": str(counts["missing_addon"] + counts["missing_original"]),
            "unsupported_count": str(counts["unsupported"]),
            "parse_error_count": str(counts["parse_error"]),
            "parser_gap_count": str(parser_gap_count),
            "normalization_change_count": str(normalization_change_count),
            "overall_status": _overall_status(counts),
        })

    canonical_groups: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in summary_rows:
        canonical_groups[row["canonical_key"]].append(row)
    canonical_rows: list[dict[str, str]] = []
    for canonical_key in sorted(canonical_groups):
        group = canonical_groups[canonical_key]
        name_counts = Counter(row["plant_name"] for row in group)
        canonical_name = sorted(name_counts, key=lambda value: (-name_counts[value], value.casefold(), value))[0]
        variant_names = sorted(name_counts, key=str.casefold)
        all_counts = Counter()
        for row in group:
            for key in ("match_count", "numeric_tolerance_count", "format_only_count",
                        "mismatch_count", "missing_count", "unsupported_count", "parse_error_count",
                        "parser_gap_count", "normalization_change_count"):
                all_counts[key] += int(row[key])
        canonical_rows.append({
            "canonical_name": canonical_name,
            "canonical_key": canonical_key,
            "variant_count": str(len(variant_names)),
            "variant_names": "; ".join(variant_names),
            "occurrence_count": str(len(group)),
            "occurrence_ids": "; ".join(row["occurrence_id"] for row in group),
            "source_files": "; ".join(sorted({row["source_file"] for row in group})),
            "field_count": str(sum(int(row["field_count"]) for row in group)),
            "match_count": str(all_counts["match_count"]),
            "numeric_tolerance_count": str(all_counts["numeric_tolerance_count"]),
            "format_only_count": str(all_counts["format_only_count"]),
            "mismatch_count": str(all_counts["mismatch_count"]),
            "missing_count": str(all_counts["missing_count"]),
            "unsupported_count": str(all_counts["unsupported_count"]),
            "parse_error_count": str(all_counts["parse_error_count"]),
            "overall_status": _overall_status(Counter({
                "mismatch": all_counts["mismatch_count"],
                "missing_addon": all_counts["missing_count"],
                "unsupported": all_counts["unsupported_count"],
                "parse_error": all_counts["parse_error_count"],
                "numeric_tolerance": all_counts["numeric_tolerance_count"],
                "format_only": all_counts["format_only_count"],
                "parser_gap": all_counts["parser_gap_count"],
            })),
        })
    return long_rows, summary_rows, occurrence_rows, canonical_rows


def write_csv(path: Path, rows: list[dict[str, str]], columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _html_table(rows: list[dict[str, str]], columns: list[str], status_column: str | None = None,
                limit: int | None = None) -> str:
    visible = rows if limit is None else rows[:limit]
    head = "".join(f"<th>{html.escape(column)}</th>" for column in columns)
    body_parts: list[str] = []
    for row in visible:
        status = row.get(status_column, "") if status_column else ""
        class_name = ""
        if status in {"mismatch", "parse_error"}:
            class_name = "bad"
        elif status in {"missing_addon", "missing_original", "unsupported", "incomplete"}:
            class_name = "warn"
        elif status in {"numeric_tolerance", "format_only", "equivalent_nonexact"}:
            class_name = "nonexact"
        searchable = " ".join(str(row.get(column, "")) for column in columns).lower()
        cells = "".join(f"<td>{html.escape(str(row.get(column, "")))}</td>" for column in columns)
        body_parts.append(f'<tr class="{class_name}" data-status="{html.escape(status)}" data-search="{html.escape(searchable)}">{cells}</tr>')
    return f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(body_parts)}</tbody></table>"


def write_html(path: Path, long_rows: list[dict[str, str]], summary_rows: list[dict[str, str]],
               occurrence_rows: list[dict[str, str]], canonical_rows: list[dict[str, str]]) -> None:
    counts = Counter(row["status"] for row in long_rows)
    occurrence_statuses = Counter(row["overall_status"] for row in summary_rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    summary_cards = "".join(
        f'<div class="card"><strong>{html.escape(label)}</strong><span>{value}</span></div>'
        for label, value in (
            ("Occurrences", len(occurrence_rows)),
            ("Canonical names", len(canonical_rows)),
            ("Fields compared", len(long_rows)),
            ("Mismatches", counts["mismatch"]),
            ("Incomplete", counts["missing_addon"] + counts["missing_original"] + counts["unsupported"]),
            ("Parser errors", counts["parse_error"]),
        )
    )
    summary_table = _html_table(summary_rows, SUMMARY_COLUMNS, "overall_status")
    occurrence_table = _html_table(occurrence_rows, OCCURRENCE_COLUMNS)
    canonical_table = _html_table(canonical_rows, CANONICAL_COLUMNS, "overall_status")
    long_table = _html_table(long_rows, LONG_COLUMNS, "status")
    document = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>PlantStudio settings comparison</title>
<style>
:root {{ color-scheme: light; font-family: system-ui, sans-serif; background: #f5f7f8; color: #1e252b; }}
body {{ margin: 0; padding: 24px; }}
h1 {{ margin: 0 0 6px; }}
p {{ max-width: 1100px; }}
.cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 10px; margin: 20px 0; }}
.card {{ background: white; border: 1px solid #d9e0e4; border-radius: 6px; padding: 12px; }}
.card strong, .card span {{ display: block; }}
.card span {{ font-size: 1.4rem; margin-top: 4px; }}
section {{ background: white; border: 1px solid #d9e0e4; border-radius: 6px; padding: 16px; margin: 18px 0; overflow: auto; }}
.controls {{ display: flex; flex-wrap: wrap; gap: 10px; margin-bottom: 12px; }}
input, select {{ padding: 8px; border: 1px solid #aebac2; border-radius: 4px; min-width: 220px; }}
table {{ border-collapse: collapse; width: 100%; font-size: 12px; }}
th, td {{ border-bottom: 1px solid #e1e6e9; padding: 6px 8px; text-align: left; vertical-align: top; white-space: nowrap; }}
th {{ position: sticky; top: 0; background: #edf1f3; z-index: 1; }}
tr.bad td {{ background: #fff0f0; }}
tr.warn td {{ background: #fff9e6; }}
tr.nonexact td {{ background: #f1f7ff; }}
small {{ color: #5e6b73; }}
.hidden {{ display: none; }}
</style>
</head>
<body>
<h1>PlantStudio settings comparison</h1>
<p>This registry-driven audit compares every original PlantStudio registry field with the raw addon parser value and the normalized value consumed by the Blender growth core. Original implicit registry defaults are expanded and marked in the detail table.</p>
<div class="cards">{summary_cards}</div>
<section>
<h2>Occurrence summary</h2>
<p><small>Source occurrences: {len(summary_rows)}. Overall statuses: {html.escape(dict(occurrence_statuses).__repr__())}</small></p>
{summary_table}
</section>
<section>
<h2>Source occurrence provenance</h2>
<p><small>These rows preserve source file hashes, line spans, duplicate-field counts, and source/addon name pairing.</small></p>
{occurrence_table}
</section>
<section>
<h2>Canonical plant names</h2>
<p><small>Case-sensitive names remain separate; the canonical key exposes case variants in the variant columns.</small></p>
{canonical_table}
</section>
<section>
<h2>Setting detail</h2>
<div class="controls">
<label>Search <input id="search" type="search" placeholder="plant, field, value, file..."></label>
<label>Status <select id="status"><option value="">All statuses</option><option>match</option><option>numeric_tolerance</option><option>format_only</option><option>mismatch</option><option>missing_addon</option><option>missing_original</option><option>unsupported</option><option>parse_error</option></select></label>
</div>
<p><small id="visible-count"></small></p>
<div id="detail-table">{long_table}</div>
</section>
<script>
const rows = Array.from(document.querySelectorAll('#detail-table tbody tr'));
const search = document.querySelector('#search');
const status = document.querySelector('#status');
const count = document.querySelector('#visible-count');
function applyFilter() {{
  const needle = search.value.toLowerCase();
  const selected = status.value;
  let visible = 0;
  rows.forEach(row => {{
    const matchesText = !needle || row.dataset.search.includes(needle);
    const matchesStatus = !selected || row.dataset.status === selected;
    const show = matchesText && matchesStatus;
    row.classList.toggle('hidden', !show);
    if (show) visible += 1;
  }});
  count.textContent = `${{visible}} of ${{rows.length}} setting rows visible`;
}}
search.addEventListener('input', applyFilter);
status.addEventListener('change', applyFilter);
applyFilter();
</script>
</body>
</html>
"""
    path.write_text(document, encoding="utf-8", newline="\n")


FIXTURE_FILENAME = "Garden flowers.pla"
FIXTURE_FIELD_ID = "kGeneralAgeAtMaturity"
FIXTURE_TDO_FILENAME = "3D object library.tdo"


def _increment_fixture_value(value: str) -> str:
    number = float(value)
    if number.is_integer():
        return str(int(number) + 1)
    return format(number + 1, ".15g")


def create_divergent_fixture(source_dir: Path, addon_dir: Path, workspace: Path,
                             filename: str = FIXTURE_FILENAME,
                             field_id: str = FIXTURE_FIELD_ID) -> dict[str, str]:
    """Create isolated original/addon copies with one intentional addon mismatch."""
    original_path = source_dir / filename
    addon_path = addon_dir / filename
    if not original_path.exists():
        raise FileNotFoundError(f"Fixture source file does not exist: {original_path}")
    if not addon_path.exists():
        raise FileNotFoundError(f"Fixture addon file does not exist: {addon_path}")

    fixture_original_dir = workspace / "original"
    fixture_addon_dir = workspace / "addon"
    fixture_original_dir.mkdir(parents=True, exist_ok=True)
    fixture_addon_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(original_path, fixture_original_dir / filename)
    shutil.copy2(addon_path, fixture_addon_dir / filename)
    tdo_path = addon_dir / FIXTURE_TDO_FILENAME
    if tdo_path.exists():
        shutil.copy2(tdo_path, fixture_addon_dir / FIXTURE_TDO_FILENAME)

    addon_text = (fixture_addon_dir / filename).read_text(encoding="latin-1")
    pattern = re.compile(
        rf"^(?P<prefix>.*\[{re.escape(field_id)}\]\s*=\s*)"
        rf"(?P<value>-?\d+(?:\.\d+)?)(?P<suffix>.*)$",
        re.MULTILINE,
    )
    match = pattern.search(addon_text)
    if match is None:
        raise ValueError(f"Could not find a numeric [{field_id}] setting in {filename}")
    original_value = match.group("value")
    mutated_value = _increment_fixture_value(original_value)
    mutated_text = pattern.sub(
        lambda found: f"{found.group('prefix')}{mutated_value}{found.group('suffix')}",
        addon_text,
        count=1,
    )
    (fixture_addon_dir / filename).write_text(mutated_text, encoding="latin-1", newline="\n")
    return {
        "source_file": filename,
        "field_id": field_id,
        "occurrence_index": "1",
        "original_value": original_value,
        "mutated_value": mutated_value,
    }


def run_fixture_audit(original_dir: Path, addon_dir: Path, registry_path: Path,
                      output_dir: Path, filename: str = FIXTURE_FILENAME,
                      field_id: str = FIXTURE_FIELD_ID) -> dict[str, Any]:
    """Generate a small report from an isolated copy with one known mismatch."""
    output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="plant-settings-fixture-") as temporary:
        fixture = create_divergent_fixture(
            original_dir, addon_dir, Path(temporary), filename, field_id
        )
        result = run_audit(
            Path(temporary) / "original",
            Path(temporary) / "addon",
            registry_path,
            output_dir,
        )
    manifest = {
        "description": "Temporary addon copy with one intentional setting mismatch.",
        "fixture": fixture,
    }
    (output_dir / "fixture_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    result["fixture"] = fixture
    return result


def run_audit(original_dir: Path, addon_dir: Path, registry_path: Path,
              output_dir: Path) -> dict[str, Any]:
    with registry_path.open(encoding="utf-8") as handle:
        registry_list = json.load(handle)
    registry = {entry["id"]: entry for entry in registry_list if entry.get("id") != "header"}
    library_path = addon_dir / "3D object library.tdo"
    library = TdoLibrary.from_file(str(library_path)) if library_path.exists() else TdoLibrary()
    long_rows, summary_rows, occurrence_rows, canonical_rows = build_rows(original_dir, addon_dir, registry, library)
    write_csv(output_dir / "plant_settings_long.csv", long_rows, LONG_COLUMNS)
    write_csv(output_dir / "plant_settings_summary.csv", summary_rows, SUMMARY_COLUMNS)
    write_csv(output_dir / "plant_settings_occurrences.csv", occurrence_rows, OCCURRENCE_COLUMNS)
    write_csv(output_dir / "plant_settings_canonical.csv", canonical_rows, CANONICAL_COLUMNS)
    write_html(output_dir / "plant_settings_report.html", long_rows, summary_rows, occurrence_rows, canonical_rows)
    return {
        "registry_fields": len(registry),
        "long_rows": len(long_rows),
        "summary_rows": summary_rows,
        "occurrence_rows": occurrence_rows,
        "canonical_rows": canonical_rows,
        "output_dir": output_dir,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--original-dir", type=Path,
                        default=ROOT / "examples" / "PlantStudio2")
    parser.add_argument("--addon-dir", type=Path,
                        default=ROOT / "plantstudio_blender" / "data")
    parser.add_argument("--registry", type=Path,
                        default=ROOT / "plantstudio_blender" / "core" / "param_registry.json")
    parser.add_argument("--output-dir", type=Path,
                        default=ROOT / "reports" / "plant_settings")
    parser.add_argument("--fixture", action="store_true",
                        help="write a small report with one intentional addon mismatch")
    parser.add_argument("--fixture-output-dir", type=Path, default=None,
                        help="where --fixture artifacts are written")
    parser.add_argument("--fixture-file", default=FIXTURE_FILENAME,
                        help=f"source collection to copy for --fixture (default: {FIXTURE_FILENAME})")
    parser.add_argument("--fixture-field", default=FIXTURE_FIELD_ID,
                        help=f"numeric field to mutate for --fixture (default: {FIXTURE_FIELD_ID})")
    args = parser.parse_args(argv)
    if args.fixture:
        fixture_output = args.fixture_output_dir or args.output_dir / "fixture"
        result = run_fixture_audit(
            args.original_dir,
            args.addon_dir,
            args.registry,
            fixture_output,
            args.fixture_file,
            args.fixture_field,
        )
        fixture = result["fixture"]
        print(f"Fixture changed {fixture['source_file']} occurrence {fixture['occurrence_index']} "
              f"[{fixture['field_id']}] from {fixture['original_value']} to {fixture['mutated_value']}.")
    else:
        result = run_audit(args.original_dir, args.addon_dir, args.registry, args.output_dir)
    counts = Counter(row["overall_status"] for row in result["summary_rows"])
    print(f"Compared {result['registry_fields']} registry fields across "
          f"{len(result['summary_rows'])} occurrences ({len(result['canonical_rows'])} canonical names).")
    print(f"Long rows: {result['long_rows']}; occurrence statuses: {dict(counts)}")
    print(f"Reports: {result['output_dir']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
