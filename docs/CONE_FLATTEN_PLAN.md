# Cone and tapered-sheet flat patterns

Implemented on `feature/cone-flatten` as `sheet_cone`. A tapered ring made of four quarter-frustums is four smooth cones (`angle=90`), each with its own flat. `Model.cone` stays a plain solid.

## What already works

Sheet bodies live on the model as `Sheet` records (`vendor/steve/sheetmetal/geometry.py`). A body starts in `sheet_base`, `sheet_roll`, or `sheet_convert` (`vendor/steve/sheetmetal/__init__.py`). Later features edit that record. `_commit_sheet` rebuilds the solid and calls `flat_face()` before the body is kept, so a solid with a broken flat is not stored.

Panels are planar faces with a folded frame and a flat frame. Bends are cylindrical. The developed length comes from `development()` in `vendor/steve/sheetmetal/rules.py`:

- K-factor is the neutral-layer distance from the inside surface, divided by thickness, and it is clamped to 0..1.
- Allowance is `angle_radians * (inside_radius + k * thickness)`.
- A caller can pass an allowance or a deduction instead of K. Exactly one of the three.
- The neutral line must sit inside the material.
- A `BendTable` supplies measured allowances. Lookup is exact in thickness and radius. It never extrapolates and never falls back to K (`SM_BEND_RULE_MISSING`).

`sheet_roll` is an open cylinder. The rule's inside radius is the cylinder radius. `width` runs along the plane's X from the origin. `angle` is the wrap, limited to ±359.9°, so there is always a seam. The whole blank is one rectangular bend zone (`kind: "roll"`, no panels). Positive wrap curls toward the plane normal, inside face on the plane.

`sheet_bend` refuses a tapered blank: the bend zone has to be one rectangular strip (`vendor/steve/sheetmetal/__init__.py`, the `SM` message about tapered boundaries). A cone cannot be faked by sketching a tapered flange.

`sheet_rip` on a cylindrical face rebuilds a straight tube and rejects anything else, including cones (`vendor/steve/sheetmetal/rips.py`, `SM_RIP_CYLINDER_UNSUPPORTED`). The bundled sheet-metal skill lists lofted transitions and general cone rips as unsupported.

The flat is the union of panel faces and bend-allowance rectangles in the material plane (`Sheet.flat_face`). It must be one connected planar face. Overlap raises `SM_FLAT_OVERLAP` (area) or `SM_MATERIAL_OVERLAP` (solid). `Sheet.bend_line` is the straight centreline of that rectangle (half the allowance). A rigid `move` keeps the sheet and leaves the flat in the material plane.

`Model.cone(id, radius1, radius2, height, ...)` is a solid primitive. It does not create a `Sheet`. Leave it that way.

Sheet-metal tests live in `tests/test_sheet_cone.py`. The pure cases load `cone_math.py` without CadQuery. Geometry and DXF cases skip when CadQuery is not installed.

## Smooth cone or frustum

New behaviour for a right circular frustum, rolled as one smooth sheet (a conical surface, constant normal thickness).

User inputs, millimetres and degrees:

| Input | Meaning |
| --- | --- |
| `radius1`, `radius2` | Radii of the two ends. Either may be larger. `0` is a pointed cone. |
| `height` or `slant` | Exactly one. `height` is the axial distance between the end planes. `slant` is the generator length. The other is derived. Both or neither is an error. |
| `angle` | Material sweep about the axis, in `(0, 360]`. `90` is a quarter segment. `360` is a full ring with one seam. |
| `weld_gap_in` | Seam opening in inches. Default 0. Converted as `gap_mm = weld_gap_in * 25.4` and removed from the developed large-end boundary, for smooth and faceted cones and for partial sweeps. |
| rule thickness `t`, K-factor `k` | One K per sheet, the same rule object as every other sheet (`SheetMetalRule`). |
| `on` | Placement plane, same convention as `sheet_roll`: axis along the plane's X, large-or-start end at the origin, seam on the plane, positive sweep toward the plane's +Y. |

