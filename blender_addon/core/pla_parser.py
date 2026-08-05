"""Parse PlantStudio .pla plant species files.

Format:
    [species name] start PlantStudio plant <v2.0>
    ; comment
    Param Name [kFieldID] =value
      start 3D object
      Name=...
      Point=0 0 0
      Triangle=1 2 3
      end 3D object
    [next species] start PlantStudio plant <v2.0>
"""

import os
import json
from .tdo_parser import Tdo

_FIELD_TYPES = {
    1: "float", 2: "smallint", 3: "color", 4: "boolean",
    5: "tdo", 6: "enum", 8: "longint",
}

_registry = None


def load_registry():
    """Load the parameter registry (fieldID -> access string)."""
    global _registry
    if _registry is None:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "param_registry.json")
        with open(path, encoding="utf-8") as f:
            _registry = json.load(f)
    return _registry


def registry_by_id():
    reg = {}
    for entry in load_registry():
        if entry["id"] != "header":
            reg[entry["id"]] = entry
    return reg


def parse_bool(value):
    return value.strip().lower() in ("true", "yes", "1", "t")


def parse_color(value):
    """'r g b' or 'r g b a' -> (r, g, b) ints 0-255."""
    parts = value.split()
    try:
        return (int(float(parts[0])), int(float(parts[1])), int(float(parts[2])))
    except (ValueError, IndexError):
        return None


def set_param(params, access, ftype, value, tdo=None):
    """
    Apply a parsed value to the params object using the access string.
    access like 'pGeneral.LineDivisions', 'pLeaf.leafTdoParams.FaceColor',
    'pFlower[kGenderFemale].tdoParams[kFirstPetals].FaceColor'.
    """
    if not access:
        return
    parts = access.split(".")
    base = parts[0]

    if base.startswith("pFlower"):
        gender_key = base[base.find("[") + 1:base.find("]")]
        obj = params.flowers.setdefault(gender_key, {})
        rest = parts[1:]
        if len(rest) >= 2 and rest[0].startswith("tdoParams"):
            part_key = rest[0][rest[0].find("[") + 1:rest[0].find("]")]
            tdo_obj = obj.setdefault("tdoParams", {}).setdefault(part_key, TdoParamsCompat())
            _set_tdo_attr(tdo_obj, rest[1], ftype, value, tdo)
            return
        if len(rest) == 1:
            _set_dict_attr(obj, rest[0], ftype, value)
        return

    # resolve base object
    if base == "pAxillaryBud":
        obj = params.pAxillaryBud
    elif base == "pLeaf":
        obj = params.pLeaf
    elif base == "pSeedlingLeaf":
        obj = params.pSeedlingLeaf
    else:
        obj = getattr(params, base, None)
        if obj is None:
            return

    # walk remaining path; recognize tdo params containers
    rest = parts[1:]
    if len(rest) == 0:
        return
    first = rest[0]

    # tdo params containers are attributes on the PlantParams root
    # (e.g. params.leafTdoParams, params.stipuleTdoParams, params.pAxillaryBud)
    if first in ("tdoParams", "leafTdoParams", "stipuleTdoParams", "seedlingTdoParams"):
        container = None
        if first == "tdoParams":
            # pAxillaryBud.tdoParams.X -> params.pAxillaryBud
            container = params.pAxillaryBud if base == "pAxillaryBud" else getattr(params, "pAxillaryBud", None)
        else:
            container = getattr(params, first, None)
        if container is None:
            return
        _set_tdo_attr(container, rest[1] if len(rest) > 1 else "object3D", ftype, value, tdo)
        return
    if first.startswith("tdoParams[") or first.startswith("leafTdoParams[") \
            or first.startswith("stipuleTdoParams["):
        container_attr = first.split("[")[0]
        key = first[first.find("[") + 1:first.find("]")]
        container = getattr(params, container_attr, None)
        if container is None:
            return
        tdo_obj = container.setdefault(key, TdoParamsCompat())
        _set_tdo_attr(tdo_obj, rest[1] if len(rest) > 1 else "object3D", ftype, value, tdo)
        return

    # regular attribute path (e.g. pGeneral.ageAtMaturity)
    _set_attr(obj, first, ftype, value)


class TdoParamsCompat:
    """Minimal tdo params container for flower parts."""
    def __init__(self):
        self.object3D = None
        self.scaleAtFullSize = 0.0
        self.xRotationBeforeDraw = 0.0
        self.yRotationBeforeDraw = 0.0
        self.zRotationBeforeDraw = 0.0
        self.faceColor = None
        self.backfaceColor = None
        self.repetitions = 1
        self.radiallyArranged = True
        self.pullBackAngle = 0.0


