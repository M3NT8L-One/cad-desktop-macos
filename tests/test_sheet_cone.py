"""Known-answer tests for cone and tapered-sheet flat patterns.

Expected numbers are written here. They are not produced by calling the development
code. Geometry and DXF checks run only when CadQuery is installed; the pure cases
load cone_math.py directly and do not import it.
"""
import importlib.util
import math
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MATH_PATH = ROOT / 'vendor' / 'steve' / 'sheetmetal' / 'cone_math.py'

# Worked frustum: inside radii 50 and 30 mm, axial height 40 mm, thickness 1.5 mm, K 0.4.
#   L = sqrt(40² + 20²) = sqrt(2000)
#   cos α = 40 / L
#   neutral offset = 0.4 * 1.5 / cos α
#   R_n large = 50 + offset, sector outer radius = R_n large * L / 20
#   full sector angle = 360 * 20 / L
FULL_SECTOR_DEG = 160.99689437998484
FULL_OUTER_RADIUS_MM = 113.30339887498948
QUARTER_SECTOR_DEG = 40.24922359499621
QUARTER_LARGE_ARC_MM = 79.59353854940095
# 0.1 inch * 25.4 = 2.54 mm removed from that quarter arc.
GAP_INCH = 0.1
GAP_MM = 2.54
GAPPED_ARC_MM = 77.05353854940094
GAPPED_SECTOR_DEG = 38.9647848102092
# Eight facets, corner radii, sweep 360°. γ from the facet-normal formula, allowance γ*(1.5+0.4*1.5).
FACET_ANGLE_DEG = 40.6577107549314
FACET_ALLOWANCE_MM = 1.490182929893831
FACET_COUNT = 7
CORNER_CHORD_MM = 38.268343236508976
DEVELOPED_LENGTH_MM = 308.6813616733662
SMOOTH_AREA_MM2 = 11428.199128880551
SMOOTH_VOLUME_MM3 = 17212.984528026624


