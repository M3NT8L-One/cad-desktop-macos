"""Build a smooth or faceted cone sheet from the pure development in cone_math."""
from __future__ import annotations

import math

import cadquery as cq
from OCP.BRepPrimAPI import BRepPrimAPI_MakeRevol
from OCP.gp import gp_Ax1, gp_Dir, gp_Pnt

from ..naming import Names
from .cone_math import ConeInputError, develop
from .geometry import Panel, Sheet, TOL, frame, place, plane, prism
from .validation import fail


def _vector(values):
    return cq.Vector(*values)


def _plane_of(origin, x_axis, y_axis):
    x = _vector(x_axis)
    y = _vector(y_axis)
    if x.Length < TOL or y.Length < TOL:
        fail('A cone frame is degenerate.')
    return cq.Plane(_vector(origin), xDir=x.normalized(), normal=x.cross(y).normalized())


def _world(placement, point):
    """Axis coordinates (axial, radial, curl) onto the sheet's placement plane."""
    origin, x_axis, y_axis, z_axis = placement
    return (origin[0] + x_axis[0] * point[0] + y_axis[0] * point[1] + z_axis[0] * point[2],
            origin[1] + x_axis[1] * point[0] + y_axis[1] * point[1] + z_axis[1] * point[2],
            origin[2] + x_axis[2] * point[0] + y_axis[2] * point[1] + z_axis[2] * point[2])


def _placement(location):
    """sheet_roll's plane: axis along X, seam along Y, positive sweep toward the normal."""
    origin = location.origin
    x_axis = location.xDir
    z_axis = location.zDir
    y_axis = z_axis.cross(x_axis)
    return (tuple(origin.toTuple()), tuple(x_axis.toTuple()), tuple(y_axis.toTuple()), tuple(z_axis.toTuple()))


def _polygon(points):
    wire = cq.Wire.makePolygon([cq.Vector(x, y, 0) for x, y in points], close=True)
    face = cq.Face.makeFromWires(wire)
    if not face.isValid() or face.Area() <= TOL:
        fail('A cone facet did not form a flat face.')
    return face


def _arc(radius, angle_deg, start_deg=0.0):
    if radius <= TOL:
        return None
    start = math.radians(start_deg)
    stop = math.radians(start_deg + angle_deg)
    mid = (start + stop) / 2

    def point(turn):
        return cq.Vector(radius * math.cos(turn), radius * math.sin(turn), 0)

    return cq.Edge.makeThreePointArc(point(start), point(mid), point(stop))


# Stations along a plane-trim edge. The cut is analytic; this polyline is how the
# flat face carries it. 64 equal sector-radius steps keeps the chord well under
# 0.01 mm on shop-size cones (the edge's angle changes by a fraction of a degree).
PLANE_EDGE_STEPS = 64


def _xy(radius, angle_deg):
    turn = math.radians(angle_deg)
    return cq.Vector(radius * math.cos(turn), radius * math.sin(turn), 0)


def _plane_angles(bend, radius):
    """Flat angles of the two plane cuts at one sector radius."""
    from .cone_math import plane_inset_angle_deg
    inset = plane_inset_angle_deg(radius, bend['sin_alpha'], bend['plane_offset_mm'])
    return inset, bend['untrimmed_sector_angle_deg'] - inset


def _curve(bend, end=False, outer_to_inner=False):
    inner, outer = sorted(bend['sector_radius_mm'])
    radii = [inner + (outer - inner) * index / PLANE_EDGE_STEPS for index in range(PLANE_EDGE_STEPS + 1)]
    if outer_to_inner:
        radii.reverse()
    points = []
    for radius in radii:
        start, finish = _plane_angles(bend, radius)
        points.append(_xy(radius, finish if end else start))
    return points


