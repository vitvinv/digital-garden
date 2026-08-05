"""Part drawing — ports the PlantStudio part draw() methods to the MeshTurtle.

Each part draws itself into the turtle's mesh buffer:
- internode: stem pipe (tapered, curved segments)
- leaf: petiole pipe + leaf TDO (or compound leaflets)
- meristem/inflorescence/flower: TDO objects (buds, petals)
"""

from . import math3d as umath
from .meristem import (kDirectionLeft, kDirectionRight, kArrangementOpposite,
                       kActivityDraw)
from .traverser import PdTraverser

kDontTaper = 0
kUseAmendment = 1

# plant part export indices (used for material naming)
kExportPartInternode = 1
kExportPartLeaf = 2
kExportPartLeafStipule = 3
kExportPartPetiole = 4
kExportPartMeristem = 5
kExportPartRootTop = 6
kExportPartInflorescence = 7
kExportPartFlower = 8
kExportPartFruit = 9

PART_NAMES = {
    kExportPartInternode: "internode",
    kExportPartLeaf: "leaf",
    kExportPartLeafStipule: "stipule",
    kExportPartPetiole: "petiole",
    kExportPartMeristem: "meristem",
    kExportPartRootTop: "root",
    kExportPartInflorescence: "inflorescence",
    kExportPartFlower: "flower",
    kExportPartFruit: "fruit",
}


def _gp(obj, name, default=0.0):
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def resolve_tdo(plant, tdo):
    """Resolve a TDO reference (Tdo object or name string) via the library."""
    if tdo is None:
        return None
    if isinstance(tdo, str):
        lib = getattr(plant, "tdoLibrary", None)
        if lib is not None:
            return lib.get(tdo)
        return None
    return tdo


class DrawContext:
    """Holds state while drawing a plant."""

    def __init__(self, turtle):
        self.turtle = turtle
        self.materials = {}  # name -> color


def draw_plant(plant, turtle):
    """Draw the whole plant into the turtle's mesh buffer."""
    plant.turtle = turtle
    if plant.firstPhytomer is not None:
        traverser = PdTraverser(plant)
        traverser.traverseWholePlant(kActivityDraw)
    plant.turtle = None


# ── internode drawing ──

def draw_internode(part):
    turtle = part.plant.turtle
    if turtle is None:
        return
    zAngle = part.internodeAngle
    if part.phytomerAttachedTo is not None:
        if part.phytomerAttachedTo.leftBranchPlantPart is part:
            zAngle = zAngle + part.plant.pMeristem.branchingAngle
        elif part.phytomerAttachedTo.rightBranchPlantPart is part:
            zAngle = zAngle + part.plant.pMeristem.branchingAngle
            turtle.rotateX(128)
    length = umath.max(0.0, part.propFullLength() *
                       part.plant.pInternode.lengthAtOptimalFinalBiomassAndExpansion_mm)
    width = umath.max(0.0, part.propFullWidth() *
                      part.plant.pInternode.widthAtOptimalFinalBiomassAndExpansion_mm)
    color = part.internodeColor if part.internodeColor else (60, 120, 60)
    _draw_stem_segment(part, length, width, zAngle, 0, color, kDontTaper,
                       kExportPartInternode)


def _draw_stem_segment(part, length, width, angleZ, angleY, color, taperIndex, dxfIndex):
    turtle = part.plant.turtle
    if turtle is None or length <= 0:
        return
    pGeneral = part.plant.pGeneral
    lineDivisions = max(1, int(getattr(pGeneral, "lineDivisions", 3)))
    realAngleZ = angleZ
    realAngleY = angleY
    if lineDivisions > 1:
        turnPortionZ = realAngleZ / lineDivisions
        turnPortionY = realAngleY / lineDivisions
        drawPortion = length / lineDivisions
    else:
        turnPortionZ = realAngleZ
        turnPortionY = realAngleY
        drawPortion = length
    startWidth = width
    if taperIndex > 0:
        endWidth = startWidth * taperIndex / 100.0
    else:
        endWidth = width

    turtle.setLineColor(color)
    for i in range(lineDivisions):
        isLast = (i >= lineDivisions - 1)
        if not isLast:
            segmentTurnZ = turnPortionZ
            segmentTurnY = turnPortionY
            segmentLength = drawPortion
        else:
            segmentTurnZ = realAngleZ - (turnPortionZ * (lineDivisions - 1))
            segmentTurnY = realAngleY - (turnPortionY * (lineDivisions - 1))
            segmentLength = length - (drawPortion * (lineDivisions - 1))
        if taperIndex > 0 and lineDivisions > 1:
            startPortionWidth = startWidth - (i / (lineDivisions - 1)) * (startWidth - endWidth)
            if not isLast:
                endPortionWidth = startWidth - ((i + 1) / (lineDivisions - 1)) * (startWidth - endWidth)
            else:
                endPortionWidth = endWidth
        else:
            startPortionWidth = width
            endPortionWidth = width
        turtle.rotateY(segmentTurnY)
        turtle.rotateZ(segmentTurnZ)
        # draw pipe for this segment
        start_pos = turtle.position()
        turtle.setLineWidth(startPortionWidth)
        turtle.moveInMillimeters(segmentLength)
        end_pos = turtle.position()
        turtle.drawPipe(start_pos, end_pos,
                        startPortionWidth * turtle.scale_pixelsPerMm * 0.5,
                        endPortionWidth * turtle.scale_pixelsPerMm * 0.5,
                        6, color)


