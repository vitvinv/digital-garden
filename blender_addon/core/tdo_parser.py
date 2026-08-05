"""Parse PlantStudio .tdo 3D object files.

Format (text):
    Name=Tutorial leaf
      Point=0 0 0
      Triangle=1 2 3
"""


class Tdo:
    def __init__(self, name, points, triangles):
        self.name = name
        self.points = points          # list of (x, y, z)
        self.triangles = triangles    # list of (i, j, k) 1-based indices

    def __repr__(self):
        return f"Tdo({self.name!r}, {len(self.points)} pts, {len(self.triangles)} tris)"


def parse_tdo_file(path):
    """Parse a .tdo file into a list of Tdo objects."""
    tdos = []
    current = None
    with open(path, encoding="latin-1") as f:
        for raw in f:
            line = raw.strip()
            if not line:
                continue
            if line.startswith("Name="):
                current = Tdo(line[len("Name="):].strip(), [], [])
                tdos.append(current)
            elif line.startswith("Point=") and current is not None:
                vals = line[len("Point="):].split()
                current.points.append((float(vals[0]), float(vals[1]), float(vals[2])))
            elif line.startswith("Triangle=") and current is not None:
                vals = line[len("Triangle="):].split()
                current.triangles.append((int(vals[0]), int(vals[1]), int(vals[2])))
    return tdos


def parse_tdo_text(text):
    """Parse .tdo content from a string (used for embedded TDOs in .pla)."""
    tdos = []
    current = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("Name="):
            current = Tdo(line[len("Name="):].strip(), [], [])
            tdos.append(current)
        elif line.startswith("Point=") and current is not None:
            vals = line[len("Point="):].split()
            current.points.append((float(vals[0]), float(vals[1]), float(vals[2])))
        elif line.startswith("Triangle=") and current is not None:
            vals = line[len("Triangle="):].split()
            current.triangles.append((int(vals[0]), int(vals[1]), int(vals[2])))
    return tdos


class TdoLibrary:
    """Named 3D object library loaded from a .tdo file."""

    def __init__(self, tdos=None):
        self._by_name = {}
        for t in (tdos or []):
            self._by_name[t.name] = t

    def get(self, name):
        return self._by_name.get(name)

    def names(self):
        return list(self._by_name.keys())

    def __len__(self):
        return len(self._by_name)

    @classmethod
    def from_file(cls, path):
        return cls(parse_tdo_file(path))
