"""Normalize parsed species params into the attribute names the simulation uses.

The .pla parser sets attributes using the exact access strings from the
PlantStudio registry (mixed case, e.g. 'OptimalFinalBiomass_pctMPB').
The simulation code uses snake_case names. This module maps between them
and fills defaults for parameters absent from a species file.
"""

from .math3d import SCurve  # noqa: F401 (kept for clarity)


def _get(obj, *names, default=None):
    for n in names:
        if obj is not None and hasattr(obj, n):
            return getattr(obj, n)
    return default


def _ensure(obj, name, value):
    if not hasattr(obj, name):
        setattr(obj, name, value)
    return getattr(obj, name)


def normalize_general(params):
    g = params.pGeneral
    _ensure(g, "lineDivisions", int(_get(g, "LineDivisions", default=3)))
    _ensure(g, "randomSway", float(_get(g, "randomSway", default=0.0)))
    _ensure(g, "ageAtMaturity", float(_get(g, "ageAtMaturity", default=100)))
    _ensure(g, "ageAtWhichFloweringStarts", float(_get(g, "ageAtWhichFloweringStarts", default=60)))
    _ensure(g, "fractionReproductiveAllocationAtMaturity_frn",
            float(_get(g, "fractionReproductiveAllocationAtMaturity_frn", default=0.6)))
    _ensure(g, "maleFlowersAreSeparate", bool(_get(g, "MaleFlowersAreSeparate", default=False)))
    _ensure(g, "isDicot", bool(_get(g, "IsDicot", default=True)))
    _ensure(g, "numApicalInflors", int(_get(g, "NumApicalInflors", default=0)))
    _ensure(g, "numAxillaryInflors", int(_get(g, "NumAxillaryInflors", default=4)))
    _ensure(g, "phyllotacticRotationAngle", float(_get(g, "phyllotacticRotationAngle", default=137.5)))
    _ensure(g, "startingSeedForRandomNumberGenerator",
            int(_get(g, "startingSeedForRandomNumberGenerator", default=1234)))
    # growth curve: 4-value string -> SCurve
    if not hasattr(g, "growthSCurve") or not isinstance(getattr(g, "growthSCurve"), SCurve):
        raw = _get(g, "growthSCurve", default="0.25 0.1 0.65 0.85")
        g.growthSCurve = _parse_scurve(raw)


def normalize_meristem(params):
    m = params.pMeristem
    _ensure(m, "branchingAndLeafArrangement",
            int(_get(m, "branchingAndLeafArrangement", default=0)))
    _ensure(m, "branchingIndex", float(_get(m, "BranchingIndex", default=30.0)))
    _ensure(m, "branchingDistance", float(_get(m, "BranchingDistance", default=3.0)))
    _ensure(m, "secondaryBranchingIsAllowed",
            bool(_get(m, "secondaryBranchingIsAllowed", default=False)))
    _ensure(m, "branchingIsSympodial", bool(_get(m, "BranchingIsSympodial", default=False)))
    _ensure(m, "branchingAngle", float(_get(m, "branchingAngle", default=30.0)))
    _ensure(m, "determinateProbability", float(_get(m, "DeterminateProbability", default=1.0)))


def normalize_internode(params):
    i = params.pInternode
    _ensure(i, "faceColor", _get(i, "FaceColor", default=(50, 100, 50)))
    _ensure(i, "firstInternodeCurvingIndex", float(_get(i, "firstInternodeCurvingIndex", default=10.0)))
    _ensure(i, "curvingIndex", float(_get(i, "curvingIndex", default=30.0)))
    _ensure(i, "lengthAtOptimalFinalBiomassAndExpansion_mm",
            float(_get(i, "LengthAtOptimalFinalBiomassAndExpansion_mm", default=60.0)))
    _ensure(i, "widthAtOptimalFinalBiomassAndExpansion_mm",
            float(_get(i, "WidthAtOptimalFinalBiomassAndExpansion_mm", default=3.0)))
    _ensure(i, "optimalFinalBiomass_pctMPB", float(_get(i, "OptimalFinalBiomass_pctMPB", default=4.0)))
    _ensure(i, "minDaysToCreateInternode", int(_get(i, "MinDaysToCreateInternode", default=3)))
    _ensure(i, "maxDaysToCreateInternodeIfOverMinFraction",
            int(_get(i, "MaxDaysToCreateInternodeIfOverMinFraction", default=10)))
    _ensure(i, "minFractionOfOptimalInitialBiomassToCreateInternode_frn",
            float(_get(i, "MinFractionOfOptimalInitialBiomassToCreateInternode_frn", default=0.2)))
    _ensure(i, "canRecoverFromStuntingDuringCreation",
            bool(_get(i, "CanRecoverFromStuntingDuringCreation", default=True)))
    _ensure(i, "minDaysToAccumulateBiomass", int(_get(i, "MinDaysToAccumulateBiomass", default=3)))
    _ensure(i, "maxDaysToAccumulateBiomass", int(_get(i, "MaxDaysToAccumulateBiomass", default=10)))
    _ensure(i, "lengthMultiplierDueToBolting",
            float(_get(i, "LengthMultiplierDueToBolting", default=0.0)))
    _ensure(i, "minDaysToBolt", int(_get(i, "MinDaysToBolt", default=10)))
    # biomass accretion multipliers (not in .pla; source defaults to 1)
    _ensure(i, "lengthMultiplierDueToBiomassAccretion", 1.0)
    _ensure(i, "widthMultiplierDueToBiomassAccretion", 1.0)