# ── leaf drawing ──

def draw_leaf(leaf, direction):
    turtle = leaf.plant.turtle
    if turtle is None or leaf.hasFallenOff:
        return
    turtle.push()
    if direction == kDirectionRight:
        turtle.rotateX(128)
    pLeaf = leaf.plant.pLeaf
    propFullSize = umath.min(1.0, leaf.liveBiomass_pctMPB /
                             max(0.001, pLeaf.optimalBiomass_pctMPB))
    length = pLeaf.petioleLengthAtOptimalBiomass_mm * propFullSize
    if leaf.isSeedlingLeaf:
        length = length / 2
    width = pLeaf.petioleWidthAtOptimalBiomass_mm * propFullSize
    angle = pLeaf.petioleAngle
    petioleColor = pLeaf.petioleColor if pLeaf.petioleColor else (60, 120, 60)

    if leaf.isSeedlingLeaf:
        _draw_stem_segment(leaf, length, width, angle, 0, petioleColor,
                           pLeaf.petioleTaperIndex, kExportPartPetiole)
        scale = propFullSize * (getattr(leaf.plant.pSeedlingLeaf, "scaleAtFullSize", 20) / 100.0)
        _draw_leaf_tdo(leaf, scale, seedling=True)
    else:
        if getattr(pLeaf, "stipuleTdoParams", None) is not None and \
                getattr(leaf.plant.params.stipuleTdoParams, "scaleAtFullSize", 0) > 0:
            _draw_stipule(leaf)
        if pLeaf.compoundNumLeaflets <= 1:
            _draw_stem_segment(leaf, length, width, angle, 0, petioleColor,
                               pLeaf.petioleTaperIndex, kExportPartPetiole)
            scale = propFullSize * (getattr(pLeaf, "leafTdoParams", None) is not None and
                                    leaf.plant.params.leafTdoParams.scaleAtFullSize or 30) / 100.0
            _draw_leaf_tdo(leaf, scale, seedling=False)
        else:
            _draw_compound_leaf(leaf, length, width, angle, petioleColor)
    turtle.pop()


def _draw_leaf_tdo(leaf, scale, seedling):
    turtle = leaf.plant.turtle
    if turtle is None:
        return
    pLeaf = leaf.plant.pLeaf
    if seedling:
        tdo = getattr(leaf.plant.pSeedlingLeaf, "leafTdoParams", None)
        if tdo is None or tdo.object3D is None:
            return
        faceColor = tdo.faceColor if tdo.faceColor else (50, 200, 50)
        turtle.rotateX(_angle_with_sway(leaf, tdo.xRotationBeforeDraw))
        turtle.rotateY(_angle_with_sway(leaf, tdo.yRotationBeforeDraw))
        turtle.rotateZ(_angle_with_sway(leaf, tdo.zRotationBeforeDraw))
    else:
        tdo = leaf.plant.params.leafTdoParams
        if tdo is None or tdo.object3D is None:
            return
        faceColor = tdo.faceColor if tdo.faceColor else (50, 200, 50)
        turtle.rotateX(_angle_with_sway(leaf, tdo.xRotationBeforeDraw))
        turtle.rotateY(_angle_with_sway(leaf, tdo.yRotationBeforeDraw))
        turtle.rotateZ(_angle_with_sway(leaf, tdo.zRotationBeforeDraw))
    turtle.rotateZ(-64)
    r_tdo = resolve_tdo(leaf.plant, tdo.object3D)
    if r_tdo is not None:
        turtle.drawTriangleSet(r_tdo.points, r_tdo.triangles, scale, faceColor)


def _draw_stipule(leaf):
    turtle = leaf.plant.turtle
    if turtle is None:
        return
    pLeaf = leaf.plant.pLeaf
    tdoParams = leaf.plant.params.stipuleTdoParams
    turtle.push()
    turtle.rotateX(_angle_with_sway(leaf, tdoParams.xRotationBeforeDraw))
    turtle.rotateY(_angle_with_sway(leaf, tdoParams.yRotationBeforeDraw))
    turtle.rotateZ(_angle_with_sway(leaf, tdoParams.zRotationBeforeDraw))
    propFullSize = umath.min(1.0, leaf.liveBiomass_pctMPB /
                             max(0.001, pLeaf.optimalBiomass_pctMPB))
    scale = propFullSize * (tdoParams.scaleAtFullSize / 100.0)
    if tdoParams.object3D is not None:
        color = tdoParams.faceColor if tdoParams.faceColor else (50, 200, 50)
        r_tdo = resolve_tdo(leaf.plant, tdoParams.object3D)
        if r_tdo is not None:
            turtle.drawTriangleSet(r_tdo.points, r_tdo.triangles, scale, color)
    turtle.pop()


