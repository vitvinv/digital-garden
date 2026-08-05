"""PdLeaf port — leaf attached to an internode."""

from . import math3d as umath
from .meristem import (PdPlantPart, kPartTypeLeaf, kActivityFree, kActivityNextDay)


class PdLeaf(PdPlantPart):
    def __init__(self, plant=None):
        super().__init__(plant)
        self.isSeedlingLeaf = False
        self.leafColor = None
        self.petioleColor = None

    def partType(self):
        return kPartTypeLeaf

    def getName(self):
        return "leaf"

    def newWithPlantFractionOfOptimalSize(self, plant, aFraction):
        self.plant = plant
        self.liveBiomass_pctMPB = aFraction * PdLeaf.optimalInitialBiomass_pctMPB(plant)
        self.deadBiomass_pctMPB = 0.0
        self.leafColor = getattr(plant.pLeaf, "faceColor", None)
        self.petioleColor = getattr(plant.pLeaf, "petioleColor", None)
        return self

    @staticmethod
    def optimalInitialBiomass_pctMPB(plant):
        return plant.pLeaf.optimalBiomass_pctMPB * \
            getattr(plant.pLeaf, "optimalFractionOfOptimalBiomassAtCreation_frn", 0.2)

    def nextDay(self):
        super().nextDay()
        # leaf grows toward optimal via linear growth (implemented in biomass allocation)
        pass

    def traverseActivity(self, mode, traverser):
        if mode == kActivityNextDay:
            self.nextDay()
        elif mode == kActivityFree:
            pass

    def draw(self):
        pass