def normalize_leaf(params):
    lf = params.pLeaf
    _ensure(lf, "faceColor", _get(lf, "FaceColor", default=(50, 250, 50)))
    _ensure(lf, "backfaceColor", _get(lf, "BackfaceColor", default=(50, 150, 50)))
    _ensure(lf, "petioleColor", _get(lf, "PetioleColor", default=(50, 100, 50)))
    _ensure(lf, "petioleAngle", float(_get(lf, "PetioleAngle", default=40.0)))
    _ensure(lf, "petioleLengthAtOptimalBiomass_mm",
            float(_get(lf, "PetioleLengthAtOptimalBiomass_mm", default=30.0)))
    _ensure(lf, "petioleWidthAtOptimalBiomass_mm",
            float(_get(lf, "PetioleWidthAtOptimalBiomass_mm", default=1.0)))
    _ensure(lf, "petioleTaperIndex", int(_get(lf, "petioleTaperIndex", default=100)))
    _ensure(lf, "compoundNumLeaflets", int(_get(lf, "CompoundNumLeaflets", default=1)))
    _ensure(lf, "compoundPinnateOrPalmate", int(_get(lf, "CompoundPinnateOrPalmate", default=0)))
    _ensure(lf, "compoundPinnateLeafletArrangement",
            int(_get(lf, "compoundPinnateLeafletArrangement", default=0)))
    _ensure(lf, "compoundRachisToPetioleRatio",
            float(_get(lf, "CompoundRachisToPetioleRatio", default=30.0)))
    _ensure(lf, "compoundCurveAngleAtStart", float(_get(lf, "compoundCurveAngleAtStart", default=0.0)))
    _ensure(lf, "compoundCurveAngleAtFullSize", float(_get(lf, "compoundCurveAngleAtFullSize", default=4.0)))
    _ensure(lf, "optimalBiomass_pctMPB", float(_get(lf, "optimalBiomass_pctMPB", default=5.0)))
    _ensure(lf, "optimalFractionOfOptimalBiomassAtCreation_frn",
            float(_get(lf, "optimalFractionOfOptimalBiomassAtCreation_frn", default=0.2)))
    _ensure(lf, "minDaysToGrow", int(_get(lf, "minDaysToGrow", default=3)))
    _ensure(lf, "maxDaysToGrow", int(_get(lf, "MaxDaysToGrow", default=10)))
    if not hasattr(lf, "sCurveParams") or not isinstance(getattr(lf, "sCurveParams"), SCurve):
        lf.sCurveParams = _parse_scurve(_get(lf, "sCurveParams", default="0.25 0.1 0.65 0.85"))


def normalize_seedling(params):
    sl = params.pSeedlingLeaf
    _ensure(sl, "nodesOnStemWhenFallsOff", int(_get(sl, "NodesOnStemWhenFallsOff", default=3)))
    _ensure(sl, "scaleAtFullSize", float(_get(sl, "ScaleAtFullSize", default=20.0)))


def normalize_flowers(params):
    for gender in ("kGenderFemale", "kGenderMale"):
        d = params.flowers.setdefault(gender, {})
        defaults = {
            "optimalBiomass_pctMPB": 1.0,
            "minFractionOfOptimalBiomassToCreateInflorescence_frn": 0.5,
            "minFractionOfOptimalBiomassToMakeFlowers_frn": 0.5,
            "minDaysToCreateInflorescence": 3,
            "maxDaysToCreateInflorescenceIfOverMinFraction": 10,
            "minDaysToGrow": 3,
            "maxDaysToGrow": 10,
            "minDaysToOpenFlower": 3,
            "minDaysBeforeSettingFruit": 3,
            "minFractionOfOptimalBiomassToCreateFruit_frn": 0.8,
            "numFlowersOnMainBranch": 1,
            "numFlowersPerBranch": 1,
            "numBranches": 0,
            "daysToAllFlowersCreated": 10,
        }
        for key, val in defaults.items():
            if key not in d:
                d[key] = val


def normalize_params(params):
    """Apply all normalizations so a species is simulation-ready."""
    normalize_general(params)
    normalize_meristem(params)
    normalize_internode(params)
    normalize_leaf(params)
    normalize_seedling(params)
    normalize_flowers(params)
    # leaf tdo params accessors used by drawing
    for container in ("leafTdoParams", "stipuleTdoParams", "seedlingTdoParams", "pAxillaryBud"):
        tdo = getattr(params, container, None)
        if tdo is not None:
            for attr in ("scaleAtFullSize", "xRotationBeforeDraw",
                         "yRotationBeforeDraw", "zRotationBeforeDraw",
                         "faceColor", "backfaceColor", "repetitions", "radiallyArranged"):
                if not hasattr(tdo, attr):
                    setattr(tdo, attr, 0.0 if "Rotation" in attr or "Scale" in attr
                            else (1 if attr == "repetitions" else
                                  (True if attr == "radiallyArranged" else
                                   ((50, 200, 50) if "Color" in attr else 0.0))))
    return params


def _parse_scurve(raw):
    if isinstance(raw, SCurve):
        return raw
    if isinstance(raw, (list, tuple)) and len(raw) >= 4:
        return SCurve(float(raw[0]), float(raw[1]), float(raw[2]), float(raw[3]))
    parts = str(raw).split()
    if len(parts) >= 4:
        try:
            return SCurve(float(parts[0]), float(parts[1]), float(parts[2]), float(parts[3]))
        except ValueError:
            pass
    return SCurve()
