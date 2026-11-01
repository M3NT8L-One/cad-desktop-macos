# Drawing title-block templates

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a drawing sheet carry a company title block loaded from a data file, starting with the measured ANSI B block in the uploads, without hard-coding that company into the drawing engine, the UI, or the assistant tools.

## Owner decisions (these override the defaults below)

The build follows these answers. Where an earlier section still describes the old default, this section wins.

1. **Logo on.** The file is `templates/company/keystone/logo.jpg` (963×473 RGB JPEG, sha256 `17b15915e6e863f0e157f080a85fa1c86287cb4dbc7633d65f86a53361e0f6b6`). It sits in the company directory with the template JSON, not in the generic package. The generic slot is an image path, a box, and aspect kept.
2. **Spellings corrected** in the template text: SYMMETRICAL, UNAUTHORIZED, RADII.
3. **DRAWING NO** defaults to the job number: the leading digits of the drawing title, else of the part name (`33107 Molded Top Plate Assembly` → `33107`). `fields["number"]` overrides it per drawing. If neither name starts with a number, the name itself is shown.
4. **Weight** is the model mass. Inch sheets show pounds (lb, 2 decimal places). Millimetre sheets show kilograms (kg, 3 decimal places). 1 lb = 453.59237 g. Bodies with no material or density, suppressed body features, and declared fasteners with no mass are left out of the total, and the sheet prints `WT EXCL. HARDWARE` when fasteners were left out, otherwise `WT INCOMPLETE`. `fields["weight"]` replaces the figure and keeps the note.
5. **B** is the suggested size. Any sheet in `SIZES` whose inner frame holds the block is allowed. A sheet that uses this template draws no zone grid.
6. **Material and the top-right parts table are in this build.** A part sheet fills the material cell from the part's materials. An assembly sheet prints `SEE ABOVE INDIVIDUAL PART DETAILS`. The parts table (ITEM, QTY, PART NAME, MATERIAL, MASS) hangs from the inner top-right, and the stacked parts list is not drawn again.
7. **New sheets preselect** the catalog template marked `default`. A `Drawing` call with no `template` keeps the built-in block, so existing drawings do not change. The account setting `drawing.defaultTemplate` is `catalog` unless someone sets `''` (built-in) or an id.

**Architecture:** A shipped JSON catalog describes frames, lines, fixed text, autofill fields, and an optional logo. `Drawing(..., template="id")` resolves one file at render time and draws it in the existing title-block layer, so SVG, DXF, and PDF export stay on the current path. A call with no `template` keeps today's built-in block. New sheets pick the catalog entry flagged `default`, and a per-drawing argument overrides that. The company name and logo exist only in that company's JSON file.

**Tech Stack:** Python drawing runtime (`vendor/steve/drawing.py`, `vendor/steve/drawing_pdf.py`, ezdxf for DXF), the Drawing tab (`cad-web/src/drawing/`), CAD build artifacts (`write_artifacts`), desktop CAD tools (`src/steve_desktop/cad_service.py` `cad_tools`).

## Global Constraints

- Keep the upstream product name and logo off anything company-specific. Keep the company name and logo out of generic code. The company lives only in `templates/company/keystone/` (the JSON and the logo) and in this plan, which records the measurement.
- Tests must not import or touch the vault or keyring/keychain code. No secrets.
- The logo is committed only inside that company directory, so dropping `templates/company/` removes it.
- The drawing engine already draws a title block. This plan adds a catalog in front of that path. It does not replace `title_block=` for a hand-written layout.

---

## How drawings work today

One `Drawing(...)` in a part or design is one sheet (`vendor/steve/drawing.py`). A full build writes `drawing.svg` (sheet 1), `drawings.zip` (every sheet as SVG and DXF, tables as CSV, logo images the DXF references), and `drawings.pdf` (`vendor/steve/drawing_pdf.py`). Paper coordinates are millimetres, origin at the lower-left, y up.

Sheet sizes already exist as landscape `(width, height)` mm in `SIZES`:

| Key | mm |
|---|---|
| A4 | 297 × 210 |
| A3 | 420 × 297 |
| A2 | 594 × 420 |
| A1 | 841 × 594 |
| A0 | 1189 × 841 |
| A | 279.4 × 215.9 |
| B | 431.8 × 279.4 |
| C | 558.8 × 431.8 |
| D | 863.6 × 558.8 |
| E | 1117.6 × 863.6 |

ISO defaults to first-angle projection, millimetres, and an A3 sheet. ANSI defaults to third-angle, inches, and a B sheet (`STANDARDS`). `_frame` draws a zone grid: ISO uses a 20 mm left margin and 10 mm elsewhere; ANSI uses 12.7 mm when the long side is over 450 mm and 10 mm otherwise. The built-in title block is an ISO 7200-style block `TITLE_WIDTH` (180 mm) wide, anchored to the inner bottom-right corner (`_title_block`). A `title_block=` list of rows replaces that block. Rows are bottom-first, at most 12 rows of 12 cells, each cell at least 4 mm wide. Text height is 1.5 mm to 20 mm; label height is 1.0 mm to 20 mm.

Autofill keys already implemented (`TITLE_VALUES`, filled in `_title_block`):

