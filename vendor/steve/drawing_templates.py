"""Title-block templates loaded from data files.

A template is JSON: a frame, lines, fixed text, fields, an optional logo and an optional parts table.
Company files live outside this package, under ``templates/company/<name>/`` at the repository root, so a
redistribution can omit that directory. This module never names a company. With that directory absent,
``load_templates()`` returns an empty catalog and drawings keep the built-in block.

Field sources a template may ask for:

- ``job_number``: the leading digits of the drawing title, else of the part name (``33107 Molded Top
  Plate`` → ``33107``). A ``fields`` override replaces it. When neither name starts with a number, the
  title itself is shown (the part name, when the title is empty).
- ``mass``: model mass. Inch sheets show pounds (lb, 2 decimal places unless the template says otherwise);
  millimetre sheets show kilograms (kg, 3 decimal places). 1 lb = 453.59237 g. Bodies with no material or
  no density, suppressed body features, and declared fasteners that have no mass are left out of the
  total. The template's ``hardware_note`` (default ``WT EXCL. HARDWARE``) is printed when fasteners were
  left out; otherwise ``incomplete_note`` (default ``WT INCOMPLETE``) when something else was left out.
  ``fields["weight"]`` replaces the computed text and keeps the note.
- ``material``: the part's material names. On an assembly the template's ``assembly_text`` is used instead.
- ``scale``, ``size``, ``sheet``, ``revision``, ``title``: the sheet fills these in, same as the built-in block.

A logo is optional. ``logo.enabled`` with ``image``, ``x``, ``y``, ``width`` and ``height`` (millimetres
from the block's lower-left) draws that image inside the box, aspect kept, centred. ``frame: false``
draws no rectangle around it. The image file sits next to the template JSON.
"""
from __future__ import annotations

import json
import os
import re
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

from .images import ImageError, check

ID = re.compile(r"[a-z][a-z0-9-]{0,40}")
JOB = re.compile(r"\s*(\d+)")
# International avoirdupois pound. Inch drawings show pounds; millimetre drawings show kilograms.
LB_PER_GRAM = 1 / 453.59237
BODY_KINDS = {"box", "extrude", "revolve", "cylinder", "loft", "sweep"}
_ANCHOR = {"left": "start", "centre": "middle", "center": "middle", "right": "end"}


def company_directory() -> Path | None:
    """``templates/company`` next to this package's repository, when that directory exists."""
    root = Path(__file__).resolve().parents[2] / "templates" / "company"
    return root if root.is_dir() else None


def _files(directory: Path) -> list[Path]:
    if not directory.is_dir():
        return []
    found = list(directory.glob("*.json"))
    for child in sorted(path for path in directory.iterdir() if path.is_dir()):
        found.extend(sorted(child.glob("*.json")))
    return found


def load_templates(extra: Path | None = None, *, roots: list[Path] | None = None) -> dict[str, dict]:
    """``id`` → template. ``roots`` replaces the search (tests). Otherwise the company directory, then
    ``extra`` or ``STEVE_DRAWING_TEMPLATES``. A later file with the same id replaces an earlier one.
    Two remaining files with ``default: true`` is an error. A missing company directory is an empty catalog."""
    if roots is not None:
        directories = [Path(path) for path in roots]
    else:
        directories = []
        company = company_directory()
        if company is not None:
            directories.append(company)
        more = Path(extra) if extra is not None else None
        if more is None and os.environ.get("STEVE_DRAWING_TEMPLATES"):
            more = Path(os.environ["STEVE_DRAWING_TEMPLATES"])
        if more is not None:
            directories.append(more)
    catalog: dict[str, dict] = {}
    for directory in directories:
        for path in _files(directory):
            block = _read(path)
            catalog[block["id"]] = block
    defaults = [item["id"] for item in catalog.values() if item.get("default")]
    if len(defaults) > 1:
        raise ValueError(f"More than one drawing template is marked default: {', '.join(defaults)}.")
    return catalog


def default_template_id(catalog: dict[str, dict]) -> str | None:
    """The one template with ``default: true``, or none."""
    found = [item["id"] for item in catalog.values() if item.get("default")]
    return found[0] if found else None


def new_sheet_template_id(account_default, catalog: dict[str, dict]) -> str | None:
    """Which template a new sheet preselects. ``None`` is the built-in block.

    ``account_default`` omitted (``None``) uses the catalog default. ``""`` forces the built-in block.
    Any other string is that id when the catalog has it, else the built-in block.
    """
    if account_default is None:
        return default_template_id(catalog)
    if account_default == "":
        return None
    return account_default if account_default in catalog else None


