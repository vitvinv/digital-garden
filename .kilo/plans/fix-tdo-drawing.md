# Fix TDO parsing & drawing: proper leaves and flowers

## Problem

User reports the addon cannot produce proper leaves and flowers. Investigation
found **7 concrete bugs**, 3 of which are root causes:

## Root causes (verified with data)

### Bug 1 — `.pla` embedded 3D object blocks are never consumed (THE main bug)

Every `.pla` file stores TDO geometry inline after the reference line:

```
Leaf 3D object [kLeafObject3D] =Leaf, sunflower
  start 3D object
  Name=Leaf, sunflower
  Point=0 0 0
  ...
  end 3D object
```

`parse_pla_file()` only consumes a block when the *value itself* starts with
`start 3D object`. In the real format the value is the object **name** and the
block follows on the next lines. Result: all embedded geometry is silently
skipped, and every TDO reference stays a name string. Names not present in the
57-object library (`Default`, `Default tdo`, `Trial`, `New 3D object`,
`Petal, daylily`, `Copy of Stipule thorn`, ...) raise `AssetError` at draw time
— **14 species can't be created at all**, and many flower rows are missing.
Audit of all 14 .pla files: 65 distinct embedded TDOs, all with geometry.

### Bug 2 — seedling leaf params clobber the leaf TDO

Registry access `pSeedlingLeaf.leafTdoParams.object3D` is routed by
`set_param()` to the root `params.leafTdoParams` container (it only special-cases
`leafTdoParams`/`stipuleTdoParams`/`seedlingTdoParams`/`tdoParams` as
*root-level* attrs). The seedling section always comes after the leaf section in
the file, so **every species' leaf TDO, rotation, scale and color get
overwritten by its seedling values** (usually `Default`/`Default 3D object`).
Maiden grass's `Leaf, grassy 2` becomes the default blob; sunflower/corn/onion/
carrot/clover/wild pink leaves become `Default` → AssetError.

### Bug 3 — flower petal scale case mismatch

Registry uses `pFlower[kGenderFemale].tdoParams[kFirstPetals].ScaleAtFullSize`
(capital S) but draw code reads `scaleAtFullSize`. `_set_tdo_attr` stores the
mixed-case attribute verbatim → every flower's petal scale reads 0 →
`normalize_flowers()` injects 20.0 → gilia's petals draw 5x too big
(intended 4.0), rows meant to be hidden (scale 0) draw anyway.

## Secondary bugs

- **Bug 4** — flower parts drawn with the *bract* alignment
  (`rotateY(-64); rotateX(64)`, draw.py draw_inflorescence) instead of the
  original `drawCircleOfTdos` open pattern (`rotateZ(-64); rotateY(32);
  rotateX(pullBackAngle)`, ufruit.py:546-550). Petals point the wrong way.
- **Bug 5** — no inflorescence structure: no peduncle/pedicels/internodes,
  no head-vs-raceme distinction, no bud stage; all flowers cluster at one point
  on the stalk.
- **Bug 6** — `kActivityFree` NameError in `inflorescence.py` (used at line 44
  & 61, never imported) — crashes any flowering species during biomass-removal
  traversal (violet, snapdragon, ...).
- **Bug 7** — fruit drawn twice per flower (duplicated block + extra guarded
  `turtle.pop()` in draw_inflorescence).

## Fixes

### 1. `core/pla_parser.py` — consume embedded blocks + fix routing

- In `parse_pla_file()`, for `ftype == 5` param lines: after the line, if the
  next line starts with `start 3D object`, consume through `end 3D object`,
  parse with `parse_tdo_text()`, and pass the first `Tdo` to `set_param()`.
  Keep the existing `value.startswith("start 3D object")` branch as a fallback.
- In `set_param()`:
  - Route `pSeedlingLeaf.leafTdoParams.*` → root `params.seedlingTdoParams`
    (parser must NOT use `getattr(params, "leafTdoParams")` for a
    `pSeedlingLeaf` base).
  - Handle `pInflor[kGender].bractTdoParams.*` → store under
    `params.flowers[gender]["bractTdoParams"]` (currently silently dropped).
- In `_set_tdo_attr()`: case-insensitive attribute matching (map
  `ScaleAtFullSize` → `scaleAtFullSize`, `FaceColor` → `faceColor`, etc.) so
  mixed-case registry access strings work.

### 2. `core/normalize.py`