Ends are cut on planes perpendicular to the axis (a ring's usual dimension). `radius_reference` says whether the given radii are inside (default), outside, or neutral. Inside matches `sheet_roll`.

Let `ΔR = radius1 - radius2` after converting to inside radii, `L = sqrt(height² + ΔR²)`, and `α` the angle between the generator and the axis, so `cos α = height / L` and `sin α = |ΔR| / L`.

Normal thickness `t` meets an axial end plane in a radial wall thickness `t / cos α`. Outside radius at that plane is `R_in + t / cos α`. Neutral radius at that same plane is

```
R_n = R_in + k * t / cos α
```

`ΔR` is the same on the inside, outside, and neutral surfaces, so converting reference is closed-form: subtract or add `k * t / cos α` or `t / cos α`. No iteration.

The neutral surface is a cone with generators parallel to the inside generators. Its flat pattern is an annular sector:

```
S1 = R_n_large * L / |ΔR|
S2 = R_n_small * L / |ΔR|
sector_angle = sweep * |ΔR| / L          # degrees; sweep * sin α
large_arc    = radians(sweep) * R_n_large
area         = radians(sweep) / 2 * (R_n_large + R_n_small) * L
```

`S1 - S2 = L`. Sector angle does not depend on `k` or `t`. K moves both sector radii, and therefore both arc lengths, together. `k = 0` develops the inside; `k = 1` develops the outside.

Equal radii (`|ΔR|` below the sheet tolerance in `validation.py`) are a cylinder. `sheet_cone` fails and tells the caller to use `sheet_roll`. `height` below that tolerance fails (a flat washer is `sheet_base`). A pointed end (`radius = 0`, `k = 0`) is a pie sector, inner radius 0. Any other pointed end has a small inner radius `k * t / cos α`.

The solid is a revolved thickness profile (or a frustum difference cut to the sweep), not a prism of a circular arc. `bend_sector` in `geometry.py` extrudes along a straight axis and only makes cylinders. The cone needs its own builder, branched on `kind == "cone"`, from `bend_piece`, `bend_face`, and `build`.

Store the analytic result on the bend record and on `Sheet.report()` so inspection can check it without reading a DXF:

```
kind: "cone"
allowance_method: "neutral_cone"
sweep_deg, slant_mm
neutral_radius_mm: [start, end]
outside_radius_mm: [start, end]
sector_radius_mm: [S_start, S_end]
sector_angle_deg
large_arc_mm        # developed length at the large end
```

`allowance_mm` for this kind is `large_arc_mm` (the length a shop checks). It is not a brake allowance. Do not run it through `development()`, which assumes one cylindrical radius.

A smooth cone has no panels, like a roll. Set `reference` to the placement plane so `developed()` and `move` keep working (`Sheet.transformed`).

## Partial segments and seams

`flat_face` requires one connected face, so one body cannot hold four separate quarters. The ring is four `sheet_cone` bodies, each with `angle=90`, placed with `move` (rotation about the cone axis). Each has its own flat and its own DXF. Four 90° sweeps tile 360° only when thickness, K, radii, and height match and no extra gap is inserted.

The sector's two straight edges are the seam. They are boundary edges of the CUT outline. They are not bend lines. Name the solid faces `id.side` (cone), `id.start` and `id.end` (the axial ends), and `id.seam.0` / `id.seam.1` when `angle < 360`.

`angle=360` is a closed solid (the seam faces coincide) and a sector whose angle is `360 * sin α`, which is under 360° for a real taper. The two radial edges are the weld seam in the flat. `sheet_roll` cannot do this because a 360° cylinder's flat would overlap itself; a cone's flat does not.

No kerf parameter in the first version. A weld gap is a smaller `angle` (a quarter with a 1° gap is `angle=89`). The two seam edges stay CUT edges.

`sheet_cut`, flanges, and forms need planar panels or a rectangular bend crossing. A smooth cone has neither. Those features stay refused on a cone body until a later change. Unfold still works: `build(flat=True)` prisms the sector by the thickness, which is the blank.

## Faceted press-brake taper

`facets=N` (`N >= 2`) is a different process on the same inputs: N flat trapezoidal panels and N−1 straight cylindrical bends, open along one generator the same way a roll is open along its seam. This is the part to build after the smooth cone. It is not a tessellated unroll of the smooth sector.

The given radii are the inside radii at the bend-line corners (the circumscribed circle). The bend lines then lie on the same cone as the smooth feature's inside surface. Facet plan angle `δ = sweep / N`.

Adjacent facets are planes through the apex, so the brake angle is constant along the generator. With `Z = R_large * height / |ΔR|` measured from the large end to the apex, and `R` the large corner radius:

```
cos γ = (Z² cos δ + R² cos²(δ/2)) / (Z² + R² cos²(δ/2))
```

`γ` is the deflection from flat, in the same sense as `sheet_flange`'s angle. As the taper goes away (`Z → ∞`), `γ → δ`, which is the bend angle of a regular prism (90° for a square tube). Each bend then uses `rules.allowance(γ)` so K, allowance, deduction, and bend tables behave exactly as they do for a flange. Bend radius is the rule's inside radius (the brake radius), not the cone radius.

`flange()` only builds a rectangular child (`rectangle(width, length)` in `geometry.py`). Facets need a trapezoid panel whose parallel edges are the end chords and whose legs meet the cylindrical bend. The allowance zone stays a rectangle of width `allowance_mm`, so `bend_line`, `pattern`, and the DXF line writer can stay on the straight-bend path. Bend records use the default `kind` of `bend` (so the layer is `BEND_UP` or `BEND_DOWN`, not `ROLL`). Sign the angle so the inside of the bend faces the axis; with the roll's "inside on the plane" convention that is a positive angle and layer `BEND_UP`.

A smooth cone must not be made by raising `N`. Curved rolled metal and brake-formed facets are different blanks.

## K-factor and thickness

| | Inside | Neutral | Outside |
| --- | --- | --- | --- |
| Where it sits | Given sheet face, or derived | `R_in + k t / cos α` on the end plane | `R_in + t / cos α` on the end plane |
| What uses it | Solid's inner surface, default user input | Arc lengths and sector radii | Reported, and accepted when `radius_reference="outside"` |

K is along the surface normal, then intersected with the end plane. Using `R_in + k t` (the cylinder formula) is wrong once `α` is not small: at 45° to the axis the radial offset is `k t √2`. The manifest convention stays `neutral_distance_from_inside_divided_by_thickness` (`export.py`).

Smooth development uses a numeric K on the rule or a `k_factor=` override on the call. A bend table does not apply to the sector: there is no single bend angle and radius to look up. If the rule has a table and no K, the smooth cone fails with a clear message. Faceted bends do look up the table, per bend, at angle `γ`.

`source=` is unchanged. A K chosen for air-bending is a poor default for a rolled cone; the source string has to say which process it came from. Nothing in this work adds springback.

Volume is the difference of the outer and inner frustums, times `sweep/360`. Neutral area times thickness is close and not the check.

## DXF

One writer: `dxf()` in `vendor/steve/sheetmetal/export.py`, called from `write_artifacts`. Layers today are `CUT`, `BEND_UP`, `BEND_DOWN`, `ROLL`, plus `FORM_*` only on the separate forming DXF. Units are millimetres. The outline is `add_shape` of `flat_face()`. Bend marks are `msp.add_line` on `ROLL` when `kind == "roll"`, otherwise `BEND_UP` / `BEND_DOWN`. `pattern()` is the same source the drawing flat view uses (`vendor/steve/drawing.py`, `_flat_pattern`), so the drawing and the DXF cannot diverge.

Cone output has to go through that function.

- Smooth: the sector outline on `CUT`. Inner and outer edges are true circular arcs (`curve()` already returns `type: "arc"` for `CIRCLE` edges). A mid-slant arc, radius `(S_large + S_small) / 2`, on layer `ROLL`. Extend the layer test from `kind == "roll"` to `kind in ("roll", "cone")`, and teach `dxf()` to emit an arc when the mark is an arc. Do not draw a rectangular bend zone: the whole sector is the roll. `FlatView.tsx` draws bend marks as straight segments with a zone of width `allowance_mm`; a cone mark is an arc and has no zone.
- Faceted: unchanged straight marks. One line per bend on `BEND_UP` or `BEND_DOWN`. Outline is lines (chords) on `CUT`.
- `_bend_note` in `drawing.py` prints `ROLL` only for `kind == "roll"`. A cone must not be labelled as a brake bend (`DOWN 161° R113` would be the sector radius misread as a bend radius). Note text: `CONE` plus the sector angle.

Gates that already wrap this writer, and that a cone must still pass:

- `flat_face()` is one planar face, or the feature does not commit.
- `write_artifacts` writes the ZIP only when every body is `ready` and no feature or design diagnostic is an error (`SM_FEATURE_FAILED`, `SM_DESIGN_FAILED`, `SM_EXPORT_INVALID`).
- The UI `exportFlat` (`cad-web/src/workspaces/sheetmetal/sheet.ts`) refuses a body whose status is not `ready`, then downloads `sheet-metal.zip` from a full build.
- Preview builds write `sheet-metal.json` and skip the ZIP (`full=mode != "preview"` in `vendor/upstream_runtime.py`). The desktop kernel defaults to preview (`src/steve_desktop/cad_kernel.py`). The ZIP still requires a full build.
- Size caps: 256 instances, 16 MiB JSON, 16 MiB per ZIP entry, 64 MiB ZIP.
- `manufacturing_validation.status` stays `not_assessed`.
- A later solid edit still invalidates the sheet (`SM_UNSUPPORTED_SOLID_EDIT`).
- Non-line, non-circle edges in `curve()` become display polylines. A cone outline that comes out as `polyline` is a failure of the exporter, to fix inside `dxf()` / `pattern()`, not a second exporter.

Bend-table CSV columns stay as they are. A cone row is identified by `kind=cone` and `allowance_method=neutral_cone`.

## Design choices

**New feature `sheet_cone`, not an extension of `sheet_roll` or `Model.cone`.** A roll is one radius and a rectangular blank; its solid is `bend_sector`. A cone is two radii and a sector; overloading `sheet_roll` would change every existing call. `Model.cone` is a solid with no flat and should stay a solid. `facets` on `sheet_cone` selects the brake-formed blank so the dialog, the rule, and the placement exist once. Smooth work lands first; `facets` can follow without an API change. Alternative considered: a separate `sheet_taper`. It duplicates placement and DXF wiring for the same inputs.

**Exact sector, not a tessellated unroll.** The flat face is built from two arcs and two lines (one arc and two lines for a pointed tip). Area, arc length, and sector angle are the closed forms above. Tessellation would hit `curve()`'s polyline path and disagree with a hand layout. Faceted mode is exact brake geometry (trapezoids plus `development()`), and it is allowed to approach the smooth arc only as a convergence check.

**Inputs.** Inside radii, axial height, sweep, and the existing rule (thickness and K). Optional `radius_reference` of `inside` (default), `outside`, or `neutral`. Optional `facets`. The rule's bend radius is the brake radius for facets and is unused by the smooth sector. Placement matches `sheet_roll`'s `on` plane. No direction vector in the first version (`on="YZ"` puts the axis on X the same way a roll does). No kerf argument; shorten `angle` instead.

**Validation.** Closed forms for sector radii, angle, arc length, area, and frustum volume, compared at the sheet tolerance (`1e-7` in `validation.py`; tests should use `1e-6` mm and `1e-6`°). DXF entity types and layers checked by reading the file `dxf()` writes. Faceted checks are `γ`, the bend allowance, bend-line count `N-1`, and convergence toward the smooth arc as `N` grows. A cylinder, a zero height, a K outside 0..1, a non-positive thickness, and `angle` outside `(0, 360]` fail. `sheet_rip` on a cone solid keeps failing. `Model.cone` still has no `sheet_metal` entry.

## Planned changes

### Core

- `vendor/steve/sheetmetal/cone_math.py` — pure development (no CadQuery): neutral radii, sector, weld gap, facet angle and developed length. `cone_build.py` turns that into a sheet.
- `vendor/steve/sheetmetal/geometry.py` — cone solid, sector face, `kind == "cone"` branches in `bend_face` / `bend_piece` / `bend_line`. Cache `VERSION` stays 1; new fields are optional and old sheets omit `kind` (the exporter already defaults `kind` to `bend`).
- `vendor/steve/sheetmetal/__init__.py` — `sheet_cone(...)`. Signature:

```
sheet_cone(self, id, radius1, radius2, height=None, slant=None, angle=360,
           thickness=None, radius=None, k_factor=None, on="XY", body=None,
           name=None, suppressed=False, rule=None, source=None,
           radius_reference="inside", weld_gap_in=0, facets=None, seam="arc")
```

  `radius` is accepted only so the rule helper stays uniform; the smooth sector ignores it. `facets=None` is smooth.
- `vendor/steve/sheetmetal/export.py` — arc mark on `ROLL`; cone fields in the JSON report and the bend CSV.
- `vendor/upstream_parse.py` — add `sheet_cone` to `FEATURE_KINDS`.
- `vendor/steve/drawing.py` — `_flat_pattern` draws the ROLL arc; `_bend_note` prints `CONE`.
- `bundled-skills/steve-sheet-metal/SKILL.md` — document the call and drop "general cone rips" from the unsupported list for this case. Lofted transitions (square-to-round and other non-circular ends) stay unsupported.

### UI

- `cad-web/src/workspaces/sheetmetal/specs.ts` — dialog fields: radius 1, radius 2, height, sweep, radius reference, facets, plane, and the shared rules block. Hint that bend radius applies when facets are set.
- `cad-web/src/workspaces/sheetmetal/commands.ts` — command `sheet.cone` in the Create group, next to Roll. Include `sheet_cone` in `hasSheet`.
- `cad-web/src/workspaces/sheetmetal/FlatView.tsx` and `sheet.ts` — arc mark, no zone, for `kind: "cone"`.
- `cad-web/src/workspaces/sheetmetal/SheetPanels.tsx` — show neutral radii, sector radii, and sector angle next to the K-factor.
- An icon in `cad-web/src/icons/cad.tsx`. The flat-pattern toggle and DXF button stay as they are; they already follow the sheet report.

### MCP

No new modeling tool. The agent already builds by `cad_build` with source that calls `model.sheet_*`, then reads geometry from `cad_inspect`.

`cad_api_reference` (`src/steve_desktop/cad_service.py`) only lists methods defined in the body of `Model`, `Sketch`, `Component`, or `Design`. `sheet_*` methods live on `SheetMetalMixin` and are invisible. Add class name `SheetMetal`, reading `SheetMetalMixin` in `vendor/steve/sheetmetal/__init__.py`.

```
cad_api_reference(class_name="SheetMetal", method="sheet_cone")
→ { "class": "SheetMetal",
    "methods": [{ "name": "sheet_cone", "signature": "...", "doc": "..." }] }
```

`cad_inspect` returns `geometry.json`, whose `upstream` object is `Model.summary()`. That already includes `sheet_metal` from `sheet_metal_summary()`. Extending `Sheet.report()` with the `development` fields above makes the known-answer numbers visible with no new tool:

```
upstream.sheet_metal.<body>.development = {
  kind, radius_reference,
  inside_radius_mm, outside_radius_mm, neutral_radius_mm,
  slant_mm, sector_radius_mm, sector_angle_deg, large_arc_mm, area_mm2
}
```

`cad_export` accepts only `STEP`, `STL`, and `3MF`. Add format `DXF` as a fetch of the existing full-build ZIP, not a new writer. Invalid sheets already produce no ZIP; the tool returns the same error the UI shows.

```
cad_export(expected_revision: str, format: "DXF")
→ { "revision": "...", "format": "DXF", "path": ".../sheet-metal.zip",
    "bytes": <int>,
    "bodies": [ { "id", "status", "thickness_mm", "bend_count", "bounds_mm", "area_mm2" } ] }
```

The assistant skill text is the other surface agents actually follow. Update it in the same change as the method.

## Test plan

New module `tests/test_sheet_cone.py` (unittest). Pure math tests do not need the geometry kernel. Geometry and DXF tests need CadQuery, which this environment does not have installed.

Known answer, inside radii, square ends. `radius1=50`, `radius2=30`, `height=40`, `t=1.5`, `k=0.4`.

| Quantity | Full sweep 360° | Quarter sweep 90° |
| --- | --- | --- |
| Slant `L` | 44.721360 mm | same |
| `α` | 26.565051° | same |
| Neutral offset `k t / cos α` | 0.670820 mm | same |
| Neutral radii | 50.670820, 30.670820 | same |
| Outside radii | 51.677051, 31.677051 | same |
| Sector radii `S` | 113.303399, 68.582039 | same |
| Sector angle | 160.996894° | 40.249224° |
| Large-end arc | 318.374154 mm | 79.593539 mm |
| Flat area | 11428.199129 mm² | 2857.049782 mm² |
| Solid volume | 17212.984528 mm³ | 4303.246132 mm³ |

Recompute from the closed forms in the test and compare to the built face (arc radii, arc angle, area) and the solid volume. Rounding above is for reading; the assertion is against the formula at `1e-6`.

Further cases:

- `k=0` and `k=1` move the large arc by the outside-minus-inside gap and leave the sector angle unchanged.
- `radius_reference="outside"` with radii 51.677051 and 31.677051 reproduces the inside development.
- Four `angle=90` bodies: sector angles sum to the full angle, areas sum to the full area, seam edges are lines, no `BEND_*` entities.
- Equal radii fail. The same numbers on `sheet_roll` (`radius=25`, `angle=90`, `t=1.5`, `k=0.44`) still develop `π/2 * (25 + 0.44*1.5) = 40.306634` mm.
- Pointed cone `radius2=0`, `k=0`: inner sector radius 0, one outer arc, two lines.
- DXF from `dxf()`: `CUT` contains `ARC` entities, `ROLL` contains the mid arc, `BEND_UP` and `BEND_DOWN` are absent. Units millimetres.
- Faceted, same frustum, corner radii, `N=4`, sweep 360°, brake radius 1.5: `γ = 83.620630°`, allowance `γ_rad * (1.5 + 0.4*1.5) = 3.064856` mm, three bend lines on `BEND_UP`. `N=8` gives `γ = 40.657711°`. A large `N` (64) lands the outline area within 1% of the smooth area.
- `Model.cone` of the same radii has no sheet report. `sheet_rip` on a conical solid still raises `SM_RIP_CYLINDER_UNSUPPORTED`.
- Existing flange and roll behaviour stays on the current `development()` numbers. There is no sheet suite to regress today; add one roll assertion next to the cone tests so the cylinder formula cannot be "fixed" into the cone formula.

## Out of scope

- Square-to-round and other lofted transitions.
- Holes, flanges, and forms on a smooth cone.
- Recognizing an imported conical solid (the tube rip's approach, later).
- Nesting the four quarters onto one sheet.
- Kerf, weld prep, springback, and shop qualification. `manufacturing_validation` stays `not_assessed`.

## Baseline

Recorded on this branch before any feature code, Python 3.12.3 (the project asks for 3.13+). Dependencies from `requirements.txt` are not installed here, and the desktop package is not installed.

`PYTHONPATH=src python3 -m unittest discover -s tests`: 72 tests, 27 passed, 5 failed, 39 errors, 1 skipped. The five failures are process and worker-pool tests whose workers never became ready. The errors are missing modules (`cadquery`, `fastapi`, `PySide6`, `pydantic`, `httpx`, `PIL`, `keyring`, `psutil`) or a CAD worker exiting because of that. No test covers sheet metal.

## Decisions

These were open in the study and are now fixed in `sheet_cone`:

- The real quarters are smooth rolled cones. `facets` omitted is that cone. `facets=N` is the press-brake taper, built in the same call.
- One K-factor per sheet. A cone with no K-factor is an error. Faceted bend allowances use that same K (`γ × (bend radius + K × thickness)`), not a second K.
- Axial height or slant height, exactly one. `Give an axial height or a slant height.` and `Give an axial height or a slant height, not both.`
- Faceted radii are the corner circumradius. The corner chord is `2 R sin(δ / 2)`.
- `weld_gap_in` defaults to 0. Inches become millimetres by multiplying by 25.4 inside `cone_math.weld_gap_mm`.
- `seam='arc'` (default) removes that length from the developed large-end boundary. `seam='plane'` instead trims each radial end with a plane parallel to the axis, offset by half the gap from that end's radial plane. A smooth cone develops the cut as `ψ(S) = sin α · asin(offset / (S sin α))`; the flat area is the exact integral of that curve. A faceted cone cuts the end panels. A full 360° sweep has only one end plane, so a positive plane gap is rejected. A gap that pinches the sweep is rejected.
