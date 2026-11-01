"""Catalog title blocks. Imports the drawing runtime only: not the desktop host, the vault, or a keyring."""
import hashlib
import json
import os
import re
import sys
import tempfile
import unittest
import zlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "vendor"))
os.environ.setdefault("STEVE_PDF_FONTS", str(ROOT / "pdf-fonts"))

from steve.drawing import SIZES, STANDARDS, TITLE_WIDTH, Sheet, _frame, _title_block
from steve.drawing_templates import (
    assess_mass, catalog_summary, default_template_id, draw_block, draw_frame, draw_parts_table,
    fits, format_mass, job_number, load_templates, local_date, new_sheet_template_id, parts_table_height,
    set_clock,
)
from steve.images import check

COMPANY = ROOT / "templates" / "company" / "keystone"
LOGO_SHA = "17b15915e6e863f0e157f080a85fa1c86287cb4dbc7633d65f86a53361e0f6b6"
# ANSI B inner bottom-right minus the measured block, from the template frame.
ORIGIN = (416.052 - 140.04, 9.652)


def _texts(sheet):
    return [item[2] for item in sheet.texts]


def _context(**overrides):
    context = {
        "fields": {
            "description": "Molded top plate",
            "drawn_by": "AR", "drawn_date": "2026-11-01",
            "checked_by": "BK", "checked_date": "2026-11-01",
            "approved_by": "CL", "approved_date": "2026-11-01",
        },
        "title": "33107 Molded Top Plate Assembly",
        "part_name": "33107 Molded Top Plate",
        "assembly": True,
        "material": "",
        "mass": {"text": "0.44 lb", "note": None, "grams": 198.72},
        "scale": "1:2",
        "size": "B",
        "sheet": "1/1",
        "revision": "A",
        "rows": [
            {"name": "Molded Top Plate", "qty": 1, "material": "Aluminum 6061-T6", "grams": 155.52, "hardware": False},
            {"name": "Rib", "qty": 1, "material": "Aluminum 6061-T6", "grams": 43.2, "hardware": False},
        ],
        "units": "in",
    }
    context.update(overrides)
    return context


def _paint(block, context=None, size=SIZES["B"]):
    context = _context() if context is None else context
    sheet = Sheet(size, STANDARDS["ANSI"])
    x0, y0, x1, y1 = draw_frame(sheet, block, size)
    with sheet.layer("titleblock"):
        draw_block(sheet, block, context, (x1 - block["width"], y0))
        if block.get("parts_table"):
            draw_parts_table(sheet, block, context, x1, y1)
    return sheet


class ImportFenceTests(unittest.TestCase):
    def test_imports_leave_the_vault_alone(self):
        # A combined run may already have loaded the vault for other tests. These modules must not name it.
        import steve.drawing as drawing
        import steve.drawing_pdf as drawing_pdf
        import steve.drawing_templates as templates
        for module in (drawing, drawing_pdf, templates):
            text = Path(module.__file__).read_text(encoding="utf-8")
            for banned in ("steve_desktop", "keyring", "keychain"):
                self.assertNotIn(banned, text, module.__name__)

    def test_generic_code_does_not_name_the_company(self):
        roots = [ROOT / "vendor" / "steve", ROOT / "cad-web" / "src", ROOT / "src" / "steve_desktop", ROOT / "bundled-skills"]
        hits = []
        for root in roots:
            for path in root.rglob("*"):
                if path.suffix.lower() not in {".py", ".ts", ".tsx", ".md", ".json"}:
                    continue
                if "node_modules" in path.parts:
                    continue
                text = path.read_text(encoding="utf-8", errors="ignore")
                if "eystone" in text:
                    hits.append(str(path.relative_to(ROOT)))
        self.assertEqual(hits, [])


