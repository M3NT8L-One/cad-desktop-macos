"""Pure development of a right circular cone or a press-brake taper.

No geometry kernel. Distances are millimetres and angles are degrees, except
``weld_gap_in``, which is inches. One international inch is 25.4 mm, so the gap
enters the rest of the model as ``weld_gap_in * 25.4``.

A smooth cone is developed on the neutral surface. Ends are square to the axis.
The neutral radius on an end plane is ``R_in + k * t / cos α``, where α is the
angle between the generator and the axis. The flat is an annular sector.

A faceted cone uses the same end radii as the polygon's circumradius (the
corner, not the flat). ``facets`` panels meet at ``facets - 1`` straight bends.
The bend angle is the deflection between adjacent facet normals. Its allowance
is the cylindrical allowance ``γ * (bend_radius + k * thickness)``.

The weld gap is removed from the developed large-end boundary. For a smooth
cone that shortens the outer sector arc by the gap. For a faceted cone it
shortens the large-end cut path (chords plus bend allowances) by the same gap.
Partial sweeps use the same rule. The default gap is 0.
"""
from __future__ import annotations

import math

TOL = 1e-7
INCH_TO_MM = 25.4


class ConeInputError(ValueError):
    """A cone input the shop call should reject before any solid is built."""


def _num(value, label, *, minimum=None, positive=False):
    if isinstance(value, bool):
        raise ConeInputError(f'{label} must be a finite number.')
    try:
        value = float(value)
    except (TypeError, ValueError):
        raise ConeInputError(f'{label} must be a finite number.') from None
    if not math.isfinite(value):
        raise ConeInputError(f'{label} must be a finite number.')
    if positive and value <= TOL:
        raise ConeInputError(f'{label} must be greater than zero.')
    if minimum is not None and value < minimum - TOL:
        raise ConeInputError(f'{label} is outside its supported range.')
    return value


def weld_gap_mm(weld_gap_in):
    """Inches to millimetres. ``None`` and omission are a closed seam (0).

    One international inch is 25.4 millimetres, so ``gap_mm = weld_gap_in * 25.4``.
    """
    if weld_gap_in is None:
        return 0.0
    gap_in = _num(weld_gap_in, 'Weld gap')
    if gap_in < -TOL:
        raise ConeInputError('Weld gap must be zero or positive.')
    return gap_in * INCH_TO_MM


def _length_pair(height, slant, delta):
    """Exactly one of axial height or generator slant. ``delta`` is the radius change."""
    given = (height is not None, slant is not None)
    if given == (False, False):
        raise ConeInputError('Give an axial height or a slant height.')
    if given == (True, True):
        raise ConeInputError('Give an axial height or a slant height, not both.')
    if slant is not None:
        length = _num(slant, 'Slant height', positive=True)
        leftover = length * length - delta * delta
        if leftover <= TOL * TOL:
            raise ConeInputError('Slant height is too short for these end radii.')
        return math.sqrt(leftover), length
    axial = _num(height, 'Height', positive=True)
    return axial, math.hypot(axial, delta)


def _deflection(radius_large, height, delta_radius, sweep_deg, facets):
    """Bend deflection (degrees) between adjacent facets of a regular taper.

    ``radius_large`` is the inside corner radius at the large end. The apex
    distance and the plan angle per facet fix the angle between outward normals.
    """
    half = math.radians(sweep_deg / facets) / 2
    opening = math.radians(sweep_deg / facets)
    apex = radius_large * height / abs(delta_radius)
    cos_half = math.cos(half)
    cos_open = math.cos(opening)
    numer = apex * apex * cos_open + radius_large * radius_large * cos_half * cos_half
    denom = apex * apex + radius_large * radius_large * cos_half * cos_half
    ratio = min(1.0, max(-1.0, numer / denom))
    return math.degrees(math.acos(ratio))


def _unit(vector):
    x, y = vector
    scale = math.hypot(x, y)
    if scale <= TOL:
        raise ConeInputError('A faceted edge has no length.')
    return (x / scale, y / scale)


def _add(a, b, scale=1.0):
    return (a[0] + b[0] * scale, a[1] + b[1] * scale)


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1])


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1]