def catalog_summary(catalog: dict[str, dict] | None = None) -> dict:
    """What the Drawing tab and the assistant tool list: no geometry, no company branch."""
    catalog = load_templates() if catalog is None else catalog
    templates = []
    for item in catalog.values():
        typed = []
        for field in item.get("fields") or []:
            for slot in field.get("slots") or [field]:
                key = slot.get("field")
                source = slot.get("source") or field.get("source")
                if key and source not in ("scale", "size", "sheet") and key not in typed:
                    typed.append(key)
        templates.append({
            "id": item["id"],
            "label": item.get("label") or item["id"],
            "default": bool(item.get("default")),
            "standard": item.get("standard"),
            "sheet": item.get("sheet"),
            "orientation": item.get("orientation"),
            "projection": item.get("projection"),
            "units": item.get("units"),
            "dual_units": item.get("dual_units"),
            "fields": typed,
            "logo": bool((item.get("logo") or {}).get("enabled")),
        })
    return {"templates": templates, "default": default_template_id(catalog)}


def _read(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ValueError(f"Drawing template {path.name} is not valid JSON: {error}.") from None
    if not isinstance(data, dict) or not isinstance(data.get("id"), str) or not ID.fullmatch(data["id"]):
        raise ValueError(f"Drawing template {path.name} needs an id of lowercase letters, digits and hyphens.")
    for key in ("width", "height"):
        if not isinstance(data.get(key), (int, float)) or isinstance(data.get(key), bool) or data[key] <= 0:
            raise ValueError(f"Drawing template {data.get('id', path.name)} needs a positive {key} in millimetres.")
    logo = data.get("logo") or {"enabled": False}
    if not isinstance(logo, dict) or not isinstance(logo.get("enabled", False), bool):
        raise ValueError(f"Drawing template {data['id']}: logo.enabled is true or false.")
    data = dict(data)
    data["_dir"] = str(path.parent)
    if logo.get("enabled"):
        image = logo.get("image")
        file = path.parent / str(image or "")
        if not image or not file.is_file():
            raise ValueError(f"Drawing template {data['id']}: logo image {image!r} is not next to the template.")
        blob = file.read_bytes()
        try:
            kind, width, height = check(str(image), blob)
        except ImageError as error:
            raise ValueError(f"Drawing template {data['id']}: {error}") from None
        data["_logo"] = {"name": str(image), "data": blob, "kind": kind, "pixels": (width, height)}
    return data


def job_number(title: str, part_name: str = "") -> tuple[str, str]:
    """``(text, "job" | "name")``. A leading number on the title wins, then one on the part name.
    With neither, the title is shown, or the part name when the title is empty."""
    for candidate in (title or "", part_name or ""):
        if candidate.lstrip()[:1].isdigit():
            found = JOB.match(candidate)
            if found:
                return found.group(1), "job"
    return (title or part_name or ""), "name"


def format_mass(grams: float, units: str, spec: dict | None = None) -> str:
    """Mass text in the drawing's units. Inches → pounds; millimetres → kilograms."""
    spec = spec or {}
    if units == "in":
        places = int(spec.get("inch_places", 2))
        value = Decimal(str(grams)) * Decimal(str(LB_PER_GRAM))
        unit = spec.get("inch", "lb")
    else:
        places = int(spec.get("mm_places", 3))
        value = Decimal(str(grams)) / Decimal(1000)
        unit = spec.get("mm", "kg")
    quantum = Decimal(1).scaleb(-places)
    text = f"{value.quantize(quantum, rounding=ROUND_HALF_UP):f}"
    return f"{text} {unit}"


def assess_mass(items: list[dict], units: str, spec: dict | None = None) -> dict:
    """Sum what has a mass. ``items`` are ``{kind: solid|hardware|suppressed, grams: float|None}``.

    Fasteners (``hardware``) with no mass print ``hardware_note``. Anything else left out, and no
    such fastener, prints ``incomplete_note``. The grams that were computed are still shown.
    """
    spec = spec or {}
    grams = 0.0
    any_mass = False
    hardware = False
    incomplete = False
    for item in items:
        kind = item.get("kind")
        if kind == "hardware":
            hardware = True
            continue
        if kind == "suppressed" or item.get("grams") is None:
            incomplete = True
            continue
        grams += float(item["grams"])
        any_mass = True
    note = None
    if hardware:
        note = spec.get("hardware_note", "WT EXCL. HARDWARE")
    elif incomplete:
        note = spec.get("incomplete_note", "WT INCOMPLETE")
    return {"grams": grams if any_mass else None, "text": format_mass(grams, units, spec) if any_mass else "", "note": note}


def fits(size: tuple[float, float], block: dict) -> bool:
    """The block fits the sheet's inner frame. ``size`` is the oriented sheet, millimetres."""
    frame = block.get("frame") or {}
    left = float(frame.get("left", 0))
    right = float(frame.get("right", left))
    top = float(frame.get("top", 0))
    bottom = float(frame.get("bottom", top))
    return (block["width"] <= size[0] - left - right + 1e-6
            and block["height"] <= size[1] - top - bottom + 1e-6)


def inner_frame(size: tuple[float, float], block: dict) -> tuple[float, float, float, float]:
    """``(x0, y0, x1, y1)`` of the template frame on a sheet of ``size`` millimetres."""
    frame = block.get("frame") or {}
    left = float(frame.get("left", 0))
    right = float(frame.get("right", left))
    top = float(frame.get("top", 0))
    bottom = float(frame.get("bottom", top))
    return left, bottom, size[0] - right, size[1] - top


def _anchor(align: str | None) -> str:
    return _ANCHOR.get(align or "left", "start")


def _x_of(x: float, width: float, anchor: str) -> float:
    return {"start": x + 1.0, "middle": x + width / 2, "end": x + width - 1.0}[anchor]


def _fit_size(text: str, size: float, width: float, bold: bool) -> float:
    factor = 0.65 if bold else 0.6
    room = max(width - 2.0, 1.0)
    need = factor * size * max(len(text), 1)
    if need <= room:
        return size
    return max(1.0, room / (factor * max(len(text), 1)))


def draw_frame(sheet, block: dict, size: tuple[float, float]) -> tuple[float, float, float, float]:
    """The template border. ``zones: false`` draws the rectangle and four center marks, and no zone text.
    Returns the inner corner ``(x0, y0, x1, y1)``."""
    x0, y0, x1, y1 = inner_frame(size, block)
    sheet.rect(x0, y0, x1 - x0, y1 - y0, "frame")
    marks = (block.get("frame") or {}).get("center_marks")
    if marks:
        stem = float(marks.get("stem", 6.35))
        head = float(marks.get("head", 3.81))
        half = float(marks.get("half_width", 2.2))
        _center_mark(sheet, (x0 + x1) / 2, y0, 0, -1, stem, head, half)
        _center_mark(sheet, (x0 + x1) / 2, y1, 0, 1, stem, head, half)
        _center_mark(sheet, x0, (y0 + y1) / 2, -1, 0, stem, head, half)
        _center_mark(sheet, x1, (y0 + y1) / 2, 1, 0, stem, head, half)
    return x0, y0, x1, y1


def _center_mark(sheet, x, y, ox, oy, stem, head, half):
    """A center mark at the inner edge ``(x, y)``, outward along ``(ox, oy)``."""
    px, py = -oy, ox  # across the edge
    sheet.line([(x, y), (x + ox * stem, y + oy * stem)], "frame")
    base = (x + ox * head, y + oy * head)
    left = (base[0] + px * half, base[1] + py * half)
    right = (base[0] - px * half, base[1] - py * half)
    sheet.line([left, right], "frame")
    sheet.line([(x, y), left], "frame")
    sheet.line([(x, y), right], "frame")


def draw_block(sheet, block: dict, context: dict, origin: tuple[float, float]) -> None:
    """Lines, text, fields and the optional logo. ``origin`` is the block's lower-left on the sheet."""
    ox, oy = origin
    for x1, y1, x2, y2 in block.get("lines") or []:
        sheet.line([(ox + x1, oy + y1), (ox + x2, oy + y2)], "thin")
    for item in block.get("texts") or []:
        _draw_lines(sheet, ox + item["x"], oy + item["y"], item["width"], item["height"], item.get("lines") or [],
                    item.get("align"), item.get("valign"))
    for field in block.get("fields") or []:
        _draw_field(sheet, block, field, context, ox, oy)
    logo = block.get("logo") or {}
    if logo.get("enabled") and block.get("_logo"):
        _draw_logo(sheet, block["_logo"], ox + logo["x"], oy + logo["y"], logo["width"], logo["height"])
    sheet.regions.append(("title-block", None, (ox, oy, ox + block["width"], oy + block["height"])))


def _draw_lines(sheet, x, y, width, height, lines, align, valign):
    if not lines:
        return
    sized = []
    for line in lines:
        text = line["text"] if isinstance(line, dict) else str(line)
        size = float(line.get("size", 2.5) if isinstance(line, dict) else 2.5)
        bold = bool(line.get("bold", False) if isinstance(line, dict) else False)
        sized.append((text, _fit_size(text, size, width, bold), bold))
    gap = 0.35
    block = sum(0.72 * size for _, size, _ in sized) + gap * (len(sized) - 1)
    if valign == "middle":
        cursor = y + height / 2 + block / 2
    elif valign == "bottom":
        cursor = y + 0.6 + block
    else:
        cursor = y + height - 0.4
    anchor = _anchor(align)
    px = _x_of(x, width, anchor)
    for text, size, bold in sized:
        cursor -= 0.72 * size
        if text:
            sheet.text(px, cursor, text, size, anchor, bold=bold)
        cursor -= gap


def _draw_field(sheet, block, field, context, ox, oy):
    x, y = ox + field["x"], oy + field["y"]
    width, height = field["width"], field["height"]
    label = field.get("label") or ""
    if label:
        size = float(field.get("label_size", 2.5))
        anchor = _anchor(field.get("label_align") or "left")
        valign = field.get("label_valign") or "top"
        by = y + height - 0.5 - 0.72 * size if valign == "top" else y + height / 2 - 0.35 * size if valign == "middle" else y + 0.5
        sheet.text(_x_of(x, width, anchor), by, label, _fit_size(label, size, width, field.get("label_bold", False)),
                   anchor, bold=bool(field.get("label_bold", False)))
    slots = field.get("slots")
    if slots:
        _draw_slots(sheet, field, slots, context, x, y, width, height)
        return
    value = _value(field, context)
    note = context.get("mass", {}).get("note") if field.get("source") == "mass" else None
    if value:
        size = float(field.get("size", 2.5))
        anchor = _anchor(field.get("align"))
        valign = field.get("valign") or "bottom"
        px = _x_of(x, width, anchor)
        if note:
            # The figure sits just after the label; the exclusion note takes the right side of the cell.
            anchor, px = "start", x + (16.0 if field.get("label") else 1.0)
        by = y + 0.55 if valign == "bottom" else y + height / 2 - 0.35 * size if valign == "middle" else y + height - 0.5 - 0.72 * size
        sheet.text(px, by, value, _fit_size(value, size, width * (0.55 if note else 1.0), False), anchor)
    if note:
        sheet.text(_x_of(x, width, "end"), y + 0.45, note, _fit_size(note, 1.25, width * 0.62, False), "end")


def _draw_slots(sheet, field, slots, context, x, y, width, height):
    """Two values share one cell: the first toward the label, the last at the right. No line between them."""
    valign = field.get("valign") or "middle"
    size0 = float(field.get("size", 2.5))
    by = y + height / 2 - 0.35 * size0 if valign == "middle" else y + 0.55
    label = field.get("label") or ""
    if label:
        label_size = float(field.get("label_size", 2.5))
        # Capitals run wider than the average 0.6 em the rest of the sheet assumes.
        label_room = 2.0 + 0.9 * label_size * len(label)
    else:
        label_room = 1.0
    for index, slot in enumerate(slots):
        value = context["fields"].get(slot.get("field") or "", "")
        if not value:
            continue
        size = float(slot.get("size", field.get("size", 2.5)))
        align = slot.get("align") or ("right" if index == len(slots) - 1 and len(slots) > 1 else "left")
        anchor = _anchor(align)
        if align in ("right", "end"):
            px = _x_of(x, width, "end")
        else:
            px = x + label_room
            anchor = "start"
        sheet.text(px, by, value, _fit_size(value, size, width - label_room, False), anchor)


def _value(field: dict, context: dict) -> str:
    override = field.get("override") or field.get("field")
    source = field.get("source")
    fields = context.get("fields") or {}
    if source == "job_number":
        if override and fields.get(override):
            return str(fields[override])
        text, _how = job_number(context.get("title") or "", context.get("part_name") or "")
        return text
    if override and source in ("mass", "material", "revision", "sheet") and fields.get(override):
        return str(fields[override])
    if source == "mass":
        return (context.get("mass") or {}).get("text") or ""
    if source == "material":
        if context.get("assembly"):
            return field.get("assembly_text") or ""
        return context.get("material") or ""
    if source == "scale":
        return context.get("scale") or ""
    if source == "size":
        return context.get("size") or ""
    if source == "sheet":
        return fields.get("sheet") or context.get("sheet") or ""
    if source == "revision":
        return fields.get("revision") or context.get("revision") or ""
    if source == "title":
        return context.get("title") or ""
    key = field.get("field")
    return str(fields[key]) if key and fields.get(key) else ""


def _draw_logo(sheet, image: dict, x, y, width, height):
    """Scale the image into the box, aspect kept, centred. No frame."""
    pw, ph = image["pixels"]
    if pw <= 0 or ph <= 0 or width <= 0 or height <= 0:
        return
    scale = min(width / pw, height / ph)
    iw, ih = pw * scale, ph * scale
    sheet.images.append((x + (width - iw) / 2, y + (height - ih) / 2, iw, ih, image))


def parts_table_height(block: dict, context: dict) -> float:
    spec = block.get("parts_table")
    if not spec:
        return 0.0
    rows = context.get("rows") or []
    return float(spec["title_height"]) + float(spec["header_height"]) + float(spec["row_height"]) * len(rows)


def draw_parts_table(sheet, block: dict, context: dict, x1: float, y1: float) -> float:
    """The template's parts table, hung from the inner top-right ``(x1, y1)``. Returns its height."""
    spec = block.get("parts_table")
    if not spec:
        return 0.0
    columns = spec["columns"]
    width = float(spec["width"])
    rows = context.get("rows") or []
    title_h = float(spec["title_height"])
    header_h = float(spec["header_height"])
    row_h = float(spec["row_height"])
    size = float(spec.get("text", 2.1))
    height = title_h + header_h + row_h * len(rows)
    x, top = x1 - width, y1
    sheet.rect(x, top - height, width, height, "thin")
    sheet.line([(x, top - title_h), (x + width, top - title_h)], "thin")
    sheet.text(x + width / 2, top - title_h / 2 - size * 0.35, spec.get("title") or "B.O.M.", size, "middle")
    cursor = x
    header_bottom = top - title_h - header_h
    sheet.line([(x, header_bottom), (x + width, header_bottom)], "thin")
    for column in columns:
        cw = float(column["width"])
        sheet.text(cursor + cw / 2, header_bottom + header_h / 2 - size * 0.35, column["title"], size, "middle")
        if cursor > x:
            sheet.line([(cursor, header_bottom), (cursor, top - height)], "thin")
        cursor += cw
    units = context.get("units") or "mm"
    spec_mass = block.get("mass") or {}
    yy = header_bottom
    for index, row in enumerate(rows):
        yy -= row_h
        if index:
            sheet.line([(x, yy + row_h), (x + width, yy + row_h)], "thin")
        values = {
            "item": str(index + 1),
            "qty": str(row.get("qty", "")),
            "name": str(row.get("name", "")),
            "material": str(row.get("material", "")),
            "mass": format_mass(row["grams"], units, spec_mass) if row.get("grams") is not None else "",
        }
        cursor = x
        for column in columns:
            cw = float(column["width"])
            text = values.get(column["key"], "")
            if text:
                sheet.text(cursor + 1.0, yy + row_h / 2 - size * 0.35, text, _fit_size(text, size, cw, False), "start")
            cursor += cw
    sheet.regions.append(("parts-list", None, (x, top - height, x1, top)))
    return height


def material_names(owner) -> list[str]:
    """Display names of the materials assigned on a part, in assignment order, each once."""
    from .materials import library
    assigned = owner.__dict__.get("materials") if owner is not None else None
    if not assigned:
        return []
    lib = library()
    names = []
    entries = []
    if assigned.default:
        entries.append(assigned.default)
    entries.extend(assigned.bodies.values())
    for entry in entries:
        material = entry.get("material") if isinstance(entry, dict) else None
        name = (lib.get(material) or {}).get("name")
        if name and name not in names:
            names.append(name)
    return names


def owner_mass_items(owner) -> list[dict]:
    """Solids and suppressed body features of one part, for ``assess_mass``."""
    from .materials import library
    from .model import is_surface
    lib = library()
    assigned = owner.__dict__.get("materials")
    items = []
    for feature in getattr(owner, "features", []):
        if getattr(feature, "status", "") == "suppressed" and getattr(feature, "kind", "") in BODY_KINDS:
            items.append({"kind": "suppressed", "grams": None, "name": feature.name})
    for body_id, body in getattr(owner, "bodies", {}).items():
        if is_surface(body):
            continue
        entry = assigned.of(body_id) if assigned else None
        material = entry.get("material") if entry else None
        density = (lib.get(material) or {}).get("density") if material else None
        grams = float(body.Volume()) * density / 1000 if density else None
        items.append({"kind": "solid", "grams": grams, "name": body_id, "material": (lib.get(material) or {}).get("name") if material else None})
    return items


def table_rows(drawing) -> list[dict]:
    """Parts-table rows: name, qty, material, grams (None when that row has no mass), hardware."""
    design = getattr(drawing, "design", None)
    if design is not None:
        grouped: dict = {}
        for item in design.instances:
            part = item["component"]
            if not getattr(part, "hardware", True):
                continue
            key = getattr(part, "id", None) or id(part)
            bucket = grouped.setdefault(key, {"name": getattr(part, "name", "Part"), "qty": 0, "part": part})
            bucket["qty"] += 1
        rows = []
        for bucket in grouped.values():
            items = owner_mass_items(bucket["part"])
            weighed = [item["grams"] for item in items if item["kind"] == "solid" and item["grams"] is not None]
            rows.append({
                "name": bucket["name"], "qty": bucket["qty"],
                "material": ", ".join(material_names(bucket["part"])),
                "grams": sum(weighed) if weighed else None, "hardware": False,
            })
        fasteners = getattr(design, "fasteners", None) or []
        if fasteners:
            from .fasteners import hardware
            for row in hardware(fasteners):
                rows.append({"name": row["name"], "qty": row["quantity"], "material": "", "grams": None, "hardware": True})
        return rows
    model = getattr(drawing, "model", None)
    name = getattr(drawing, "part_name", None) or getattr(drawing, "title", "")
    if model is None:
        return [{"name": name, "qty": 1, "material": "", "grams": None, "hardware": False}]
    items = owner_mass_items(model)
    weighed = [item["grams"] for item in items if item["kind"] == "solid" and item["grams"] is not None]
    return [{
        "name": name, "qty": 1, "material": ", ".join(material_names(model)),
        "grams": sum(weighed) if weighed else None, "hardware": False,
    }]


def mass_items(drawing, rows: list[dict]) -> list[dict]:
    """Everything ``assess_mass`` should see: part solids, suppressed features, and fastener rows."""
    items = []
    design = getattr(drawing, "design", None)
    owners = []
    if design is not None:
        for item in design.instances:
            part = item["component"]
            if getattr(part, "hardware", True):
                owners.append(part)
    elif getattr(drawing, "model", None) is not None:
        owners.append(drawing.model)
    seen = set()
    for owner in owners:
        if id(owner) in seen:
            continue
        seen.add(id(owner))
        items.extend(owner_mass_items(owner))
    for row in rows:
        if row.get("hardware"):
            items.append({"kind": "hardware", "grams": None})
    if not items:
        items.append({"kind": "solid", "grams": None})
    return items


def drawing_context(drawing, block: dict, scale_text: str, number: int, count: int) -> dict:
    """The values a template's fields and parts table read off one sheet."""
    fields = drawing.fields
    rows = table_rows(drawing) if block.get("parts_table") or block.get("fields") else []
    items = mass_items(drawing, rows)
    mass = assess_mass(items, drawing.units, block.get("mass"))
    material = ", ".join(material_names(drawing.model)) if getattr(drawing, "model", None) is not None and drawing.design is None else ""
    revision = fields.get("revision") or (drawing.revisions[-1]["rev"] if drawing.revisions else "")
    return {
        "fields": fields,
        "title": drawing.title,
        "part_name": getattr(drawing, "part_name", "") or "",
        "assembly": drawing.design is not None,
        "material": material,
        "mass": mass,
        "scale": scale_text,
        "size": drawing.sheet,
        "sheet": fields.get("sheet") or f"{number}/{count}",
        "revision": revision,
        "rows": rows,
        "units": drawing.units,
    }
