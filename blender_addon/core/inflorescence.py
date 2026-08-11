"""PdInflorescence + PdFlowerFruit port — reproductive structures."""

from . import math3d as umath
from .meristem import (PdPlantPart, kPartTypeInflorescence, kPartTypeFlowerFruit,
                       kActivityNextDay, kActivityDemandReproductive,
                       kActivityGrowReproductive, kActivityDraw, kActivityFree)


def _gp(obj, name, default=0.0):
    """Get param from dict or object."""
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


class PdFlowerFruit(PdPlantPart):
    def __init__(self, plant=None):
        super().__init__(plant)
        self.isOpen = False
        self.hasSetFruit = False
        self.isRipe = False
        self.daysAccumulatingFruitBiomass = 0

    def partType(self):
        return kPartTypeFlowerFruit

    def getName(self):
        return "flower/fruit"

    def nextDay(self):
        super().nextDay()
        p = self.plant.pFlower[self.gender]
        if not self.isOpen:
            if self.age >= _gp(p, "minDaysToOpenFlower", 3):
                self.isOpen = True
        if not self.hasSetFruit:
            minDays = _gp(p, "minDaysBeforeSettingFruit", 3)
            minFract = _gp(p, "minFractionOfOptimalBiomassToCreateFruit_frn", 0.8)
            biomassReached = self.liveBiomass_pctMPB >= _gp(p, "optimalBiomass_pctMPB") * minFract
            deadlineReached = self.age > _gp(p, "maxDaysToGrowIfOverMinFraction", 30)
            if self.age >= minDays and (biomassReached or deadlineReached):
                self.hasSetFruit = True
                self.daysAccumulatingFruitBiomass = 0
        elif not self.isRipe:
            daysToRipen = self._days_to_ripen()
            if self.daysAccumulatingFruitBiomass >= daysToRipen:
                self.isRipe = True
            self.daysAccumulatingFruitBiomass += 1

    def _days_to_ripen(self):
        """pFruit.DaysToRipen — days of fruit biomass before turning ripe."""
        fruit = getattr(self.plant, "params", None)
        fruit = getattr(fruit, "pFruit", None)
        return int(_gp(fruit, "daysToRipen", 5) or 5)

    def traverseActivity(self, mode, traverser):
        """Flowers demand and grow reproductive biomass toward optimal,
        matching the original — required for hasSetFruit to trigger."""
        if self.hasFallenOff and mode != kActivityFree:
            return
        if mode == kActivityNextDay:
            self.nextDay()
        elif mode == kActivityDemandReproductive:
            # The original flower demand has NO age cap — it demands toward
            # the flower's own optimal biomass every day until it is reached
            # (linearGrowthResult returns 0 once current >= optimal).
            p = self.plant.pFlower[self.gender]
            self.biomassDemand_pctMPB = umath.linearGrowthResult(
                self.liveBiomass_pctMPB, _gp(p, "optimalBiomass_pctMPB"),
                _gp(p, "minDaysToGrow", 3))
            traverser.total += self.biomassDemand_pctMPB
        elif mode == kActivityGrowReproductive:
            newBiomass = self.biomassDemand_pctMPB * traverser.fractionOfPotentialBiomass
            self.liveBiomass_pctMPB += newBiomass
        elif mode == kActivityFree:
            pass