def _facet_layout(radius_start, radius_end, height, sweep_deg, facets, bend_radius, k_factor, thickness, gap_mm):
    """Flat polygons for a brake-formed taper, plus the numbers a test can check.

    Corner radii are the circumradius. The large-end cut path is the chords of
    the trimmed facets plus one allowance width per bend. The weld gap shortens
    that path from the open seam.
    """
    if facets < 2 or abs(facets - round(facets)) > TOL:
        raise ConeInputError('Facets must be a whole number, 2 or more.')
    facets = int(round(facets))
    bend_radius = _num(bend_radius, 'Bend radius', positive=True)
    plan = sweep_deg / facets
    large_is_start = abs(radius_start) >= abs(radius_end)
    radius_large = radius_start if large_is_start else radius_end
    gamma = _deflection(radius_large, height, radius_start - radius_end, sweep_deg, facets)
    if gamma <= TOL:
        raise ConeInputError('These facets are already flat. Increase the sweep or reduce the facet count.')
    allowance = math.radians(gamma) * (bend_radius + k_factor * thickness)
    if allowance <= TOL:
        raise ConeInputError('The bend allowance is zero.')
    setback = bend_radius * math.tan(math.radians(gamma) / 2)
    half = math.radians(plan) / 2
    base_start = 2 * radius_start * math.sin(half)
    base_end = 2 * radius_end * math.sin(half)
    leg = math.hypot(height, radius_start - radius_end)
    face_height = math.hypot(height, (radius_start - radius_end) * math.cos(half))
    if face_height <= TOL or leg <= TOL:
        raise ConeInputError('A facet has no face height.')
    trim = setback * leg / face_height
    overhang = (base_start - base_end) / 2

    def polygon(left_trim, right_trim, gap):
        # Start edge on y = 0, end edge on y = face height. Trims are distances along each base.
        left = left_trim
        right = right_trim
        start_left = (left, 0.0)
        start_right = (base_start - right, 0.0)
        end_right = (overhang + base_end - right, face_height)
        end_left = (overhang + left, face_height)
        if gap > TOL:
            edge = _sub(start_right, start_left)
            length = math.hypot(*edge)
            if gap >= length - TOL:
                raise ConeInputError('The weld gap is wider than the developed seam edge.')
            start_left = _add(start_left, _unit(edge), gap)
        points = (start_left, start_right, end_right, end_left)
        if _polygon_area(points) <= TOL:
            raise ConeInputError('A bend consumes its facet. Increase the sweep or reduce the bend radius.')
        return points

    facets_local = []
    for index in range(facets):
        left = 0.0 if index == 0 else trim
        right = 0.0 if index == facets - 1 else trim
        gap = gap_mm if index == 0 else 0.0
        facets_local.append(polygon(left, right, gap))

    # Place facet 0 in the plane, then walk bend rectangles and the next facet off each right leg.
    placed = []
    frames = []
    bends = []
    transform = ((1.0, 0.0), (0.0, 1.0), (0.0, 0.0))  # x axis, y axis, origin

    def apply(point, mapping):
        (xx, xy), (yx, yy), origin = mapping
        return (origin[0] + xx * point[0] + yx * point[1], origin[1] + xy * point[0] + yy * point[1])

    for index, local in enumerate(facets_local):
        frames.append(transform)
        world = tuple(apply(point, transform) for point in local)
        placed.append(world)
        if index == facets - 1:
            break
        start_right, end_right = world[1], world[2]
        leg_vec = _sub(end_right, start_right)
        along = _unit(leg_vec)
        # Outward is away from the facet centroid.
        center = tuple(sum(point[axis] for point in world) / 4 for axis in (0, 1))
        normal = (along[1], -along[0])
        if _dot(normal, _sub(center, start_right)) > 0:
            normal = (-normal[0], -normal[1])
        outer_start = _add(start_right, normal, allowance)
        outer_end = _add(end_right, normal, allowance)
        bends.append(dict(corners=(start_right, end_right, outer_end, outer_start),
                          length_mm=math.hypot(*leg_vec), allowance_mm=allowance, angle_deg=gamma))
        # Next facet's left leg (local point 0 → point 3) lands on the rectangle's outer edge.
        nxt = facets_local[index + 1]
        src0, src1 = nxt[0], nxt[3]
        src = _unit(_sub(src1, src0))
        dst = _unit(_sub(outer_end, outer_start))
        # Rotation taking src to dst, then translation taking src0 to outer_start.
        cos_r = max(-1.0, min(1.0, _dot(src, dst)))
        sin_r = src[0] * dst[1] - src[1] * dst[0]
        rotation = ((cos_r, sin_r), (-sin_r, cos_r))
        moved_src0 = (rotation[0][0] * src0[0] + rotation[1][0] * src0[1],
                      rotation[0][1] * src0[0] + rotation[1][1] * src0[1])
        origin = (outer_start[0] - moved_src0[0], outer_start[1] - moved_src0[1])
        transform = (rotation[0], rotation[1], origin)

    developed = 0.0
    area = 0.0
    for facet in placed:
        developed += math.dist(facet[0], facet[1])
        area += _polygon_area(facet)
    for bend in bends:
        developed += math.dist(bend['corners'][0], bend['corners'][3])
        area += bend['length_mm'] * bend['allowance_mm']
    corner_chord = 2 * radius_large * math.sin(math.radians(plan) / 2)
    solids = _facet_solids(radius_start, radius_end, height, sweep_deg, facets, trim, gap_mm)
    return dict(bend_angle_deg=gamma, bend_allowance_mm=allowance, bend_count=facets - 1,
                corner_chord_mm=corner_chord, developed_length_mm=developed, setback_mm=setback,
                leg_mm=leg, face_height_mm=face_height, facets_local=facets_local, facets_world=placed,
                flat_frames=frames, bends_world=bends, solids=solids, radius_large_mm=radius_large,
                bend_radius_mm=bend_radius, flat_area_mm2=area)