def _draw_compound_leaf(leaf, length, width, angle, petioleColor):
    """Simplified compound leaf: petiole + leaflets in a fan."""
    turtle = leaf.plant.turtle
    if turtle is None:
        return
    pLeaf = leaf.plant.pLeaf
    _draw_stem_segment(leaf, length, width, angle, 0, petioleColor,
                       kDontTaper, kExportPartPetiole)
    numLeaflets = pLeaf.compoundNumLeaflets
    if numLeaflets <= 1:
        return
    pLeaf_ = pLeaf
    scale = umath.min(1.0, leaf.liveBiomass_pctMPB /
                      max(0.001, pLeaf_.optimalBiomass_pctMPB)) * \
        (getattr(pLeaf_, "leafTdoParams", None) is not None and
         leaf.plant.params.leafTdoParams.scaleAtFullSize or 30) / 100.0
    leafColor = (getattr(pLeaf_, "leafTdoParams", None) is not None and
                 leaf.plant.params.leafTdoParams.faceColor) or (50, 200, 50)
    # fan leaflets alternately left/right
    for i in range(numLeaflets):
        turtle.push()
        flip = -1 if (i % 2 == 0) else 1
        t = (i + 1) / (numLeaflets + 1)
        turtle.rotateX(flip * 24)
        turtle.rotateZ(-40 * flip)
        turtle.moveInMillimeters(length * t)
        tdo = leaf.plant.params.leafTdoParams.object3D
        if tdo is not None:
            r_tdo = resolve_tdo(leaf.plant, tdo)
            if r_tdo is not None:
                turtle.drawTriangleSet(r_tdo.points, r_tdo.triangles, scale * 0.7, leafColor)
        turtle.pop()


def _angle_with_sway(part, angle):
    """Add random sway to a draw angle (deterministic via plant RNG)."""
    rng = part.plant.randomNumberGenerator
    sway = getattr(part.plant.pGeneral, "randomSway", 0.0)
    if sway == 0:
        return angle
    return angle + (rng.zeroToOne() - 0.5) * 2.0 * sway * 256 / 360


# ── meristem / inflorescence TDO drawing ──

def draw_meristem(meristem):
    plant = meristem.plant
    turtle = plant.turtle
    if turtle is None or meristem.isApical:
        return
    bud = plant.pAxillaryBud
    if bud is None or bud.scaleAtFullSize == 0 or bud.object3D is None:
        return
    daysToFullSize = 5
    scale = (bud.scaleAtFullSize / 100.0) * umath.min(1.0, meristem.age / daysToFullSize)
    if scale <= 0:
        return
    numParts = 5
    color = bud.faceColor if bud.faceColor else (50, 100, 50)
    for i in range(numParts):
        turtle.rotateX(256 / numParts)
        turtle.push()
        turtle.rotateZ(-64)
        turtle.rotateX(bud.xRotationBeforeDraw)
        turtle.rotateY(bud.yRotationBeforeDraw)
        turtle.rotateZ(bud.zRotationBeforeDraw)
        r_tdo = resolve_tdo(plant, bud.object3D)
        if r_tdo is not None:
            turtle.drawTriangleSet(r_tdo.points, r_tdo.triangles, scale, color)
        turtle.pop()


def draw_inflorescence(inflor):
    plant = inflor.plant
    turtle = plant.turtle
    if turtle is None:
        return
    # draw peduncle-like stem + flowers as TDOs
    p = plant.pInflor[inflor.gender]
    faceColor = (200, 200, 60)
    # simple representation: a small stem then flower TDOs radially
    tdo = None
    if "tdoParams" in p:
        tp = p["tdoParams"]
        for k in tp:
            if tp[k].object3D is not None:
                tdo = tp[k].object3D
                faceColor = tp[k].faceColor or (200, 200, 60)
                break
    scale = inflor.fractionOfOptimalSizeWhenCreated
    turtle.setLineWidth(1.5)
    turtle.drawInMillimeters(10 * scale)
    if tdo is not None:
        numFlowers = min(8, max(1, inflor.numFlowers))
        for i in range(numFlowers):
            turtle.push()
            turtle.rotateX(i * 256 / max(1, numFlowers))
            turtle.rotateZ(-64)
            turtle.drawTriangleSet(tdo.points, tdo.triangles, 0.5 * scale, faceColor)
            turtle.pop()


def draw_flower(flower):
    pass