| Key | Value |
|---|---|
| `title` | `Drawing.title` (the `title` argument, else the source's name, else `Untitled`) — `Drawing.__init__` |
| `revision` | `fields["revision"]`, else the last `revisions` row's `rev` |
| `scale` | Fitted or given scale, written `1:2` by `_scale_text` |
| `sheet` | `fields["sheet"]`, else `n/m` such as `1/2` |
| `size` | The sheet key, such as `B` |
| `units` | `mm` or `in` |
| `projection` | The projection symbol, only when a cell's field is `projection` |

Typed fields with built-in labels (`FIELDS`): `number`, `owner`, `drawn_by`, `checked_by`, `approved_by`, `date`, `material`, `finish`, `tolerances`. Any other key is allowed and shown in capitals. Nothing in `Drawing` copies the model's material or mass into the title block. Material names for the cut list come from `vendor/steve/materials.py` (`library()` names) inside `_cut_list`. Mass in grams is reported per body by `Assignments.report` in `vendor/steve/materials.py` and can be overridden on a design by `Design.mass` / `measured_mass` in `vendor/steve/design.py`. Those values never reach the title block today.

A logo is already a cell `{"image": "logo.png"}`. `vendor/steve/images.py` accepts one PNG or JPEG beside `main.py`, lowercase name matching `[a-z][a-z0-9_]{0,63}\.(png|jpe?g)`, at most 512 KB and 4096 px a side. The Drawing tab's Source panel imports it. DXF writes an IMAGE entity; PDF embeds the pixels.

The Drawing tab (`cad-web/src/drawing/`) edits the same `Drawing(...)` call. Sheet format and the title-block form write literals. Account templates (`drawing.templates` in `cad-web/src/settings/store.ts`, saved through `/v1/settings` in `src/steve_desktop/cad_server.py`) copy standard, size, orientation, projection, units, fields, notes, and a `title_block` layout into the call. They are a snapshot. Changing a saved template leaves drawings already written alone. The server stores that setting in the CAD state file. It does not go through the vault.

Desktop assistant tools are `cad_tools` in `src/steve_desktop/cad_service.py`: `cad_read`, `cad_inspect`, `cad_build`, `cad_set_parameters`, `cad_export`, `cad_revisions`, `cad_restore`, `cad_api_reference`, `cad_source_package`, `cad_import_package`, `cad_find_parts`, `cad_import_catalog_part`, and `blender_render`. The same set is exposed on the local MCP bridge (`src/steve_desktop/local_mcp.py`). `cad_build` runs the source, which is what produces drawing artifacts. `cad_export` writes STEP, STL, or 3MF (or a Blender scene export). It does not write the drawing DXF or PDF. The drawing skill the assistant loads is `bundled-skills/steve-drawings/SKILL.md`.

## 1. Field inventory

Source files measured for this plan:

- `KEYSTONE_TEMPLATE Assembly.dxf` (model space, inches, `$INSUNITS` = 1). Border block `ANSI_B_SHEET` inserted at `(0, 0)`. Title block inserted at `(16.38, 0.38)`, which is the inner bottom-right corner. Fusion's block name in the file is an internal id and is not the template id.
- `KEYSTONE_TEMPLATE.pdf`, one page, 1224 × 792 pt = 17.000 × 11.000 in.

The model space also contains a small assembly view (layer `Visible`, about x 13.17–15.25 in, y 6.60–9.40 in) and a parts table. Those are this sample drawing's contents. They are not the title block. Defpoints corner ticks are on the non-plotting layer and are left out.

### Sheet border

Outer sheet: **17.000 × 11.000 in = 431.80 × 279.40 mm**. That is ANSI B landscape, and it matches `SIZES["B"]` `(431.8, 279.4)` within 0.05 mm.

Inner frame, from the border lines:

| Edge | inches from sheet origin | mm |
|---|---|---|
| Left | 0.62 | 15.748 |
| Right | 16.38 | 416.052 |
| Bottom | 0.38 | 9.652 |
| Top | 10.62 | 269.748 |

Insets: left and right 15.748 mm, top and bottom 9.652 mm. Four center marks sit on the midpoints of the inner edges (bottom and top at x = 8.5 in, left and right at y = 5.5 in). Each mark is a 0.25 in (6.35 mm) stem out into the margin, plus an arrowhead 0.15 in (3.81 mm) out from the inner edge and 0.0866 in (2.20 mm) to either side. There is no zone letter or number.

The built-in ANSI frame for a B sheet is a 10 mm margin and a zone grid (`_frame`). The measured border is a different rectangle. A sheet that uses this template draws this frame instead of the zone grid.

### Title block outline

Anchored on the inner bottom-right corner. Size **5.5134 × 1.6617 in = 140.04 × 42.21 mm**. Block lower-left on this B sheet: **(276.01, 9.65) mm**. Coordinates in the tables below are millimetres from the block's own lower-left, y up, so the same file drops onto any sheet that can hold it.

DXF dividers in the tolerance columns are skewed by under 0.15 mm, and the material box sits 0.30 mm above the band line under it. The template straightens those to the band lines. Known-answer tests use the straightened numbers. Raw DXF endpoints stay in the line list comments of the data file only as comments are not valid JSON; the plan is the record of the snap.

Straightened lines, block millimetres `[x1, y1, x2, y2]`:

| Role | Line |
|---|---|
| Outer bottom, top, left, right | `[0, 0, 140.04, 0]`, `[0, 42.207, 140.04, 42.207]`, `[0, 0, 0, 42.207]`, `[140.04, 0, 140.04, 42.207]` |
| Major column at x = 51.582 | `[51.582, 0, 51.582, 42.207]` |
| Top of the tolerance columns / bottom of the title band | `[0, 31.339, 140.04, 31.339]` |
| Top of the signature band | `[0, 13.597, 140.04, 13.597]` |
| Top of the drawn row | `[0, 4.694, 140.04, 4.694]` |
| Checked / approved split (left column only) | `[0, 9.134, 51.582, 9.134]` |
| Tolerance column splits | `[15.776, 13.597, 15.776, 31.339]`, `[34.470, 13.597, 34.470, 31.339]` |
| Size / confidential / rev splits | `[63.812, 4.694, 63.812, 13.597]`, `[129.243, 4.694, 129.243, 13.597]` |
| Scale / weight and weight / sheet | `[73.878, 0, 73.878, 4.694]`, `[111.359, 0, 111.359, 4.694]` |
| Material-note box | `[51.582, 13.597, 87.495, 13.597]`, `[87.495, 13.597, 87.495, 19.977]`, `[51.582, 19.977, 87.495, 19.977]` |

### Fields

Text sizes are the PDF's glyph sizes converted as `pt × 25.4 / 72`. Boxes are the cell the text sits in. "Block mm" is `(x, y, width, height)` from the block lower-left.

Spelling is copied from the source. The words SYMETRICAL, UNAUTHERIZED, and RADI are the owner's current text. See open questions before changing them.

#### Filled by the sheet

| Printed label | Field key | Cell (block mm) | Value size | Where the value comes from |
|---|---|---|---|---|
| DRAWING NO | `title` | (51.582, 31.339, 88.458, 10.868) | 5.68 mm | `Drawing.title`. The PDF placeholder is `<ModelPartName>`. The printed label says DRAWING NO; the Fusion tag is the part name. There is no separate drawing-number cell. |
| SIZE | `size` | (51.582, 4.694, 12.230, 8.903) | 2.84 mm | `drawing.sheet`. The sample value is `B`. Already `TITLE_VALUES["size"]`. |
| REV | `revision` | (129.243, 4.694, 10.797, 8.903) | 2.84 mm | `fields["revision"]`, else the last `revisions` row's `rev`. Already implemented. The sample cell is empty. |
| SCALE | `scale` | (51.582, 0, 22.296, 4.694) | 2.69 mm | `_scale_text` during `render`. The sample placeholder is `<Scale>`. A blank sheet with no `scale=` prints an empty scale, which is current behavior. |
| SHEET | `sheet` | (111.359, 0, 28.681, 4.694) | 2.84 mm | `fields["sheet"]` if set, else `n/m` (`f"{number}/{count}"` in `_title_block`). The sample placeholder is `<Sheet>`. |

Label sizes next to those values: DRAWING NO 3.55 mm; SIZE, REV, SCALE, SHEET 3.19 mm. Labels are fixed text in the template, not the built-in `FIELDS` captions (those say "DRAWING NO." with a period and would be wrong here).

#### Typed on the drawing

These are `fields` keys. The title-block form already writes `fields`. New keys are ordinary custom fields; `FIELDS` does not need a company entry. The form should list whatever keys the active template declares, which `layoutFields` already does for a `title_block` layout and the template picker must do for a catalog id.

| Printed label | Field key | Cell (block mm) | Value size | Notes |
|---|---|---|---|---|
| DESCRIPTION | `description` | (51.582, 19.977, 88.458, 11.362) | 2.84 mm | Placeholder `<ModelDescription>`. No description attribute exists on `Model` or `Design`. The person types it. |
| DRAWN | `drawn_by` | name sits in (0, 0, 51.582, 4.694), left of the date | 2.48 mm | `fields["drawn_by"]`. Sample value `HE&D` is an example, not a default. |
| (same cell, right side) | `drawn_date` | right side of that cell | 2.27 mm | `fields["drawn_date"]`. Sample placeholder `<CreateDate>`. Do not stamp today's date. The drawing skill already says to leave a date out rather than invent one. |
| CHECKED | `checked_by` | (0, 4.694, 51.582, 4.440) | 2.48 mm | `fields["checked_by"]`. Sample empty. |
| (same cell, right side) | `checked_date` | right side of that cell | 2.27 mm | `fields["checked_date"]`. Sample empty. |
| APPROVED | `approved_by` | (0, 9.134, 51.582, 4.463) | 2.48 mm | `fields["approved_by"]`. Sample empty. |
| (same cell, right side) | `approved_date` | right side of that cell | 2.27 mm | `fields["approved_date"]`. Sample empty. |
| WEIGHT | `weight` | (73.878, 0, 37.481, 4.694) | 2.84 mm | `fields["weight"]`. Sample placeholder `<ModelMass>`. Not wired to mass. Open question 4 covers reading `Assignments.report(...)["mass"]` (grams) or `Design.mass`; the first build leaves the cell blank until someone types a value. |

The drawn, checked, and approved cells each have a label on the left and two values with no line between the name and the date. One `title_block` cell holds one field, so the template format needs a field with two slots (see the file format). The single `date` key in `FIELDS` is the old one-date cell. This block has three dates; the template uses the three keys above.

#### Fixed text in the template file

| Region (block mm) | Size | Text, line for line |
|---|---|---|
| (0, 31.339, 51.582, 10.868) | 2.13 mm bold, then 1.77 mm bold, then 1.42 mm | `TOLERANCES` / `UNLESS SPECIFIED OTHERWISE` / `DIMENSIONS ARE IN INCHES [MM]` / `MIRROR SYMETRICAL DIMENSIONS` |
| (0, 13.597, 15.776, 17.742) | 1.42 mm bold, then 1.24 mm | `GENERAL ASSY` / `(BURN, FIT-UP)` / `.X = ± 0.250 [6]` / `.XX = ± 0.125 [3]` / `.XXX = ± 0.063 [1.5]` / `ANGLES = ± 1.5°` / `BREAK SHARP EDGES` / `REMOVE SLAG/DROSS` |
| (15.776, 13.597, 18.694, 17.742) | 1.42 mm bold, then 1.24 mm | `CAST` / `ISO 8062 / BS6615 TO CT9` / `RADI = 0.25 [6]` / `DRAFT = ±1.5°` / `MIRROR SYMETRICAL DIMS` / `BREAK SHARP EDGES` |
| (34.470, 13.597, 17.112, 17.742) | 1.42 mm bold, then 1.24 mm | `MACHINE` / `FINISH = 125 RMS [3.2 Ra]` / `.X = ± .030 [0.8]` / `.XX = ± .010 [0.25]` / `.XXX = ± .005 [0.13]` / `ANGLES = ± 0.5°` / `BREAK SHARP EDGES` / `REMOVE BURRS/CHIPS` |
| (51.582, 13.597, 35.913, 6.380) | 2.13 mm bold, then 1.77 mm | `MATERIAL TYPE(S)` / `SEE ABOVE INDIVIDUAL PART DETAILS` |
| (63.812, 4.694, 65.431, 8.903) | 1.42 mm, first line and the company name bold | `CONFIDENTIAL INFORMATION` / `PROPERTY OF KEYSTONE SUPPLY AND ITS DESIGNEES` / `THIS DOCUMENT AND ACCOMPANIED INFORMATION IS STRICTLY CONFIDENTIAL` / `AND SHALL NOT BE DUPLICATED, DISCLOSED OR SHOWN TO UNAUTHERIZED` / `PERSONS WITHOUT WRITTEN CONSENT` |

`MATERIAL TYPE(S)` is fixed text on this assembly block, not `fields["material"]`. The inch sentence is fixed text, not `TITLE_VALUES["units"]`. A sheet whose units are millimetres would still print that sentence until the company edits the file.

Body text at 1.24 mm is below the current `text_height` floor of 1.5 mm in `_title_layout`. The build lowers that generic floor to 1.0 mm (the label floor already used). Eight lines at 1.24 mm with the existing 1.4× line pitch fit the 17.74 mm column.

#### Parts table on the sample sheet (not the title block)

A table hangs from the inner top-right corner. Insert `(11.266257, 10.62)` in. Size 5.1137 × 0.64 in = 129.89 × 16.26 mm. Columns: ITEM 11.05 mm, QTY 11.24 mm, PART NAME 54.08 mm, MATERIAL 24.42 mm, MASS 29.10 mm. Header band 3.05 mm (`B.O.M.`), column titles 3.05 mm, two data rows of 5.08 mm. The sample rows are placeholders (`----`).

The runtime parts list is a different table: it stacks above the title block and its columns are ITEM, QTY, NAME, DESCRIPTION (`_stack`). It has no MATERIAL or MASS column. Build phase 1 leaves that parts list where it is. Replacing it with this top-right table is an open question, not part of the first build.

## 2. Sheet sizes

The source template is one ANSI B landscape sheet, 17.000 × 11.000 in (431.80 × 279.40 mm), confirmed by the DXF extents, the layout paper size 431.80 × 279.40 mm, the PDF page size, and the SIZE value `B`.

**Use one block at this measured size. Do not scale it.** Text is 1.24–5.68 mm. Scaling the block onto ANSI A (half the width) would shrink the smallest line under 1 mm. Scaling it onto D would make a title band about 20 mm tall. ASME practice keeps the block's physical size and moves the border.

Place the 140.04 × 42.21 mm block on the inner bottom-right corner of whatever sheet is selected. The frame insets above (15.748 mm left and right, 9.652 mm top and bottom) are template data, applied on every size, with the same center-mark shape at each edge midpoint. That is one parameterized frame, not a separate drawing per size.

It fits ANSI A–E in landscape, and ANSI A in portrait. The narrowest inner width is A portrait: 215.9 − 31.50 = 184.4 mm, which is wider than 140.04 mm. ISO A4 landscape also fits geometrically (inner width about 265 mm). The first build supports every size already in `SIZES`, because the fit check is "the block fits the inner frame," not a hard-coded list. The template file records `"sheet": "B"` as the size the new-sheet dialog suggests. The person can pick another size in Sheet format.

A sheet whose inner frame is smaller than the block raises `ValueError` and names the sheet. No silent scaling.

## 3. Where the template lives

**JSON in the runtime tree, one file per company block.** Not DXF and not SVG. The renderer already speaks millimetres, text, and images. A DXF would be a second geometry engine, and the source DXF mixes the block with one assembly. SVG is not the paper model (`Sheet` is).

```
vendor/steve/drawing_templates/<id>.json
```

Generic loader (new `vendor/steve/drawing_templates.py`):

- Read every `*.json` in that directory.
- Then read `STEVE_DRAWING_TEMPLATES` if it is set, one directory of extra JSON files. A file with the same `id` replaces the shipped one. This is how a company adds or replaces a block without editing the package. The variable is a path the desktop may set later. The loader does not import the desktop, the vault, or a keyring.
- Return `{id: dict}`. Zero or two files with `"default": true` among the files that remain after replacement is an error at load time.
- Reject an id that is not `[a-z][a-z0-9-]{0,40}`, a block wider than the sheet, a text line over `TEXT_LIMIT` (200), or more than `TITLE_LINES` (12) lines in one text element.

A company swaps its block by replacing that JSON, or by dropping another file in the extra directory and pointing the default at it. No Python or TypeScript branch on a company name.

Suggested file shape (the build writes the real file from section 1):

```json
{
  "id": "keystone-ansi",
  "default": true,
  "standard": "ANSI",
  "sheet": "B",
  "orientation": "landscape",
  "projection": "third",
  "units": "in",
  "dual_units": "mm",
  "frame": {
    "left": 15.748, "right": 15.748, "top": 9.652, "bottom": 9.652,
    "zones": false,
    "center_marks": {"stem": 6.35, "head": 3.81, "half_width": 2.20}
  },
  "width": 140.04,
  "height": 42.207,
  "lines": [[0, 0, 140.04, 0]],
  "texts": [
    {"x": 0, "y": 31.339, "width": 51.582, "height": 10.868, "align": "centre", "valign": "middle",
     "lines": [
       {"text": "TOLERANCES", "size": 2.13, "bold": true},
       {"text": "UNLESS SPECIFIED OTHERWISE", "size": 1.77, "bold": true},
       {"text": "DIMENSIONS ARE IN INCHES [MM]", "size": 1.42, "bold": false},
       {"text": "MIRROR SYMETRICAL DIMENSIONS", "size": 1.42, "bold": false}
     ]}
  ],
  "fields": [
    {"field": "title", "label": "DRAWING NO", "x": 51.582, "y": 31.339, "width": 88.458, "height": 10.868,
     "label_size": 3.55, "size": 5.68, "align": "left", "valign": "top"}
  ],
  "logo": {"enabled": false, "image": "logo.png", "x": 105.287, "y": 13.885, "width": 34.294, "height": 16.845, "frame": false}
}
```

`texts` and `fields` in the real file are the full inventory in section 1, not the two examples above. Signature cells use `"slots": [{"field": "drawn_by"}, {"field": "drawn_date", "align": "right"}]` instead of a single `field`. The company name appears inside `texts` of this file and nowhere else.

`title_block=` on the call remains the hand-written row layout. It wins over `template` when both are set, so a sheet someone already customized stays customized.

## 4. How a drawing chooses it

Three layers, from general to specific:

1. **Catalog default.** The one JSON with `"default": true`. The new-sheet dialog preselects it when the account setting is absent.
2. **Account default.** Setting `drawing.defaultTemplate` (string). `""` means the built-in block. Any other value is a catalog id. Stored with the other CAD settings in `cad_server.py` (`/v1/settings`), the same store as `drawing.templates`. The UI writes it from Sheet format. Missing key means "use the catalog default."
3. **This drawing.** `Drawing(..., template="id")`. `template=""` forces the built-in block on that sheet. Omitting `template` also means the built-in block, so drawings already in the tree do not change when the catalog appears. `title_block=[...]` still replaces both.

Applying a catalog template writes `template="id"` plus the file's suggested `standard`, `sheet`, `orientation`, `projection`, `units`, and `dual_units` when the person has not set them. It does not paste the lines into the call. Editing the JSON then changes every sheet that names that id, the next time it builds. Account templates (`drawing.templates`) stay snapshots and keep copying literals.

### UI

- Sheet format (`cad-web/src/drawing/forms.tsx`) gains a template choice: Built-in, then each catalog id, then the account templates it already lists. The catalog is fetched from `GET /v1/drawing-templates`, which returns id, default flag, suggested sheet setup, the typed field keys, and whether the logo is enabled. The route reads the loader. It has no company branch.
- The title-block form lists `title` and the template's typed keys (`description`, `drawn_by`, `drawn_date`, `checked_by`, `checked_date`, `approved_by`, `approved_date`, `weight` for this file). Autofill keys (`size`, `revision` is editable today, `scale`, `sheet`) stay as they are: revision remains editable because the form already treats it as a field; scale, size, and sheet stay computed and are not text boxes.
- The sheet preview is the SVG the build already returns. No second preview path.

### Export

`render` resolves the id, draws the frame and the placed block inside `sheet.layer("titleblock")`, and returns the same `Sheet`. `Sheet.svg`, `Sheet.dxf`, and `drawing_pdf.pdf` need no company logic. DXF text is the resolved strings (the title, the typed fields, the fixed lines). Positions are the block anchor plus the JSON coordinates. Logos follow the existing IMAGE path only when the logo setting is on and the image file is present.

### MCP and the assistant

Add one read-only tool on the existing `cad_tools` toolset, name `cad_drawing_templates`. It returns the catalog summary (the same payload as `GET /v1/drawing-templates`). It does not write a drawing and it does not know any company. `cad_build` already runs `Drawing(...)`. `cad_export` stays a model export.

`bundled-skills/steve-drawings/SKILL.md` gains a short generic paragraph: call `cad_drawing_templates`; for a new sheet pass `template=` the id whose `default` is true, unless the person names another id or asks for the built-in block; do not paste the block's lines; do not invent dates, names, or a weight. The paragraph must not contain a company name. The skill's existing `title_block=` instructions stay, for a block that is not in the catalog.

The desktop bridge in `local_mcp.py` publishes whatever `cad_tools` returns, so the new tool shows up there with no extra registration.

## 5. Logo

The logo is optional and **off** in the shipped file (`"logo": {"enabled": false, ...}`). The box, measured from the DXF IMAGE entity, is reserved in the file so turning it on does not require a geometry guess:

- Block millimetres: x 105.287, y 13.885, width 34.294, height 16.845.
- Source pixels: 963 × 473. Pixel size in the DXF is 0.00140205 in. `frame` is false: the sample has no rectangle around the artwork.
- The image reference sits in the right side of the description band (sheet inches about 15.012, 0.927 to 16.362, 1.590). It does not enter the DRAWING NO band.

When `enabled` is false the renderer draws nothing there and does not require a file. When a company sets `enabled` true, the `image` name must pass `vendor/steve/images.py` (`logo.png` does). The Fusion file name on the sample image has spaces and capitals, so it cannot be used as the runtime name. The person adds the file with the existing Import logo action. The build fails with the existing `ImageError` if the setting is on and the file is missing.

**OPEN QUESTION for the owner:** does the standard template include the logo? Some drawings use a different block with no logo. Until that is answered, `enabled` stays false and the image is not in the repository. A second block with no logo is another JSON file, not a code flag.

## 6. Test plan

New module `tests/test_title_block_template.py`. Put `vendor` on `sys.path` the way `tests/test_plane_rename.py` does, then import `steve.drawing` and `steve.drawing_templates` only. Do not import `steve_desktop`, `steve_desktop.vault`, `steve_desktop.settings_store`, or `keyring`. After the imports, assert those module names are absent from `sys.modules`.

A blank sheet is enough for the title block: `Drawing` still needs a CadQuery shape (`_source`). Use a 10 mm box and `views=[]`. That path draws the frame and the title block and does not run hidden-line removal.

### Field placement

Load the company JSON through the public loader (by id, not by a hard-coded company check in the test's helper). Render an ANSI B landscape sheet with `template` set to that id, `title="PLATE"`, `scale=(1, 2)`, and fields for every typed key. Assert:

- The block's outer rectangle is width 140.04 mm and height 42.21 mm, with its right edge at 416.05 mm and its bottom at 9.65 mm, tolerance 0.05 mm.
- Every line in the JSON appears as a `Sheet` line on the TITLEBLOCK layer within 0.05 mm after adding the anchor `(416.05 - 140.04, 9.65)`.
- Fixed strings from section 1 appear verbatim, including the three odd spellings.
- `PLATE` is in the drawing-number cell. `1:2` is in the scale cell. `B` is in the size cell. `1/1` is in the sheet cell.
- Typed values land in the cells in section 1. A signature cell contains both the name and the date and has no extra vertical line between them (no TITLEBLOCK line with x between 15 mm and 45 mm of the block crossing y = 0 to 4.694).

### Autofill

| Setup | Expected |
|---|---|
| Two `Drawing` calls, this template, no `fields["sheet"]` | First sheet text `1/2`, second `2/2` |
| `fields={"sheet": "1 OF 2"}` | That exact string, not `1/2` |
| `revisions=[{"rev": "C", "description": "Hole", "date": "2026-11-01", "by": "AD"}]` and no `fields["revision"]` | `C` in the REV cell |
| `fields={"revision": "D"}` plus a revisions row `A` | `D` |
| `title` omitted on a `cq` box with no model name | `Untitled` |
| No `scale=` and `views=[]` | Scale cell empty |
| No weight field | Weight cell empty, and the mass of the box is not printed |

### Sheet size

Render the same template at A, B, C, D, and E landscape, and A portrait. On each, the block is 140.04 × 42.21 mm and its bottom-right corner is the inner bottom-right corner produced by this template's insets (sheet width − 15.748, bottom 9.652), tolerance 0.05 mm. Center marks exist at the four edge midpoints and nowhere else (four stems). Zone letters `A`–`H` are absent.

A template whose `width` exceeds the inner frame (a fixture JSON, not the company file) raises `ValueError` mentioning the sheet key.

### Export

- **DXF.** `sheet.dxf` to a temp file, read with ezdxf. Units are millimetres (`$INSUNITS` 4, which `Sheet.dxf` already sets). A TEXT entity reads `PLATE` with insert within 1.0 mm of the drawing-number value origin (the renderer anchors by baseline; 1.0 mm covers baseline versus cap-height). A LINE on layer `TITLEBLOCK` matches the outer bottom edge within 0.05 mm. With the logo off, the DXF has no IMAGE entity.
- **PDF.** `drawing_pdf.pdf` with `STEVE_PDF_FONTS` pointed at `pdf-fonts/`. The page MediaBox is the sheet size in points (`mm × 72 / 25.4`): B is 1224 × 792 pt within 1 pt. Extract text and require `PLATE`, `1:2`, `KEYSTONE SUPPLY` (this string comes from the data file under test, not from the assertion helper's logic — read the expected confidential line out of the loaded JSON), and the absence of a weight when none was typed.
- **Logo on.** A fixture template with `logo.enabled` true and a tiny valid PNG named `logo.png` beside the fake source produces one IMAGE in the DXF whose insert and size match the JSON box within 0.5 mm, and one image XObject in the PDF. `logo.enabled` false produces neither.

### No-template regression

`Drawing` of the same box with no `template` and no `title_block` on an ISO A3 sheet:

- Title-block width is `TITLE_WIDTH` (180 mm).
- The texts include `TITLE`, `DRAWING NO.`, and `REV`.
- The frame uses the ISO zone grid (a left margin of 20 mm, and a column label `1`).
- The company string that lives in the data file is not on the sheet.

A call that sets both `template` to the catalog id and `title_block=` to a one-row layout draws that one-row layout. A call that omits `template` draws the built-in block even when the catalog has a default file.

Run: `python -m unittest tests.test_title_block_template -v`

The existing `tests/test_cad_drawings.py` boots the CAD server. Leave it unchanged. Do not extend it for this work, because that path is heavier than the renderer and is the wrong place to prove field coordinates.

## 7. Open questions — answered

The owner answered these during the build. The decisions are at the top of this plan. Nothing in this list is still open.

1. Logo on, file in the company directory, generic image slot.
2. Spellings corrected.
3. DRAWING NO is the job number, overridable, and falls back to the name.
4. Weight is model mass in lb or kg, with an exclusion note, and a typed override.
5. Part material autofills; assemblies keep the fixed sentence.
6. B is the suggested size; any size the block fits is allowed.
7. Templated sheets have no zone grid.
8. The top-right parts table is in this build.
9. New sheets preselect the catalog default. Existing drawings keep the built-in block.

## File structure for the build

| File | Responsibility |
|---|---|
| `vendor/steve/drawing_templates.py` | Load and validate catalog JSON. No company names. |
| `vendor/steve/drawing_templates/keystone-ansi.json` | The measured block. The only file that contains the company name. |
| `vendor/steve/drawing.py` | `template=` argument, frame override, placed block, text-height floor 1.0 mm. |
| `vendor/steve/drawing_pdf.py` | Unchanged unless a test shows a placed image or a small text size fails. |
| `cad-web/src/drawing/code.ts` | Read and write the `template` argument. |
| `cad-web/src/drawing/forms.tsx` | Template choice and typed fields from the catalog. |
| `cad-web/src/settings/store.ts` | `drawing.defaultTemplate`. |
| `src/steve_desktop/cad_server.py` | `GET /v1/drawing-templates`. |
| `src/steve_desktop/cad_service.py` | `cad_drawing_templates` on `cad_tools`. |
| `bundled-skills/steve-drawings/SKILL.md` | Generic paragraph on `template=`. |
| `tests/test_title_block_template.py` | Known-answer tests. No vault, no keyring. |

Account template snapshots and `title_block=` stay as they are.

## Build phase

### Task 1: Catalog loader

**Files:**
- Create: `vendor/steve/drawing_templates.py`
- Create: `tests/test_title_block_template.py`

**Interfaces:**
- Consumes: nothing
- Produces: `load_templates(extra: Path | None = None, *, roots: list[Path] | None = None) -> dict[str, dict]`, `default_template_id(catalog: dict[str, dict]) -> str | None`. `roots` replaces the shipped directory and is how tests pass a fixture. The normal call reads the shipped directory (empty is valid) and then `extra` or `STEVE_DRAWING_TEMPLATES`.

- [ ] **Step 1: Write the failing test**

```python
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "vendor"))
from steve.drawing_templates import load_templates, default_template_id

class CatalogTests(unittest.TestCase):
    def test_imports_leave_the_vault_alone(self):
        self.assertNotIn("steve_desktop.vault", sys.modules)
        self.assertNotIn("keyring", sys.modules)

    def test_extra_directory_replaces_an_id_and_one_default_wins(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            (path / "alpha.json").write_text(json.dumps({
                "id": "alpha", "default": True, "width": 100, "height": 40,
                "logo": {"enabled": False, "image": "logo.png"},
            }), encoding="utf-8")
            catalog = load_templates(roots=[path])
            self.assertEqual(default_template_id(catalog), "alpha")
            self.assertEqual(catalog["alpha"]["width"], 100)
            self.assertFalse(catalog["alpha"]["logo"]["enabled"])
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `python -m unittest tests.test_title_block_template.CatalogTests -v`

Expected: FAIL because `steve.drawing_templates` does not exist yet.

- [ ] **Step 3: Implement the loader**

`load_templates` reads `Path(__file__).parent / "drawing_templates" / "*.json"` unless `roots` is passed, then the directory in `STEVE_DRAWING_TEMPLATES` when `extra` is omitted and the variable is set. A missing shipped directory yields an empty catalog. Validate `id`, a single `default: true` across the merged catalog, positive `width` and `height`, and `logo.enabled` as a bool. `default_template_id` returns that id or `None`.

- [ ] **Step 4: Re-run the test**

Expected: PASS.

- [ ] **Step 5: Commit** `Add the drawing template catalog loader`

### Task 2: Company data file

**Files:**
- Create: `vendor/steve/drawing_templates/keystone-ansi.json`
- Modify: `tests/test_title_block_template.py`

**Interfaces:**
- Consumes: `load_templates`
- Produces: one catalog entry whose `texts`, `fields`, `lines`, `frame`, and `logo` match section 1

- [ ] **Step 1: Extend the test** with one assertion per fixed string in section 1, the line table, the field boxes, `logo.enabled is False`, and `logo.image == "logo.png"`. Read expected strings from the loaded dict and compare them to literals copied from section 1, so a dropped line fails.

- [ ] **Step 2: Run it and confirm it fails** on the missing strings.

- [ ] **Step 3: Write the JSON** from section 1. Company wording lives only in this file. `default` is true. Suggested sheet setup is ANSI, B, landscape, third angle, inches, dual millimetres.

- [ ] **Step 4: Re-run** `python -m unittest tests.test_title_block_template -v` and expect PASS.

- [ ] **Step 5: Commit** `Add the measured ANSI B title-block template`

### Task 3: Resolve `template` and draw the block

**Files:**
- Modify: `vendor/steve/drawing.py` (`Drawing.__init__`, `_title_layout` text floor, `render`, new placed-block drawer)
- Modify: `tests/test_title_block_template.py`

**Interfaces:**
- Consumes: `load_templates`
- Produces: `Drawing(..., template=None)`. `None` and `""` keep the built-in block. A string loads that id. `title_block=` wins when it is not `None`.

- [ ] **Step 1: Write the failing placement, autofill, sheet-size, and no-template tests** from section 6. Use a CadQuery 10 mm box and `views=[]`.

- [ ] **Step 2: Run them and confirm they fail** because `Drawing` does not accept `template`.

- [ ] **Step 3: Implement**

- Lower the `text_height` floor from 1.5 mm to 1.0 mm. Leave the 20 mm cap.
- On `template="id"`, set `self.template` to the loaded dict and `self.table_width` to `width`. Unknown id raises `ValueError` listing the ids.
- In `render`, when a template is active, draw its frame (insets and center marks, no zone labels) instead of `_frame`, and draw lines, texts, fields, and slots from the block anchor `(x1 - width, bottom inset)`.
- Field lookup uses the existing `TITLE_VALUES` map plus `drawing.fields`. Unknown autofill prints an empty string.
- Two slots in one cell draw both values and do not add a line between them.
- Logo with `enabled` false draws nothing.

- [ ] **Step 4: Re-run the unit module.** Expected: PASS, including the no-template assertions (`TITLE`, `DRAWING NO.`, width 180, company string absent).

- [ ] **Step 5: Commit** `Draw catalog title blocks on a sheet`

### Task 4: DXF and PDF known answers

**Files:**
- Modify: `tests/test_title_block_template.py`
- Modify: `vendor/steve/drawing.py` or `drawing_pdf.py` only if a test shows a placed line or a 1.24 mm string missing

**Interfaces:**
- Consumes: `Sheet.dxf`, `drawing_pdf.pdf`
- Produces: no new export API

- [ ] **Step 1: Write the DXF and PDF tests** from section 6, including logo off (no IMAGE) and a fixture template with logo on (tiny PNG, `logo.png`, enabled true).

- [ ] **Step 2: Run them.** Fix only a real mismatch in placement or embedding. Do not special-case the company file in the exporter.

- [ ] **Step 3: Commit** `Check title-block DXF and PDF geometry`

### Task 5: UI, account default, and the read-only tool

**Files:**
- Modify: `cad-web/src/drawing/code.ts`, `forms.tsx`, `settings/store.ts`
- Modify: `src/steve_desktop/cad_server.py`, `src/steve_desktop/cad_service.py`
- Modify: `bundled-skills/steve-drawings/SKILL.md`
- Modify: `tests/test_title_block_template.py` with a tool-schema test that imports `cad_drawing_templates` via a direct function if that can be done without `steve_desktop.vault`. If the desktop import pulls the vault in, keep this assertion in a comment-free unit test of the JSON the route would return by calling `load_templates` only, and test the route by reading `cad_server.py` source for the path string. Do not boot `LocalCadServer` if that imports the vault.

**Interfaces:**
- Consumes: `load_templates`, `default_template_id`
- Produces: `GET /v1/drawing-templates` → `{templates: [{id, default, standard, sheet, orientation, projection, units, dual_units, fields, logo}], default}`. `cad_drawing_templates()` returns that same dict. `drawing.defaultTemplate` in the settings types.

- [ ] **Step 1: Write a failing test** that the catalog summary lists field keys `description`, `drawn_by`, `drawn_date`, `checked_by`, `checked_date`, `approved_by`, `approved_date`, `weight` and does not list `scale` (computed) as a typed field.

- [ ] **Step 2: Implement the route, the tool, the `template` argument reader/writer, the Sheet format choice, and the skill paragraph.** The skill paragraph uses the words "catalog" and "template id" and does not name the company.

- [ ] **Step 3: Re-run** `python -m unittest tests.test_title_block_template -v`. Expected: PASS.

- [ ] **Step 4: Commit** `Choose a drawing template from the catalog`

### Task 6: Regression check

- [ ] Run `python -m unittest tests.test_title_block_template tests.test_plane_rename -v`. The plane test is a sanity check that vendor imports still load. Skip any test module that imports the vault.
- [ ] Confirm `git grep -n Keystone -- vendor/steve '*.py' 'cad-web/src' 'src/steve_desktop' 'bundled-skills'` prints nothing. The only hits are `vendor/steve/drawing_templates/keystone-ansi.json` and this plan.
- [ ] Confirm the logo image is not in the tree.

## Spec coverage

| Requirement | Where |
|---|---|
| Field inventory with positions, sizes, autofill versus typed | Section 1 |
| Measured sheet size, which sizes, scale versus per size | Section 2 |
| Generic data file, company can swap | Section 3 |
| Default plus per-drawing override, UI, export, MCP | Section 4 |
| Optional logo, open question, image not committed | Section 5 |
| Known-answer tests and no-template regression | Section 6 |
| Open questions and the build steps | Section 7 and the task list |
| Company name only in its data file | Global constraints, Task 2, Task 6 grep |
| Tests stay off the vault and the keyring | Section 6, Task 1 |