def sector_face(bend):
    """Annular sector (or a pie when the inner radius vanishes) in the flat's XY plane.

    A plane seam replaces the two radial edges with the developed intersection of
    the offset planes and the neutral cone.
    """
    inner, outer = sorted(bend['sector_radius_mm'])
    angle = bend['sector_angle_deg']
    if angle <= TOL or outer <= TOL:
        fail('The cone sector has no area.')
    if bend.get('seam') == 'plane' and bend.get('plane_offset_mm', 0) > TOL:
        start_outer, end_outer = _plane_angles(bend, outer)
        start_inner, end_inner = _plane_angles(bend, inner)
        outer_arc = _arc(outer, end_outer - start_outer, start_outer)
        end_curve = _curve(bend, end=True, outer_to_inner=True)
        start_curve = _curve(bend, end=False, outer_to_inner=False)
        if inner <= TOL:
            edges = [outer_arc, cq.Edge.makeLine(_xy(outer, end_outer), cq.Vector(0, 0, 0)),
                     cq.Edge.makeLine(cq.Vector(0, 0, 0), _xy(outer, start_outer))]
        else:
            inner_arc = _arc(inner, start_inner - end_inner, end_inner)
            edges = [outer_arc]
            edges.extend(cq.Edge.makeLine(end_curve[index], end_curve[index + 1]) for index in range(len(end_curve) - 1))
            edges.append(inner_arc)
            edges.extend(cq.Edge.makeLine(start_curve[index], start_curve[index + 1]) for index in range(len(start_curve) - 1))
        wire = cq.Wire.assembleEdges(edges)
    else:
        turn = math.radians(angle)
        outer_arc = _arc(outer, angle)
        end = cq.Vector(outer * math.cos(turn), outer * math.sin(turn), 0)
        start = cq.Vector(outer, 0, 0)
        if inner <= TOL:
            wire = cq.Wire.assembleEdges([
                cq.Edge.makeLine((0, 0, 0), start), outer_arc, cq.Edge.makeLine(end, (0, 0, 0))])
        else:
            inner_arc = cq.Edge.makeThreePointArc(
                cq.Vector(inner * math.cos(turn), inner * math.sin(turn), 0),
                cq.Vector(inner * math.cos(turn / 2), inner * math.sin(turn / 2), 0),
                cq.Vector(inner, 0, 0))
            wire = cq.Wire.assembleEdges([
                outer_arc, cq.Edge.makeLine(end, cq.Vector(inner * math.cos(turn), inner * math.sin(turn), 0)),
                inner_arc, cq.Edge.makeLine(cq.Vector(inner, 0, 0), start)])
    face = cq.Face.makeFromWires(wire)
    if not face.isValid():
        fail('The cone flat pattern is not a valid sector.')
    return face


def sector_mark(bend):
    """Mid-slant arc of a smooth cone, the ROLL mark, staying inside a plane trim."""
    inner, outer = sorted(bend['sector_radius_mm'])
    radius = (inner + outer) / 2
    if bend.get('seam') == 'plane' and bend.get('plane_offset_mm', 0) > TOL:
        start, end = _plane_angles(bend, radius)
        return _arc(radius, end - start, start)
    return _arc(radius, bend['sector_angle_deg'])


def _smooth_solid(bend, thickness):
    start, end = bend['inside_radius_mm']
    height = bend['height_mm']
    slant = math.hypot(height, start - end)
    offset = thickness * slant / height
    points = [(0, start, 0), (height, end, 0), (height, end + offset, 0), (0, start + offset, 0)]
    edges = [cq.Edge.makeLine(points[i], points[(i + 1) % 4]) for i in range(4)]
    face = cq.Face.makeFromWires(cq.Wire.assembleEdges(edges))
    maker = BRepPrimAPI_MakeRevol(face.wrapped, gp_Ax1(gp_Pnt(0, 0, 0), gp_Dir(1, 0, 0)), math.radians(bend['sweep_deg']))
    if not maker.IsDone():
        fail('Could not build the conical sheet.')
    local = cq.Shape.cast(maker.Shape())
    if bend.get('seam') == 'plane' and bend.get('plane_offset_mm', 0) > TOL:
        local = _cut_offset_planes(local, bend['sweep_deg'], bend['plane_offset_mm'])
    placed = place(local, frame(cq.Plane(_vector(bend['origin']), xDir=_vector(bend['axis']), normal=_vector(bend['normal']))))
    names = Names()
    identity = bend['id']
    seams = []
    axis = _vector(bend['axis'])
    origin = _vector(bend['origin'])
    for face in placed.Faces():
        if face.geomType() == 'CONE':
            names.add(f'{identity}.side', [face])
            continue
        normal = face.normalAt()
        if abs(normal.dot(axis)) > 0.5:
            station = (face.Center() - origin).dot(axis)
            names.add(f'{identity}.start' if station < height / 2 else f'{identity}.end', [face])
        else:
            seams.append(face)
    seams.sort(key=lambda face: (face.Center() - origin).dot(_vector(bend['outward'])))
    for index, face in enumerate(seams):
        names.add(f'{identity}.seam.{index}', [face])
    return placed, names