class PdInflorescence(PdPlantPart):
    def __init__(self, plant=None):
        super().__init__(plant)
        self.flowers = []
        self.daysSinceLastFlowerAppeared = 0
        self.daysSinceStartedMakingFlowers = 0
        self.fractionOfOptimalSizeWhenCreated = 1.0
        self.numFlowers = 0
        self.numFlowersEachDay = 0
        self.daysBetweenFlowerAppearances = 0
        self.meristemThatCreatedMe = None

    def partType(self):
        return kPartTypeInflorescence

    def getName(self):
        return "inflorescence"

    def initializeGenderApicalOrAxillary(self, plant, gender, initAsApical, fractionOfOptimalSize):
        self.plant = plant
        self.gender = gender
        self.isApical = initAsApical
        self.daysSinceLastFlowerAppeared = 0
        self.daysSinceStartedMakingFlowers = 0
        self.fractionOfOptimalSizeWhenCreated = umath.min(1.0, fractionOfOptimalSize)
        p = plant.pInflor[gender]
        daysToAllFlowers = _gp(p, "daysToAllFlowersCreated", 10)
        self.numFlowers = int(_gp(p, "numFlowersOnMainBranch", 1)) + \
            int(_gp(p, "numFlowersPerBranch", 1)) * int(_gp(p, "numBranches", 0))
        self.daysBetweenFlowerAppearances = 0
        self.numFlowersEachDay = 0
        if self.numFlowers > 0:
            if self.numFlowers == 1 or self.numFlowers == daysToAllFlowers:
                self.numFlowersEachDay = 1
            elif self.numFlowers > daysToAllFlowers:
                self.numFlowersEachDay = max(1, int(round(self.numFlowers / daysToAllFlowers)))
            else:
                self.daysBetweenFlowerAppearances = max(1, int(round(daysToAllFlowers / self.numFlowers)))

    @staticmethod
    def optimalInitialBiomass_pctMPB(plant, gender):
        if gender < 0 or gender > 1:
            return 0.0
        p = plant.pInflor[gender]
        return _gp(p, "optimalBiomass_pctMPB") * \
            _gp(p, "minFractionOfOptimalBiomassToCreateInflorescence_frn", 0.2)

    def nextDay(self):
        super().nextDay()
        for flower in list(self.flowers):
            flower.nextDay()
        p = self.plant.pInflor[self.gender]
        biomassToMakeFlowers = _gp(p, "minFractionOfOptimalBiomassToMakeFlowers_frn", 0.5) \
            * _gp(p, "optimalBiomass_pctMPB")
        if self.liveBiomass_pctMPB >= biomassToMakeFlowers:
            self.daysSinceStartedMakingFlowers += 1
            if len(self.flowers) <= 0 and self.numFlowers > 0:
                self.createFlower()
            elif len(self.flowers) < self.numFlowers:
                if self.daysBetweenFlowerAppearances > 0:
                    if self.daysSinceLastFlowerAppeared >= self.daysBetweenFlowerAppearances:
                        self.createFlower()
                        self.daysSinceLastFlowerAppeared = 0
                    else:
                        self.daysSinceLastFlowerAppeared += 1
                else:
                    n = umath.min(self.numFlowersEachDay, self.numFlowers - len(self.flowers))
                    for _ in range(int(n)):
                        self.createFlower()
                    self.daysSinceLastFlowerAppeared = 0

    def createFlower(self):
        max_parts = self.plant.maxPartsPerPlant
        if self.plant.partsCreated > max_parts:
            return
        flower = PdFlowerFruit(self.plant)
        flower.gender = self.gender
        flower.phytomerAttachedTo = self
        # The original initializes flowers at zero biomass
        # (ufruit.initializeGender sets liveBiomass_pctMPB = 0.0) and grows
        # them via reproductive demand toward the FLOWER's own optimal
        # biomass (pFlower.optimalBiomass_pctMPB) — not the inflorescence's.
        flower.liveBiomass_pctMPB = 0.0
        self.flowers.append(flower)
        self.plant.partsCreated += 1

    def traverseActivity(self, mode, traverser):
        if mode != kActivityDraw:
            for flower in list(self.flowers):
                flower.traverseActivity(mode, traverser)
        if mode == kActivityNextDay:
            self.nextDay()
        elif mode == kActivityDemandReproductive:
            p = self.plant.pInflor[self.gender]
            if self.age > _gp(p, "maxDaysToGrow", 10):
                self.biomassDemand_pctMPB = 0.0
                return
            self.biomassDemand_pctMPB = umath.linearGrowthResult(
                self.liveBiomass_pctMPB, _gp(p, "optimalBiomass_pctMPB"),
                _gp(p, "minDaysToGrow", 3))
            traverser.total += self.biomassDemand_pctMPB
        elif mode == kActivityGrowReproductive:
            self.liveBiomass_pctMPB += self.biomassDemand_pctMPB * traverser.fractionOfPotentialBiomass
        elif mode == kActivityDraw:
            from .draw import draw_inflorescence
            draw_inflorescence(self)