def _sub3(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _add3(a, b, scale=1.0):
    return (a[0] + b[0] * scale, a[1] + b[1] * scale, a[2] + b[2] * scale)


def _unit3(vector):
    scale = math.sqrt(vector[0] ** 2 + vector[1] ** 2 + vector[2] ** 2)
    if scale <= TOL:
        raise ConeInputError('A faceted edge has no length.')
    return (vector[0] / scale, vector[1] / scale, vector[2] / scale)


def _slide(start, end, distance):
    """Point ``distance`` millimetres from ``start`` toward ``end``."""
    if distance <= TOL:
        return start
    return _add3(start, _unit3(_sub3(end, start)), distance)


def _facet_solids(radius_start, radius_end, height, sweep_deg, facets, trim, gap_mm):
    """Inside corner quads in axis coordinates: X along the axis, angle in YZ.

    Each quad is the trimmed inside face, congruent with that facet's flat polygon.
    """
    opening = math.radians(sweep_deg / facets)
    quads = []
    for index in range(facets):
        theta = index * opening
        left = 0.0 if index == 0 else trim
        right = 0.0 if index == facets - 1 else trim
        gap = gap_mm if index == 0 else 0.0

        def corner(radius, angle, axial):
            return (axial, radius * math.cos(angle), radius * math.sin(angle))

        sharp_start_left = corner(radius_start, theta, 0.0)
        sharp_start_right = corner(radius_start, theta + opening, 0.0)
        sharp_end_right = corner(radius_end, theta + opening, height)
        sharp_end_left = corner(radius_end, theta, height)
        quads.append((
            _slide(sharp_start_left, sharp_start_right, left + gap),
            _slide(sharp_start_right, sharp_start_left, right),
            _slide(sharp_end_right, sharp_end_left, right),
            _slide(sharp_end_left, sharp_end_right, left),
        ))
    return quads


def _polygon_area(points):
    total = 0.0
    for index, point in enumerate(points):
        nxt = points[(index + 1) % len(points)]
        total += point[0] * nxt[1] - nxt[0] * point[1]
    return abs(total) / 2


def develop(radius1, radius2, thickness, k_factor, *, height=None, slant=None, angle=360,
            radius_reference='inside', weld_gap_in=0, facets=None, bend_radius=None):
    """Return the flat-pattern numbers for one cone.

    ``radius1`` is the radius at the start of the axis and ``radius2`` at the
    other end. ``radius_reference`` is ``inside`` (default), ``outside`` or
    ``neutral``. Give ``height`` (axial) or ``slant`` (generator), not both.
    """
    if radius_reference not in ('inside', 'outside', 'neutral'):
        raise ConeInputError('Radius reference must be inside, outside or neutral.')
    radius_start = _num(radius1, 'Radius', minimum=0)
    radius_end = _num(radius2, 'Radius', minimum=0)
    sweep = _num(angle, 'Sweep', minimum=0)
    if sweep <= TOL or sweep > 360 + TOL:
        raise ConeInputError('Sweep must be greater than 0 and at most 360 degrees.')
    sweep = min(sweep, 360.0)
    thickness = _num(thickness, 'Thickness', positive=True)
    k_factor = _num(k_factor, 'K factor', minimum=0)
    if k_factor > 1 + TOL:
        raise ConeInputError('K factor must be from 0 to 1.')
    k_factor = min(k_factor, 1.0)
    gap = weld_gap_mm(weld_gap_in)
    delta = radius_start - radius_end
    if abs(delta) <= TOL:
        raise ConeInputError('Equal end radii are a cylinder. Use sheet_roll.')
    axial, slant_length = _length_pair(height, slant, delta)
    cos_alpha = axial / slant_length
    radial_thickness = thickness / cos_alpha
    radial_neutral = k_factor * thickness / cos_alpha
    if radius_reference == 'inside':
        inside = (radius_start, radius_end)
    elif radius_reference == 'outside':
        inside = (radius_start - radial_thickness, radius_end - radial_thickness)
    else:
        inside = (radius_start - radial_neutral, radius_end - radial_neutral)
    if inside[0] < -TOL or inside[1] < -TOL:
        raise ConeInputError('The radius is smaller than the sheet offset on that end.')
    inside = (max(0.0, inside[0]), max(0.0, inside[1]))
    outside = (inside[0] + radial_thickness, inside[1] + radial_thickness)
    neutral = (inside[0] + radial_neutral, inside[1] + radial_neutral)
    # Sector geometry uses the inside radius change. It matches the given change.
    inside_delta = inside[0] - inside[1]
    if abs(inside_delta) <= TOL:
        raise ConeInputError('Equal end radii are a cylinder. Use sheet_roll.')
    sector_radius = tuple(radius * slant_length / abs(inside_delta) for radius in neutral)
    neutral_large = max(neutral)
    large_arc = math.radians(sweep) * neutral_large
    if gap >= large_arc - TOL and facets is None:
        raise ConeInputError('The weld gap is wider than the developed large-end arc.')
    # Smooth: the gap shortens the outer sector arc, and the sweep with it.
    smooth_sweep = sweep if gap <= TOL else math.degrees((large_arc - gap) / neutral_large)
    smooth_arc = math.radians(smooth_sweep) * neutral_large
    sector_angle = smooth_sweep * abs(inside_delta) / slant_length
    area = math.radians(smooth_sweep) / 2 * (neutral[0] + neutral[1]) * slant_length
    result = dict(kind='cone' if facets is None else 'faceted', radius_reference=radius_reference,
                  inside_radius_mm=inside, outside_radius_mm=outside, neutral_radius_mm=neutral,
                  height_mm=axial, slant_mm=slant_length, requested_sweep_deg=sweep,
                  sweep_deg=smooth_sweep if facets is None else sweep, weld_gap_in=0.0 if weld_gap_in is None else float(weld_gap_in),
                  weld_gap_mm=gap, sector_radius_mm=sector_radius, sector_angle_deg=sector_angle,
                  large_arc_mm=smooth_arc, area_mm2=area, facets=None if facets is None else int(round(float(facets))),
                  bend_angle_deg=None, bend_allowance_mm=None, bend_count=0, corner_chord_mm=None,
                  developed_length_mm=smooth_arc, k_factor=k_factor, thickness_mm=thickness)
    if facets is None:
        return result
    if bend_radius is None:
        raise ConeInputError('A faceted cone uses the sheet bend radius.')
    layout = _facet_layout(inside[0], inside[1], axial, sweep, facets, bend_radius, k_factor, thickness, gap)
    result.update(kind='faceted', sweep_deg=sweep, bend_angle_deg=layout['bend_angle_deg'],
                  bend_allowance_mm=layout['bend_allowance_mm'], bend_count=layout['bend_count'],
                  corner_chord_mm=layout['corner_chord_mm'], developed_length_mm=layout['developed_length_mm'],
                  area_mm2=layout['flat_area_mm2'])
    result['_layout'] = layout
    return result