def _cut_offset_planes(solid, sweep_deg, offset):
    """Drop the material outside two planes parallel to the axis.

    The revolve runs from the +Y radial plane toward +Z. Each end plane is
    ``offset`` millimetres toward the material from its radial plane.
    """
    beta = math.radians(sweep_deg)
    size = 1.0e6

    def cut(shape, origin, normal):
        cutter = cq.Workplane(cq.Plane(origin=cq.Vector(*origin), normal=cq.Vector(*normal))).rect(size, size).extrude(-size)
        return shape.cut(cutter.val())

    solid = cut(solid, (0, 0, offset), (0, 0, 1))
    solid = cut(solid, (0, offset * math.sin(beta), -offset * math.cos(beta)), (0, math.sin(beta), -math.cos(beta)))
    if solid.Volume() <= TOL:
        fail('The weld gap is too large for this sweep.')
    return solid


def smooth_piece(sheet, bend, flat):
    if flat:
        data = sheet.unfolded_frame(bend['flat'])
        face = place(sector_face(bend), data)
        shape, names = prism(face, -plane(data).zDir * sheet.rules.thickness, bend['id'], ['start', 'outer', 'end', 'inner'])
        return shape, names
    return _smooth_solid(bend, sheet.rules.thickness)


def _map_frame(local_points, world_points):
    """Rigid map sending the local polygon onto the world polygon, as a plane frame."""
    source = local_points[0], local_points[1], local_points[3]
    target = world_points[0], world_points[1], world_points[3]
    base = source[0]
    vx = (source[1][0] - base[0], source[1][1] - base[1])
    vy = (source[2][0] - base[0], source[2][1] - base[1])
    determinant = vx[0] * vy[1] - vx[1] * vy[0]
    if abs(determinant) <= TOL:
        fail('A cone facet is degenerate.')
    # Images of local (1, 0) and (0, 1).
    wx = tuple(target[1][i] - target[0][i] for i in range(len(target[0])))
    wy = tuple(target[2][i] - target[0][i] for i in range(len(target[0])))

    def combine(a, b):
        return tuple(a * wx[i] + b * wy[i] for i in range(len(wx)))

    x_axis = combine(vy[1] / determinant, -vx[1] / determinant)
    y_axis = combine(-vy[0] / determinant, vx[0] / determinant)
    origin = tuple(target[0][i] - (x_axis[i] * base[0] + y_axis[i] * base[1]) for i in range(len(wx)))
    return _plane_of(origin, x_axis, y_axis)


def _public_development(spec):
    """Numbers only, with lists instead of tuples, so a saved sheet record stays JSON."""
    def convert(value):
        if isinstance(value, tuple):
            return [convert(item) for item in value]
        if isinstance(value, dict):
            return {key: convert(item) for key, item in value.items()}
        return value
    return convert({key: value for key, value in spec.items() if not key.startswith('_')})


def build_sheet(identity, feature_id, rules, location, spec):
    """A ``Sheet`` for one smooth or faceted cone. ``spec`` is ``cone_math.develop``."""
    placement = _placement(location)
    if spec['kind'] == 'cone':
        return _smooth_sheet(identity, feature_id, rules, placement, spec)
    return _faceted_sheet(identity, feature_id, rules, placement, spec)


def _smooth_sheet(identity, feature_id, rules, placement, spec):
    origin, x_axis, y_axis, z_axis = placement
    inner, outer = sorted(spec['sector_radius_mm'])
    bend = dict(id=feature_id, parent=None, child=None, edge_index=None, kind='cone',
                angle_deg=spec['sector_angle_deg'], radius_mm=max(spec['neutral_radius_mm']),
                k_factor=spec['k_factor'], allowance_mm=spec['large_arc_mm'], allowance_method='neutral_cone',
                width_mm=abs(outer - inner), straight_length_mm=0, sweep_deg=spec['sweep_deg'],
                sector_angle_deg=spec['sector_angle_deg'], sector_radius_mm=list(spec['sector_radius_mm']),
                inside_radius_mm=list(spec['inside_radius_mm']), height_mm=spec['height_mm'],
                seam=spec.get('seam', 'arc'), plane_offset_mm=spec.get('plane_offset_mm', 0.0),
                sin_alpha=spec.get('sin_alpha'), untrimmed_sector_angle_deg=spec.get('untrimmed_sector_angle_deg', spec['sector_angle_deg']),
                origin=list(origin), axis=list(x_axis), outward=list(y_axis), normal=list(z_axis),
                flat=frame(cq.Plane.XY()))
    sheet = Sheet(identity, rules, feature_id, {}, bends=[bend], reference=frame(
        cq.Plane(_vector(origin), xDir=_vector(x_axis), normal=_vector(z_axis))))
    sheet.development = _public_development(spec)
    return sheet


