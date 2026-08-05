"""Species library: load .pla files and list species."""

import os
import glob
from .pla_parser import parse_pla_file


class SpeciesLibrary:
    def __init__(self, data_dir):
        self.data_dir = data_dir
        self.species = []
        self._by_name = {}
        self.load()

    def load(self):
        self.species = []
        self._by_name = {}
        if not os.path.isdir(self.data_dir):
            return
        for path in sorted(glob.glob(os.path.join(self.data_dir, "*.pla"))):
            try:
                species = parse_pla_file(path)
                for s in species:
                    self.species.append(s)
                    self._by_name[s.name] = s
            except Exception as e:
                print(f"[PlantStudio] failed to parse {path}: {e}")

    def names(self):
        return [s.name for s in self.species]

    def get(self, name):
        return self._by_name.get(name)

    def __len__(self):
        return len(self.species)

    def __repr__(self):
        return f"SpeciesLibrary({len(self.species)} species from {self.data_dir})"