def _set_tdo_attr(tdo_obj, attr, ftype, value, tdo):
    if attr in ("object3D", "object3D"):
        tdo_obj.object3D = tdo if tdo is not None else value
        return
    if attr == "FaceColor" or attr == "faceColor":
        tdo_obj.faceColor = parse_color(value) if isinstance(value, str) else value
        return
    if attr == "BackfaceColor" or attr == "backfaceColor":
        tdo_obj.backfaceColor = parse_color(value) if isinstance(value, str) else value
        return
    if attr == "repetitions":
        try:
            tdo_obj.repetitions = int(float(value))
        except (ValueError, TypeError):
            pass
        return
    if attr == "radiallyArranged":
        tdo_obj.radiallyArranged = parse_bool(value)
        return
    if attr == "pullBackAngle":
        try:
            tdo_obj.pullBackAngle = float(value)
        except (ValueError, TypeError):
            pass
        return
    try:
        setattr(tdo_obj, attr, float(value))
    except (ValueError, TypeError):
        setattr(tdo_obj, attr, value)


def _set_attr(obj, attr, ftype, value):
    if ftype == 4:  # boolean
        setattr(obj, attr, parse_bool(value))
    elif ftype == 3:  # color
        setattr(obj, attr, parse_color(value))
    elif ftype in (1, 2, 8):  # float / smallint / longint
        try:
            setattr(obj, attr, float(value))
        except ValueError:
            setattr(obj, attr, value)
    elif ftype == 6:  # enumerated list (numeric first token)
        try:
            setattr(obj, attr, int(float(value.split()[0])))
        except (ValueError, IndexError):
            setattr(obj, attr, value)
    else:
        setattr(obj, attr, value)


def _set_dict_attr(d, attr, ftype, value):
    """Like _set_attr but for dict-stored flower params."""
    if ftype == 4:
        d[attr] = parse_bool(value)
    elif ftype == 3:
        d[attr] = parse_color(value)
    elif ftype in (1, 2, 8):
        try:
            d[attr] = float(value)
        except ValueError:
            d[attr] = value
    elif ftype == 6:
        try:
            d[attr] = int(float(value.split()[0]))
        except (ValueError, IndexError):
            d[attr] = value
    else:
        d[attr] = value


class PlantSpecies:
    """A parsed plant species: name + params."""

    def __init__(self, name):
        self.name = name
        from .params import PlantParams
        self.params = PlantParams()

    def __repr__(self):
        return f"PlantSpecies({self.name!r})"


def parse_pla_file(path):
    """Parse a .pla file into a list of PlantSpecies."""
    from .params import PlantParams
    registry = registry_by_id()
    species_list = []
    current = None

    with open(path, encoding="latin-1") as f:
        lines = f.readlines()

    i = 0
    while i < len(lines):
        raw = lines[i]
        line = raw.strip()
        i += 1
        if not line or line.startswith(";"):
            continue
        if line.startswith("[") and "start PlantStudio plant" in line:
            name = line[1:line.find("]")]
            current = PlantSpecies(name)
            species_list.append(current)
            continue
        if current is None:
            continue
        if "=" not in line or "[" not in line:
            continue
        # parameter line: Name [kFieldID] =value
        name_part = line[:line.find("[")]
        field_id = line[line.find("[") + 1:line.find("]")]
        eq = line.find("=")
        value = line[eq + 1:].strip()
        entry = registry.get(field_id)
        if entry is None:
            # unknown key: skip (but still consume embedded tdo block if any)
            if value.startswith("start 3D object"):
                while i < len(lines) and "end 3D object" not in lines[i]:
                    i += 1
                i += 1
            continue
        ftype = entry["type"]
        if ftype == 5:  # tdo — may be a name or an embedded block
            tdo = None
            if value.startswith("start 3D object"):
                block = []
                while i < len(lines) and "end 3D object" not in lines[i]:
                    block.append(lines[i])
                    i += 1
                i += 1  # consume end 3D object
                tdos = _parse_tdo_block(block)
                tdo = tdos[0] if tdos else None
            set_param(current.params, entry["access"], ftype, value, tdo)
        else:
            set_param(current.params, entry["access"], ftype, value)

    return species_list


def _parse_tdo_block(block_lines):
    from .tdo_parser import parse_tdo_text
    return parse_tdo_text("".join(block_lines))