def _faceted_sheet(identity, feature_id, rules, placement, spec):
    layout = spec['_layout']
    panels = {}
    bends = []
    root = None
    for index, local in enumerate(layout['facets_local']):
        panel_id = feature_id if index == 0 else f'{feature_id}.{index + 1}'
        root = root or panel_id
        solid = tuple(_world(placement, point) for point in layout['solids'][index])
        flat_world = tuple((point[0], point[1], 0.0) for point in layout['facets_world'][index])
        local_face = local
        folded = _map_frame(local_face, solid)
        # The face is the inside surface. Material is extruded opposite the frame
        # normal, so that normal has to point toward the axis. Mirroring local Y
        # flips the normal; both frames are refit so the face stays on its quad.
        if folded.zDir.dot(_vector(_toward_axis(solid, placement))) < 0:
            local_face = tuple((point[0], -point[1]) for point in local)
            folded = _map_frame(local_face, solid)
        flat_plane = _map_frame(local_face, flat_world)
        panel = Panel(panel_id, _polygon(local_face), ['start', 'right', 'end', 'left'], frame(folded), frame(flat_plane))
        removal = layout.get('plane_removal')
        last = len(layout['facets_local']) - 1
        if removal and index in (0, last):
            clipped = _clip_end(local, layout['solids'][index], spec['plane_offset_mm'], spec['sweep_deg'], index == last)
            if local_face is not local:
                clipped = tuple((point[0], -point[1]) for point in clipped)
            panel.pattern = _polygon(clipped)
        panels[panel_id] = panel
    panel_ids = list(panels)
    for index, bend in enumerate(layout['bends_world']):
        parent, child = panel_ids[index], panel_ids[index + 1]
        corners = bend['corners']
        # The allowance rectangle is counter-clockwise in its frame, so the frame
        # normal has to point up (+Z). Reverse the edge when the raw corner order
        # would point the normal down; the shared edge is the same line.
        x_axis = _unit2d(_sub2(corners[1], corners[0]))
        y_axis = _unit2d(_sub2(corners[3], corners[0]))
        origin = corners[0]
        if x_axis[0] * y_axis[1] - x_axis[1] * y_axis[0] < 0:
            origin = corners[1]
            x_axis = _unit2d(_sub2(corners[0], corners[1]))
            y_axis = _unit2d(_sub2(corners[2], corners[1]))
        flat_plane = _plane_of((origin[0], origin[1], 0), (*x_axis, 0), (*y_axis, 0))
        start = layout['solids'][index][1]
        end = layout['solids'][index][2]
        origin = _world(placement, start)
        axis = _unit3d(_sub3(end, start))
        width = math.dist(start, end)
        outward, normal = _bend_directions(layout['solids'][index], placement)
        bends.append(dict(id=f'{feature_id}.b{index + 1}', parent=parent, child=child, edge_index=1,
                          kind='bend', angle_deg=bend['angle_deg'], radius_mm=layout['bend_radius_mm'],
                          k_factor=spec['k_factor'], allowance_mm=bend['allowance_mm'], allowance_method='k_factor',
                          width_mm=width, straight_length_mm=layout['face_height_mm'],
                          origin=list(origin), axis=list(axis), outward=list(outward), normal=list(normal),
                          flat=frame(flat_plane)))
    sheet = Sheet(identity, rules, root, panels, bends=bends, reference=frame(
        cq.Plane(_vector(placement[0]), xDir=_vector(placement[1]), normal=_vector(placement[3]))))
    sheet.development = _public_development(spec)
    return sheet


def _sub2(a, b):
    return (a[0] - b[0], a[1] - b[1])


def _unit2d(vector):
    scale = math.hypot(*vector)
    return (vector[0] / scale, vector[1] / scale)