class CatalogTests(unittest.TestCase):
    def test_company_directory_is_outside_the_package(self):
        self.assertFalse(str(COMPANY).startswith(str(ROOT / "vendor")))
        self.assertTrue((COMPANY / "keystone-ansi.json").is_file())
        self.assertTrue((COMPANY / "logo.jpg").is_file())

    def test_loader_works_with_the_company_directory_absent(self):
        with tempfile.TemporaryDirectory() as folder:
            catalog = load_templates(roots=[Path(folder)])
        self.assertEqual(catalog, {})
        self.assertIsNone(default_template_id(catalog))
        self.assertIsNone(new_sheet_template_id(None, catalog))

    def test_shipped_company_template(self):
        catalog = load_templates()
        chosen = default_template_id(catalog)
        self.assertEqual(chosen, "keystone-ansi")
        block = catalog[chosen]
        self.assertEqual(block["sheet"], "B")
        self.assertEqual(block["width"], 140.04)
        self.assertEqual(block["height"], 42.207)
        self.assertFalse(block["frame"]["zones"])
        self.assertTrue(block["logo"]["enabled"])
        blob = (COMPANY / "logo.jpg").read_bytes()
        self.assertEqual(hashlib.sha256(blob).hexdigest(), LOGO_SHA)
        kind, width, height = check("logo.jpg", blob)
        self.assertEqual((kind, width, height), ("jpeg", 963, 473))
        joined = (COMPANY / "keystone-ansi.json").read_text(encoding="utf-8")
        self.assertIn("SYMMETRICAL", joined)
        self.assertIn("UNAUTHORIZED", joined)
        self.assertIn("RADII", joined)
        self.assertNotIn("SYMETRICAL", joined)
        self.assertNotIn("UNAUTHERIZED", joined)
        self.assertNotIn("RADI =", joined)
        self.assertEqual(new_sheet_template_id(None, catalog), "keystone-ansi")
        self.assertIsNone(new_sheet_template_id("", catalog))

    def test_extra_file_replaces_an_id(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            (path / "alpha.json").write_text(json.dumps({
                "id": "alpha", "default": True, "width": 100, "height": 40,
                "logo": {"enabled": False},
            }), encoding="utf-8")
            catalog = load_templates(roots=[path])
            self.assertEqual(catalog["alpha"]["width"], 100)
            self.assertFalse(catalog["alpha"]["logo"]["enabled"])
            summary = catalog_summary(catalog)
            self.assertEqual(summary["default"], "alpha")


def _pdf_objects(data: bytes) -> dict[int, bytes]:
    """PDF objects this drawing writer emits. Streams are inflated with zlib, which the runtime already uses."""
    objects = {}
    for match in re.finditer(rb"(\d+) 0 obj\n", data):
        number = int(match.group(1))
        start = match.end()
        end = data.find(b"\nendobj", start)
        body = data[start:end]
        stream = body.find(b"stream\n")
        if stream >= 0:
            payload = body[stream + len(b"stream\n"):body.rfind(b"\nendstream")]
            if b"FlateDecode" in body[:stream]:
                payload = zlib.decompress(payload)
            body = body[:stream] + payload
        objects[number] = body
    return objects


def _pdf_info(data: bytes) -> tuple[float, float, str, int]:
    """Page size in points, extracted text, and how many images the page embeds. Standard library only."""
    objects = _pdf_objects(data)
    size = None
    fonts: dict[str, dict[int, str]] = {}
    content = b""
    images = data.count(b"/Subtype /Image")
    for body in objects.values():
        box = re.search(rb"/MediaBox\s*\[\s*[\d.]+\s+[\d.]+\s+([\d.]+)\s+([\d.]+)\s*\]", body)
        if box:
            size = (float(box.group(1)), float(box.group(2)))
        font_dict = re.search(rb"/Font\s*<<(.+?)>>", body, re.S)
        if font_dict and b"/Contents" in body:
            named = {}
            for name, ref in re.findall(rb"/(F\d+)\s+(\d+)\s+0\s+R", font_dict.group(1)):
                named[name.decode()] = int(ref)
            contents = re.search(rb"/Contents\s+(\d+)\s+0\s+R", body)
            if contents:
                content = objects[int(contents.group(1))]
            for name, ref in named.items():
                link = re.search(rb"/ToUnicode\s+(\d+)\s+0\s+R", objects[ref])
                cmap = {}
                if link:
                    for gid, uni in re.findall(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", objects[int(link.group(1))]):
                        cmap[int(gid, 16)] = bytes.fromhex(uni.decode()).decode("utf-16-be")
                fonts[name] = cmap
    pieces = []
    current = {}
    for token in re.finditer(rb"/(F\d+)\s+[^\s]+ Tf|<([0-9A-Fa-f]+)>\s*Tj", content):
        if token.group(1):
            current = fonts.get(token.group(1).decode(), {})
            continue
        raw = bytes.fromhex(token.group(2).decode())
        for index in range(0, len(raw), 2):
            pieces.append(current.get(int.from_bytes(raw[index:index + 2], "big"), ""))
    if size is None:
        raise AssertionError("The PDF has no MediaBox.")
    return size[0], size[1], "".join(pieces), images


class DateTests(unittest.TestCase):
    def tearDown(self):
        set_clock(None, None)

    def test_auto_date_is_the_local_day_when_utc_is_already_tomorrow(self):
        # 04:33 UTC on 1 November is 22:33 the previous evening at a fixed UTC−6 offset.
        zone = timezone(timedelta(hours=-6))
        instant = datetime(2026, 11, 1, 4, 33, tzinfo=timezone.utc)
        set_clock(lambda: instant, zone)
        self.assertEqual(local_date(), datetime(2026, 10, 31).date())
        block = load_templates()["keystone-ansi"]
        context = _context(fields={"drawn_by": "AR", "checked_by": "BK", "approved_by": "CL", "description": "Plate"})
        texts = _texts(_paint(block, context))
        self.assertEqual(texts.count("2026-10-31"), 3)
        self.assertNotIn("2026-11-01", texts)
        context["fields"]["drawn_date"] = "1999-01-02"
        texts = _texts(_paint(block, context))
        self.assertIn("1999-01-02", texts)
        self.assertEqual(texts.count("2026-10-31"), 2)


class JobAndMassTests(unittest.TestCase):
    def test_job_number_parsing_and_fallback(self):
        self.assertEqual(job_number("33107 Molded Top Plate Assembly"), ("33107", "job"))
        self.assertEqual(job_number("  42 Bracket"), ("42", "job"))
        self.assertEqual(job_number("Molded Top Plate", "33107 Molded Top Plate"), ("33107", "job"))
        self.assertEqual(job_number("Molded Top Plate"), ("Molded Top Plate", "name"))
        self.assertEqual(job_number("", "Side Plate"), ("Side Plate", "name"))

    def test_mass_units_and_exclusion_notes(self):
        # 198.72 g is 0.43810 lb → 0.44 lb, and 0.19872 kg → 0.199 kg.
        self.assertEqual(format_mass(198.72, "in"), "0.44 lb")
        self.assertEqual(format_mass(198.72, "mm"), "0.199 kg")
        hardware = assess_mass(
            [{"kind": "solid", "grams": 100.0}, {"kind": "hardware", "grams": None}], "in")
        self.assertEqual(hardware["text"], "0.22 lb")
        self.assertEqual(hardware["note"], "WT EXCL. HARDWARE")
        missing = assess_mass([{"kind": "solid", "grams": 50.0}, {"kind": "solid", "grams": None}], "mm")
        self.assertEqual(missing["note"], "WT INCOMPLETE")
        self.assertEqual(missing["text"], "0.050 kg")
        suppressed = assess_mass([{"kind": "suppressed", "grams": None}, {"kind": "solid", "grams": 10.0}], "in")
        self.assertEqual(suppressed["note"], "WT INCOMPLETE")
        both = assess_mass(
            [{"kind": "hardware", "grams": None}, {"kind": "solid", "grams": None}, {"kind": "solid", "grams": 10.0}], "in")
        self.assertEqual(both["note"], "WT EXCL. HARDWARE")
        clear = assess_mass([{"kind": "solid", "grams": 198.72}], "in")
        self.assertIsNone(clear["note"])
        self.assertEqual(clear["text"], "0.44 lb")


class PlacementTests(unittest.TestCase):
    def setUp(self):
        self.block = load_templates()["keystone-ansi"]

    def test_frame_has_no_zone_grid_and_b_fits_every_ansi_size(self):
        sheet = Sheet(SIZES["B"], STANDARDS["ANSI"])
        before = len(sheet.texts)
        x0, y0, x1, y1 = draw_frame(sheet, self.block, SIZES["B"])
        self.assertEqual(sheet.texts[before:], [])
        self.assertEqual((round(x0, 3), round(y0, 3), round(x1, 3), round(y1, 3)), (15.748, 9.652, 416.052, 269.748))
        # One closed border plus four center marks of four lines each.
        self.assertEqual(len(sheet.lines), 17)
        for key, size in SIZES.items():
            self.assertTrue(fits(size, self.block), key)
        portrait_a = (SIZES["A"][1], SIZES["A"][0])
        self.assertTrue(fits(portrait_a, self.block))
        self.assertFalse(fits((100.0, 100.0), self.block))

    def test_field_positions_job_number_material_weight_and_logo(self):
        sheet = _paint(self.block)
        texts = _texts(sheet)
        self.assertIn("33107", texts)
        self.assertIn("SEE ABOVE INDIVIDUAL PART DETAILS", texts)
        self.assertIn("0.44 lb", texts)
        self.assertIn("1:2", texts)
        self.assertIn("1/1", texts)
        self.assertIn("B", texts)
        self.assertIn("A", texts)
        self.assertIn("AR", texts)
        self.assertIn("2026-11-01", texts)
        self.assertIn("SYMMETRICAL", " ".join(texts))
        self.assertIn("UNAUTHORIZED", " ".join(texts))
        self.assertIn("RADII = 0.25 [6]", texts)
        self.assertNotIn("WT EXCL. HARDWARE", texts)
        number = next(item for item in sheet.texts if item[2] == "33107")
        self.assertAlmostEqual(number[0], ORIGIN[0] + 51.582 + 1.0, delta=0.05)
        self.assertAlmostEqual(number[1], ORIGIN[1] + 31.339 + 0.55, delta=0.05)
        bottom = next(points for points, _kind in sheet.lines
                      if len(points) == 2 and abs(points[0][1] - ORIGIN[1]) < 0.05 and abs(points[1][1] - ORIGIN[1]) < 0.05
                      and abs(points[1][0] - points[0][0] - 140.04) < 0.05)
        self.assertAlmostEqual(bottom[0][0], ORIGIN[0], delta=0.05)
        self.assertAlmostEqual(bottom[1][0], ORIGIN[0] + 140.04, delta=0.05)
        self.assertEqual(len(sheet.images), 1)
        ix, iy, iw, ih, image = sheet.images[0]
        self.assertEqual(image["pixels"], (963, 473))
        self.assertAlmostEqual(iw / ih, 963 / 473, delta=1e-6)
        slot = self.block["logo"]
        self.assertGreaterEqual(ix, ORIGIN[0] + slot["x"] - 0.05)
        self.assertGreaterEqual(iy, ORIGIN[1] + slot["y"] - 0.05)
        self.assertLessEqual(ix + iw, ORIGIN[0] + slot["x"] + slot["width"] + 0.05)
        self.assertLessEqual(iy + ih, ORIGIN[1] + slot["y"] + slot["height"] + 0.05)
        # Centred in the slot.
        self.assertAlmostEqual(ix + iw / 2, ORIGIN[0] + slot["x"] + slot["width"] / 2, delta=0.05)
        self.assertAlmostEqual(iy + ih / 2, ORIGIN[1] + slot["y"] + slot["height"] / 2, delta=0.05)

    def test_job_number_override_and_weight_note(self):
        context = _context(fields={
            "number": "99999", "weight": "2.5 lb", "description": "Override",
            "drawn_by": "AR", "drawn_date": "2026-11-01",
        })
        context["mass"] = {"text": "0.44 lb", "note": "WT EXCL. HARDWARE", "grams": 198.72}
        context["assembly"] = False
        context["material"] = "Aluminum 6061-T6"
        sheet = _paint(self.block, context)
        texts = _texts(sheet)
        self.assertIn("99999", texts)
        self.assertNotIn("33107", texts)
        self.assertIn("2.5 lb", texts)
        self.assertIn("WT EXCL. HARDWARE", texts)
        self.assertIn("Aluminum 6061-T6", texts)
        self.assertNotIn("SEE ABOVE INDIVIDUAL PART DETAILS", texts)

    def test_parts_table_sits_at_the_top_right(self):
        sheet = _paint(self.block)
        self.assertIn("B.O.M.", _texts(sheet))
        self.assertIn("PART NAME", _texts(sheet))
        self.assertIn("Molded Top Plate", _texts(sheet))
        self.assertIn("Aluminum 6061-T6", _texts(sheet))
        self.assertIn(format_mass(155.52, "in"), _texts(sheet))
        region = next(box for kind, _index, box in sheet.regions if kind == "parts-list")
        self.assertAlmostEqual(region[2], 416.052, delta=0.05)
        self.assertAlmostEqual(region[3], 269.748, delta=0.05)
        self.assertAlmostEqual(region[2] - region[0], 129.888, delta=0.05)
        self.assertAlmostEqual(parts_table_height(self.block, _context()), region[3] - region[1], delta=0.05)


class ExportTests(unittest.TestCase):
    def test_dxf_text_and_line_positions(self):
        import ezdxf
        block = load_templates()["keystone-ansi"]
        sheet = _paint(block)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "sheet.dxf"
            sheet.dxf(path)
            document = ezdxf.readfile(path)
        self.assertEqual(document.header["$INSUNITS"], 4)
        texts = [entity.dxf.text for entity in document.modelspace().query("TEXT")]
        self.assertIn("33107", texts)
        entity = next(item for item in document.modelspace().query("TEXT") if item.dxf.text == "33107")
        self.assertAlmostEqual(entity.dxf.insert.x, ORIGIN[0] + 51.582 + 1.0, delta=0.05)
        self.assertAlmostEqual(entity.dxf.insert.y, ORIGIN[1] + 31.339 + 0.55, delta=0.05)
        self.assertEqual(entity.dxf.layer, "TITLEBLOCK")
        lines = []
        for entity in document.modelspace().query("LWPOLYLINE"):
            points = [(point[0], point[1]) for point in entity.get_points("xy")]
            if len(points) == 2 and abs(points[0][1] - ORIGIN[1]) < 0.05 and abs(points[1][1] - ORIGIN[1]) < 0.05 \
                    and abs(abs(points[1][0] - points[0][0]) - 140.04) < 0.05:
                lines.append(entity)
        self.assertTrue(lines)
        self.assertEqual(lines[0].dxf.layer, "TITLEBLOCK")
        images = list(document.modelspace().query("IMAGE"))
        self.assertEqual(len(images), 1)

    def test_pdf_page_and_text(self):
        from steve.drawing_pdf import pdf
        block = load_templates()["keystone-ansi"]
        sheet = _paint(block)
        data = pdf([sheet], title="33107")
        self.assertTrue(data.startswith(b"%PDF"))
        width, height, text, images = _pdf_info(data)
        self.assertAlmostEqual(width, 431.8 * 72 / 25.4, delta=1.0)
        self.assertAlmostEqual(height, 279.4 * 72 / 25.4, delta=1.0)
        self.assertIn("33107", text)
        self.assertIn("KEYSTONE SUPPLY", text)
        self.assertIn("0.44 lb", text)
        self.assertIn("B.O.M.", text)
        self.assertGreaterEqual(images, 1)


class NoTemplateTests(unittest.TestCase):
    def test_builtin_block_is_unchanged(self):
        class Bare:
            standard = "ISO"
            fields = {"number": "PL-001"}
            title = "Inspection plate"
            revisions = []
            title_block = None
            table_width = TITLE_WIDTH
            projection = "first"
            units = "mm"
            sheet = "A3"
            placed = None

        sheet = Sheet(SIZES["A3"], STANDARDS["ISO"])
        x0, y0, x1, y1 = _frame(sheet, "ISO")
        height = _title_block(sheet, Bare(), x1, y0, "1:2", 1, 1)
        texts = " ".join(_texts(sheet))
        self.assertIn("TITLE", texts)
        self.assertIn("DRAWING NO.", texts)
        self.assertIn("REV", texts)
        self.assertIn("PL-001", texts)
        self.assertNotIn("KEYSTONE", texts)
        self.assertNotIn("33107", texts)
        self.assertAlmostEqual(height, 32.0, delta=0.1)  # 14 + 9 + 9, no extra fields
        self.assertAlmostEqual(x1 - TITLE_WIDTH, x1 - 180.0, delta=0.01)
        self.assertEqual(x0, 20.0)
        self.assertTrue(any(item[2] == "1" for item in sheet.texts))


class SampleTests(unittest.TestCase):
    def test_sample_sheet_is_ansi_b(self):
        block = load_templates()["keystone-ansi"]
        sheet = _paint(block)
        self.assertEqual(sheet.width, SIZES["B"][0])
        self.assertEqual(sheet.height, SIZES["B"][1])
        self.assertIn("33107", _texts(sheet))


class GeometryTests(unittest.TestCase):
    """A real two-box assembly. CadQuery is imported here, never the desktop host."""

    def setUp(self):
        from steve.drawing import SHEETS
        from steve import design
        SHEETS.clear()
        design._COMPONENTS.clear()

    def tearDown(self):
        self.setUp()

    def _assembly(self):
        from steve import Component, Design
        plate = Component("plate", "33107 Molded Top Plate")
        plate.box("body", 120, 80, 6)
        plate.material("aluminum-6061-t6")
        rib = Component("rib", "33108 Rib")
        rib.box("body", 80, 10, 20)
        rib.material("aluminum-6061-t6")
        design = Design("33107 Molded Top Plate Assembly")
        design.add(plate, name="plate_1")
        design.add(rib, at=(0, 50, 6), name="rib_1")
        return design.result()

    def test_assembly_fills_number_mass_material_and_parts_table(self):
        from steve.drawing import SHEETS, Drawing, render
        SHEETS.clear()
        template = default_template_id(load_templates())
        drawing = Drawing(self._assembly(), title="33107 Molded Top Plate Assembly", template=template,
                          standard="ANSI", sheet="B", views=[], scale=(1, 2),
                          fields={"description": "Molded top plate and rib", "drawn_by": "AR", "drawn_date": "2026-11-01",
                                  "revision": "A"})
        sheet, report = render(drawing, 1, 1)
        self.assertIsNone(report.get("error"))
        texts = _texts(sheet)
        self.assertIn("33107", texts)
        self.assertIn("SEE ABOVE INDIVIDUAL PART DETAILS", texts)
        self.assertIn("Aluminum 6061-T6", texts)
        self.assertIn("0.44 lb", texts)
        self.assertIn("0.34 lb", texts)
        self.assertIn("0.10 lb", texts)
        self.assertIn("B.O.M.", texts)
        self.assertIn("33107 Molded Top Plate", texts)
        self.assertNotIn("WT EXCL. HARDWARE", texts)
        self.assertNotIn("WT INCOMPLETE", texts)
        self.assertEqual(len(sheet.images), 1)
        self.assertEqual(sheet.width, SIZES["B"][0])

    def test_part_name_supplies_the_job_number_and_a_missing_density_is_noted(self):
        from steve import Model
        from steve.drawing import SHEETS, Drawing, render
        SHEETS.clear()
        model = Model("33107 Plate")
        model.box("plate", 120, 80, 6)
        model.box("boss", 10, 10, 10, op="new")
        model.material("aluminum-6061-t6", bodies=["plate"])
        drawing = Drawing(model.result(), title="Cover", template="keystone-ansi", standard="ANSI", sheet="B",
                          views=[], scale=(1, 1))
        sheet, _report = render(drawing, 1, 1)
        texts = _texts(sheet)
        self.assertIn("33107", texts)
        self.assertNotIn("Cover", texts)
        self.assertIn("Aluminum 6061-T6", texts)
        self.assertIn("WT INCOMPLETE", texts)
        self.assertIn("0.34 lb", texts)

    def test_omitted_template_keeps_the_builtin_block(self):
        from steve import Model
        from steve.drawing import SHEETS, Drawing, render
        SHEETS.clear()
        model = Model("33107 Plate")
        model.box("plate", 10, 10, 10)
        model.material("aluminum-6061-t6")
        drawing = Drawing(model.result(), title="33107 Plate", views=[], scale=(1, 1))
        self.assertIsNone(drawing.placed)
        sheet, _report = render(drawing, 1, 1)
        texts = " ".join(_texts(sheet))
        self.assertIn("DRAWING NO.", texts)
        self.assertIn("33107 Plate", texts)  # the built-in block prints the title, not a job number
        self.assertNotIn("KEYSTONE", texts)
        self.assertNotIn("WT INCOMPLETE", texts)

    def test_hand_written_title_block_wins(self):
        from steve import Model
        from steve.drawing import SHEETS, Drawing, render
        SHEETS.clear()
        model = Model("33107 Plate")
        model.box("plate", 10, 10, 10)
        drawing = Drawing(model.result(), title="33107 Plate", template="keystone-ansi", views=[], scale=(1, 1),
                          title_block=[{"height": 10, "cells": [{"width": 80, "text": "CUSTOM BLOCK"}]}])
        self.assertIsNone(drawing.placed)
        sheet, _report = render(drawing, 1, 1)
        texts = _texts(sheet)
        self.assertIn("CUSTOM BLOCK", texts)
        self.assertNotIn("33107", texts)
        self.assertNotIn("KEYSTONE", texts)


if __name__ == "__main__":
    unittest.main()