- `normalize_flowers()`: remove the `scaleAtFullSize = 20.0` injection for
  zero-scale rows (faithful: scale 0 = row not drawn). Keep color defaults.
- `normalize_seedling()`: ensure `params.seedlingTdoParams` defaults
  (scaleAtFullSize 20, rotations 0, faceColor default green) instead of
  relying on `pSeedlingLeaf.scaleAtFullSize`; keep `pSeedlingLeaf` fields too.

### 3. `core/draw.py`

- `_draw_leaf_tdo()` seedling branch: read TDO/rotations/color from
  `plant.params.seedlingTdoParams` (fall back to `leafTdoParams`), scale from
  seedlingTdoParams/seedling defaults.
- Rewrite `draw_inflorescence()` as a faithful port of uinflor.py draw():
  - `drawBracts` (bractTdoParams, only when scale > 0, bract alignment
    `rotateY(-64); rotateX(64); rotateX(pullBackAngle)` — this pattern stays
    for bracts only)
  - `drawPeduncle` (stalk segment, peduncleLength_mm)
  - `isHead` → `drawHead` (radial, rotateY(64)/rotateZ(64)/rotateY(32)),
    else `drawApex` (internodes + branches + pedicels + flowers)
  - per-flower: bud stage (`budDrawingOption`: kDrawNoBud/kDrawSingleTdoBud/
    kDrawOpeningFlower) vs open flower (`drawPistilsAndStamens` + rows
    kFirstPetals..kSepals) vs fruit when `hasSetFruit`
  - `drawCircleOfTdos` helper: per-part `rotateX(turn)`; push; `rotateZ(-64)`;
    `rotateY(32)` if open; `rotateX(pullBackAngle)`; draw; pop — matching
    ufruit.py:538-557.
  - Use `_angle_with_sway` for all draw angles (as the original does).
  - Remove the duplicated fruit block and the extra `turtle.pop()`.
- Keep `draw_fruit()` (fruit uses `rotateZ(-64)` non-open alignment).
- Rows with empty/unresolvable TDO → skip row (scale <= 0 already skips);
  keep `AssetError` only for `None` references.
- Rows referencing placeholder/empty objects (`Default tdo`, `Trial`, ...) —
  with Bug 1 fixed these resolve to real embedded geometry, so no special
  casing is needed.

### 4. `core/inflorescence.py`

- Import `kActivityFree` from `.meristem`.

### 5. Tests (`blender_addon/tests/`)

- Update `test_mesh_output.py::test_bushy_plant_mesh` — Piney bushy plant no
  longer raises AssetError (its `Default tdo`/`Petal, pink` refs now resolve to
  embedded geometry); assert it *draws* with verts > 0 instead.
- Add tests:
  - embedded TDO block parsing: sunflower's `leafTdoParams.object3D` is a `Tdo`
    named `Leaf, sunflower` with points (not a string, not `Default`).
  - seedling params land on `params.seedlingTdoParams` and do NOT clobber
    `leafTdoParams` (maiden grass leaf object3D name preserved).
  - flower row scale parses: gilia `kFirstPetals.scaleAtFullSize == 4.0`.
  - regression: previously-failing species grow + draw at day 120 without
    AssetError (sunflower, corn, onion, carrot, clover, wild pink, violet,
    snapdragon, buttercup, Daylily, Piney bushy plant).
  - `kActivityFree` traversal on a flowering species does not crash
    (growTo + `traverseWholePlant(kActivityFree)`).

### 6. Docs

- Update `blender_addon/README.md` if the test count changes (27 → more).

## Verification

1. `python -m pytest blender_addon/tests/ -q` — all pass.
2. Headless render check (Blender 2.83 available at
   `C:\Program Files\Blender Foundation\Blender 2.83`) — grow + build meshes
   for gilia, maiden grass, sunflower, red tulip, corn, cabbage, tomato,
   Daylily, violet: no AssetError, non-degenerate leaves & flowers.
3. Numeric sanity: gilia flower petal scale == 4.0 (not 20.0); maiden grass
   leaf TDO name == `Leaf, grassy 2`; sunflower leaf TDO name ==
   `Leaf, sunflower`.

## Out of scope

- The `Leaf, sunflower` duplicate-name loss in `TdoLibrary` (57 parsed, 56
  unique) — cosmetic; embedded TDOs bypass the library anyway.
- `examples/` reference copy of the addon; only `blender_addon/` is fixed.
