"""Regenerate the sample B-size sheet.

Uses the vendored drawing runtime only. It does not import the desktop host, the vault, or a keyring.
Drawn, checked, and approved dates are the machine's local calendar day.

    python3 scripts/make_title_block_sample.py docs/samples/33107-molded-top-plate.pdf
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "vendor"))

from steve import Component, Design
from steve.drawing import SHEETS, Drawing, render
from steve.drawing_pdf import pdf
from steve.drawing_templates import default_template_id, load_templates


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("Usage: python3 scripts/make_title_block_sample.py <output.pdf>", file=sys.stderr)
        return 2
    destination = Path(argv[1])
    os.environ.setdefault("STEVE_PDF_FONTS", str(ROOT / "pdf-fonts"))
    plate = Component("plate", "33107 Molded Top Plate")
    plate.box("body", 120, 80, 6)
    plate.material("aluminum-6061-t6")
    rib = Component("rib", "33108 Rib")
    rib.box("body", 80, 10, 20)
    rib.material("aluminum-6061-t6")
    design = Design("33107 Molded Top Plate Assembly")
    design.add(plate, name="plate_1")
    design.add(rib, at=(0, 50, 6), name="rib_1")
    SHEETS.clear()
    drawing = Drawing(
        design.result(),
        title="33107 Molded Top Plate Assembly",
        template=default_template_id(load_templates()),
        standard="ANSI",
        sheet="B",
        views=("front",),
        scale=(1, 2),
        fields={
            "description": "Molded top plate and rib",
            "drawn_by": "AR",
            "checked_by": "BK",
            "approved_by": "CL",
            "revision": "A",
        },
    )
    sheet, report = render(drawing, 1, 1)
    if report.get("error"):
        print(report["error"], file=sys.stderr)
        return 1
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(pdf([sheet], title=drawing.title))
    print(destination)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