def load_math():
    spec = importlib.util.spec_from_file_location('cone_math_under_test', MATH_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def hand_sector():
    """The worked sector, expanded here so a copied production bug cannot set the expected value."""
    length = math.sqrt(40 ** 2 + 20 ** 2)
    cosine = 40 / length
    neutral_large = 50 + 0.4 * 1.5 / cosine
    return 360 * 20 / length, neutral_large * length / 20


class ConeMathTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.math = load_math()

    def develop(self, **kwargs):
        values = dict(radius1=50, radius2=30, thickness=1.5, k_factor=0.4, height=40, angle=360)
        values.update(kwargs)
        radius1 = values.pop('radius1')
        radius2 = values.pop('radius2')
        thickness = values.pop('thickness')
        k_factor = values.pop('k_factor')
        return self.math.develop(radius1, radius2, thickness, k_factor, **values)

    def test_hand_expansion_matches_the_published_frustum(self):
        sector, outer = hand_sector()
        self.assertAlmostEqual(sector, FULL_SECTOR_DEG, places=9)
        self.assertAlmostEqual(outer, FULL_OUTER_RADIUS_MM, places=9)
        self.assertAlmostEqual(sector / 4, QUARTER_SECTOR_DEG, places=9)

    def test_worked_frustum_full_sweep(self):
        result = self.develop()
        self.assertAlmostEqual(result['sector_angle_deg'], FULL_SECTOR_DEG, places=9)
        self.assertAlmostEqual(max(result['sector_radius_mm']), FULL_OUTER_RADIUS_MM, places=9)
        self.assertAlmostEqual(result['area_mm2'], SMOOTH_AREA_MM2, places=6)
        self.assertEqual(result['kind'], 'cone')

    def test_worked_frustum_quarter(self):
        result = self.develop(angle=90)
        self.assertAlmostEqual(result['sector_angle_deg'], QUARTER_SECTOR_DEG, places=9)
        self.assertAlmostEqual(result['large_arc_mm'], QUARTER_LARGE_ARC_MM, places=9)

    def test_same_frustum_by_slant_height(self):
        slant = math.sqrt(2000)  # sqrt(40² + 20²), the generator of the worked frustum
        result = self.develop(height=None, slant=slant)
        self.assertAlmostEqual(result['height_mm'], 40, places=9)
        self.assertAlmostEqual(result['sector_angle_deg'], FULL_SECTOR_DEG, places=9)
        self.assertAlmostEqual(max(result['sector_radius_mm']), FULL_OUTER_RADIUS_MM, places=9)

    def test_outside_and_neutral_radius_options(self):
        # Outside = inside + t/cos α. Neutral = inside + k*t/cos α. Same worked frustum.
        outside = self.develop(radius1=51.67705098312484, radius2=31.677050983124843, radius_reference='outside')
        neutral = self.develop(radius1=50.67082039324994, radius2=30.670820393249937, radius_reference='neutral')
        for result in (outside, neutral):
            self.assertAlmostEqual(result['sector_angle_deg'], FULL_SECTOR_DEG, places=9)
            self.assertAlmostEqual(max(result['sector_radius_mm']), FULL_OUTER_RADIUS_MM, places=9)
            self.assertAlmostEqual(result['inside_radius_mm'][0], 50, places=9)
            self.assertAlmostEqual(result['inside_radius_mm'][1], 30, places=9)

    def test_quarter_sweep_with_weld_gap_in_inches(self):
        result = self.develop(angle=90, weld_gap_in=GAP_INCH)
        self.assertAlmostEqual(result['weld_gap_mm'], GAP_MM, places=9)
        self.assertAlmostEqual(result['large_arc_mm'], GAPPED_ARC_MM, places=9)
        self.assertAlmostEqual(result['sector_angle_deg'], GAPPED_SECTOR_DEG, places=9)
        self.assertAlmostEqual(QUARTER_LARGE_ARC_MM - result['large_arc_mm'], GAP_MM, places=9)

    def test_faceted_eight_corner_radius_dihedral_and_developed_length(self):
        result = self.develop(facets=8, bend_radius=1.5)
        self.assertEqual(result['bend_count'], FACET_COUNT)
        self.assertAlmostEqual(result['bend_angle_deg'], FACET_ANGLE_DEG, places=9)
        self.assertAlmostEqual(result['bend_allowance_mm'], FACET_ALLOWANCE_MM, places=9)
        self.assertAlmostEqual(result['corner_chord_mm'], CORNER_CHORD_MM, places=9)
        self.assertAlmostEqual(result['developed_length_mm'], DEVELOPED_LENGTH_MM, places=9)
        # The published chord is the circumradius chord, 2*R*sin(δ/2), δ = 45°.
        self.assertAlmostEqual(result['corner_chord_mm'], 2 * 50 * math.sin(math.radians(45) / 2), places=9)

    def test_faceted_weld_gap_removes_its_length_from_the_developed_path(self):
        closed = self.develop(facets=8, bend_radius=1.5)
        opened = self.develop(facets=8, bend_radius=1.5, weld_gap_in=GAP_INCH)
        self.assertAlmostEqual(closed['developed_length_mm'] - opened['developed_length_mm'], GAP_MM, places=6)

    def test_input_errors(self):
        errors = [
            ((), dict(height=40, slant=45), 'not both'),
            ((), dict(height=None), 'axial height or a slant height'),
            ((), dict(weld_gap_in=-0.1), 'zero or positive'),
            ((), dict(angle=0), 'Sweep'),
            ((), dict(angle=361), 'Sweep'),
            ((40, 40), dict(), 'sheet_roll'),
            ((), dict(facets=1, bend_radius=1.5), 'Facets'),
            ((), dict(radius_reference='mid'), 'inside, outside or neutral'),
        ]
        for radii, kwargs, fragment in errors:
            with self.subTest(kwargs=kwargs, radii=radii):
                arguments = {}
                if radii:
                    arguments['radius1'], arguments['radius2'] = radii
                arguments.update(kwargs)
                with self.assertRaises(self.math.ConeInputError) as caught:
                    self.develop(**arguments)
                self.assertIn(fragment, str(caught.exception))


def _cad_available():
    try:
        import cadquery  # noqa: F401
    except ImportError:
        return False
    return True


@unittest.skipUnless(_cad_available(), 'CadQuery is not installed; pure cone tests still run')
class ConeGeometryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import sys
        from cadquery import occ_compat
        occ_compat.enable()
        vendor = str(ROOT / 'vendor')
        if vendor not in sys.path:
            sys.path.insert(0, vendor)
        from steve import Model, SheetMetalRule
        from steve.sheetmetal.export import dxf
        cls.Model = Model
        cls.Rule = SheetMetalRule
        cls.dxf = staticmethod(dxf)
        cls.rule = SheetMetalRule(1.5, 1.5, 0.4, source='cone flat-pattern test')

    def build(self, **kwargs):
        model = self.Model()
        model.sheet_cone('cone', **kwargs, rule=self.rule)
        feature = model.features[-1]
        self.assertEqual(feature.status, 'ok', feature.error)
        return model

    def test_smooth_flat_and_volume_match_the_hand_sector(self):
        model = self.build(radius1=50, radius2=30, height=40, angle=360)
        sheet = model._sheet_metal['cone']
        development = sheet.development
        self.assertAlmostEqual(development['sector_angle_deg'], FULL_SECTOR_DEG, places=9)
        self.assertAlmostEqual(max(development['sector_radius_mm']), FULL_OUTER_RADIUS_MM, places=9)
        self.assertAlmostEqual(sheet.flat_face().Area(), SMOOTH_AREA_MM2, places=6)
        self.assertEqual(len(sheet.flat_face().Faces()), 1)
        self.assertAlmostEqual(model.bodies['cone'].Volume(), SMOOTH_VOLUME_MM3, places=6)
        report = model.summary()['sheet_metal']['cone']['development']
        self.assertAlmostEqual(report['sector_angle_deg'], FULL_SECTOR_DEG, places=9)

    def test_quarter_weld_gap_on_the_built_sheet(self):
        model = self.build(radius1=50, radius2=30, height=40, angle=90, weld_gap_in=GAP_INCH)
        development = model._sheet_metal['cone'].development
        self.assertAlmostEqual(development['large_arc_mm'], GAPPED_ARC_MM, places=9)
        self.assertAlmostEqual(development['sector_angle_deg'], GAPPED_SECTOR_DEG, places=9)
        self.assertEqual(len([name for name in model._sheet_metal['cone'].names if 'seam' in name]), 2)

    def test_smooth_dxf_layers(self):
        model = self.build(radius1=50, radius2=30, height=40, angle=90)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'flat.dxf'
            self.dxf(model._sheet_metal['cone'], path)
            layers = _dxf_entities(path)
        self.assertEqual(layers[('CUT', 'ARC')], 2)
        self.assertEqual(layers[('CUT', 'LINE')], 2)
        self.assertEqual(layers[('ROLL', 'ARC')], 1)
        self.assertNotIn(('BEND_UP', 'LINE'), layers)
        self.assertNotIn(('BEND_DOWN', 'LINE'), layers)
        self.assertNotIn(('ROLL', 'LINE'), layers)

    def test_faceted_geometry_and_dxf_layers(self):
        model = self.build(radius1=50, radius2=30, height=40, angle=360, facets=8)
        sheet = model._sheet_metal['cone']
        self.assertEqual(len(sheet.bends), FACET_COUNT)
        self.assertTrue(all(abs(bend['angle_deg'] - FACET_ANGLE_DEG) < 1e-9 for bend in sheet.bends))
        self.assertTrue(all(abs(bend['allowance_mm'] - FACET_ALLOWANCE_MM) < 1e-9 for bend in sheet.bends))
        self.assertAlmostEqual(sheet.development['corner_chord_mm'], CORNER_CHORD_MM, places=9)
        self.assertAlmostEqual(sheet.development['developed_length_mm'], DEVELOPED_LENGTH_MM, places=9)
        self.assertEqual(len(sheet.flat_face().Faces()), 1)
        self.assertTrue(model.bodies['cone'].isValid())
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'flat.dxf'
            self.dxf(sheet, path)
            layers = _dxf_entities(path)
        self.assertEqual(layers[('BEND_UP', 'LINE')], FACET_COUNT)
        self.assertGreater(layers.get(('CUT', 'LINE'), 0), 0)
        self.assertNotIn(('ROLL', 'ARC'), layers)
        self.assertNotIn(('BEND_DOWN', 'LINE'), layers)

    def test_feature_rejects_bad_input(self):
        model = self.Model()
        model.sheet_cone('cone', 50, 30, height=40, slant=50, rule=self.rule)
        self.assertIn('not both', model.features[-1].error)
        model = self.Model()
        model.sheet_cone('cone', 50, 30, rule=self.rule)
        self.assertIn('axial height or a slant height', model.features[-1].error)


def _dxf_entities(path):
    import ezdxf
    document = ezdxf.readfile(path)
    counts = {}
    for entity in document.modelspace():
        key = (entity.dxf.layer, entity.dxftype())
        counts[key] = counts.get(key, 0) + 1
    return counts


if __name__ == '__main__':
    unittest.main()