def _sub3(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _unit3d(vector):
    scale = math.sqrt(sum(component * component for component in vector))
    return tuple(component / scale for component in vector)


def _toward_axis(quad, placement):
    """World-space direction from the facet center toward the cone axis."""
    origin, axis = placement[0], placement[1]
    center = tuple(sum(point[axis_index] for point in quad) / len(quad) for axis_index in range(3))
    relative = tuple(center[i] - origin[i] for i in range(3))
    along = sum(relative[i] * axis[i] for i in range(3))
    radial = tuple(relative[i] - axis[i] * along for i in range(3))
    return tuple(-component for component in radial)


def _bend_directions(quad, placement):
    """Inside-face tangent direction leaving the parent, and the parent normal."""
    world = [_world(placement, point) for point in quad]
    edge = _sub3(world[2], world[1])
    axis = _unit3d(edge)
    mid = tuple((world[1][i] + world[2][i]) / 2 for i in range(3))
    center = tuple(sum(point[i] for point in world) / 4 for i in range(3))
    inward = _sub3(center, mid)
    along = sum(inward[i] * axis[i] for i in range(3))
    inward = tuple(inward[i] - axis[i] * along for i in range(3))
    outward = _unit3d(tuple(-component for component in inward))
    span_a = _sub3(world[1], world[0])
    span_b = _sub3(world[3], world[0])
    normal = _unit3d((span_a[1] * span_b[2] - span_a[2] * span_b[1],
                      span_a[2] * span_b[0] - span_a[0] * span_b[2],
                      span_a[0] * span_b[1] - span_a[1] * span_b[0]))
    # Positive bends curl toward the sheet normal. Point it so the inside of the
    # bend faces the cone axis (the same side as the inward radial).
    toward_axis = _toward_axis(world, placement)
    if sum(normal[i] * toward_axis[i] for i in range(3)) < 0:
        normal = tuple(-component for component in normal)
    return outward, normal


def _clip_end(local, solid, offset, sweep_deg, end):
    """Clip one end panel to the plane seam. Points stay in the panel's local plane."""
    beta = math.radians(sweep_deg)

    def signed(point):
        if not end:
            return point[2] - offset
        return point[1] * math.sin(beta) - point[2] * math.cos(beta) - offset

    kept = []
    count = len(local)
    for index in range(count):
        start, stop = local[index], local[(index + 1) % count]
        start_solid, stop_solid = solid[index], solid[(index + 1) % count]
        ds, de = signed(start_solid), signed(stop_solid)
        if ds >= -TOL and de >= -TOL:
            kept.append(stop)
        elif ds >= -TOL and de < -TOL:
            kept.append(_blend(start, stop, ds / (ds - de)))
        elif ds < -TOL and de >= -TOL:
            kept.append(_blend(start, stop, ds / (ds - de)))
            kept.append(stop)
    if len(kept) < 3:
        fail('The weld gap is too large for this sweep.')
    return tuple(kept)


def _blend(start, stop, fraction):
    return (start[0] + fraction * (stop[0] - start[0]), start[1] + fraction * (stop[1] - start[1]))


def trim_placed_solid(shape, sheet):
    """Cut a placed faceted cone with the same two axial-parallel seam planes."""
    offset = sheet.development['plane_offset_mm']
    beta = math.radians(sheet.development['sweep_deg'])
    located = plane(sheet.reference)
    origin, y_axis, z_axis = located.origin, located.yDir, located.zDir
    size = 1.0e6

    def cut(solid, point, normal):
        cutter = cq.Workplane(cq.Plane(origin=point, normal=normal)).rect(size, size).extrude(-size)
        return solid.cut(cutter.val())

    shape = cut(shape, origin + z_axis * offset, z_axis)
    shape = cut(shape, origin + y_axis * (offset * math.sin(beta)) - z_axis * (offset * math.cos(beta)),
                y_axis * math.sin(beta) - z_axis * math.cos(beta))
    if shape.Volume() <= TOL:
        fail('The weld gap is too large for this sweep.')
    return shape


def sheet_from_call(identity, feature_id, rules, location, radius1, radius2, height, slant, angle,
                    radius_reference, weld_gap_in, facets, seam='arc'):
    try:
        spec = develop(radius1, radius2, rules.thickness, rules.k_factor, height=height, slant=slant, angle=angle,
                       radius_reference=radius_reference, weld_gap_in=weld_gap_in, facets=facets,
                       bend_radius=rules.radius, seam=seam)
    except ConeInputError as error:
        fail(str(error))
    return build_sheet(identity, feature_id, rules, location, spec)
