bl_info = {
    "name": "Parametric Plinth Generator v3.3",
    "author": "cyberresearch",
    "version": (3, 3, 0),
    "blender": (5, 0, 0),
    "location": "View3D > Sidebar > Plinth v3.3",
    "description": "Parametric plinth with slope, hollow (sealed/open), decorative half-round base trim, magnets, drains, and optional watertight remesh fallback.",
    "category": "Add Mesh",
}

import bpy
import bmesh
import math
from mathutils import Matrix, Vector

# -----------------------------
# Global names / constants
# -----------------------------
PROP_NAME = "plinthgen_props_v3_3"

COLL_NAME = "PlinthGen_v3_3"
OBJ_MAIN = "Plinth_Main_v3_3"
OBJ_CUTTERS = "Plinth_MagnetCutters_v3_3"
OBJ_HOLLOW = "Plinth_HollowCutter_v3_3"
OBJ_DRAINS = "Plinth_DrainCutters_v3_3"
OBJ_DRAINS_MAGNET_CENTER = "Plinth_MagnetCenterDrainCutters_v3_3"
OBJ_BASE_TRIM = "Plinth_BaseTrim_v3_3"
OBJ_PREVIEW = f"{OBJ_MAIN}_PREVIEW"

OVERSHOOT_MM = 1.0            # cutters extend below the base for reliable boolean subtraction
MAGNET_CLAMP_MARGIN_MM = 0.5  # keep at least this much material before cavity (sealed bottom)

# Small cleanup merge distance (mm)
MERGE_DIST_MM = 0.001

# Default voxel size used only when manifold guarantee triggers
DEFAULT_VOXEL_MM = 0.25
DEFAULT_DEGENERATE_FACE_AREA_MM2 = 1e-5
MM_PER_INCH = 25.4
MAX_PERIMETER_DETAIL_INSTANCES = 4096
ROPE_SAMPLES_PER_TWIST = 10


# -----------------------------
# Scene / cleanup utilities
# -----------------------------
def ensure_units_mm():
    scene = bpy.context.scene
    us = scene.unit_settings
    us.system = "METRIC"
    us.scale_length = 0.001  # 1 BU = 1mm
    us.length_unit = "MILLIMETERS"


def purge_orphans():
    try:
        bpy.ops.outliner.orphans_purge(do_recursive=True)
    except Exception:
        pass


def get_or_create_collection(name: str):
    coll = bpy.data.collections.get(name)
    if coll is None:
        coll = bpy.data.collections.new(name)
        bpy.context.scene.collection.children.link(coll)
    return coll


def delete_plinthgen_objects_only():
    """Delete only objects belonging to the PlinthGen collection (never touches user geometry)."""
    coll = bpy.data.collections.get(COLL_NAME)
    if coll:
        for obj in list(coll.objects):
            bpy.data.objects.remove(obj, do_unlink=True)


def clear_plinthgen_artifacts():
    """Remove our known objects and our collection (Blender 5 safe)."""
    for name in (OBJ_MAIN, OBJ_CUTTERS, OBJ_HOLLOW, OBJ_DRAINS, OBJ_DRAINS_MAGNET_CENTER, OBJ_BASE_TRIM, OBJ_PREVIEW):
        obj = bpy.data.objects.get(name)
        if obj:
            bpy.data.objects.remove(obj, do_unlink=True)

    coll = bpy.data.collections.get(COLL_NAME)
    if coll:
        # remove objects still in collection
        for obj in list(coll.objects):
            bpy.data.objects.remove(obj, do_unlink=True)

        # unlink from current scene
        scene_children = bpy.context.scene.collection.children
        for child in list(scene_children):
            if child == coll:
                scene_children.unlink(coll)
                break

        bpy.data.collections.remove(coll)

    purge_orphans()


# -----------------------------
# Geometry helpers
# -----------------------------
def ground_mesh_to_z0(mesh: bpy.types.Mesh):
    """Shift mesh so its minimum Z is exactly 0."""
    if not mesh or not mesh.vertices:
        return
    min_z = min(v.co.z for v in mesh.vertices)
    if abs(min_z) > 1e-9:
        for v in mesh.vertices:
            v.co.z -= min_z
    mesh.update()


def clamp_mesh_top_z(mesh: bpy.types.Mesh, target_top_z: float):
    """Shift mesh so its maximum Z becomes target_top_z."""
    if not mesh or not mesh.vertices:
        return
    max_z = max(v.co.z for v in mesh.vertices)
    dz = max_z - target_top_z
    if abs(dz) > 1e-9:
        for v in mesh.vertices:
            v.co.z -= dz
    mesh.update()


def slope_top_only(mesh: bpy.types.Mesh, base_top_mm: float, slope_delta_mm: float, axis: str, high_positive: bool):
    """Apply slope only to vertices on the top surface."""
    if not mesh or not mesh.vertices or abs(slope_delta_mm) < 1e-9:
        return

    ax = "X" if axis == "X" else "Y"

    coords = [v.co.x if ax == "X" else v.co.y for v in mesh.vertices]
    min_a, max_a = min(coords), max(coords)
    span = max(max_a - min_a, 1e-9)

    z_top = max(v.co.z for v in mesh.vertices)
    thr = max(0.01, 0.002 * max(1.0, base_top_mm))

    for v in mesh.vertices:
        if abs(v.co.z - z_top) <= thr:
            a = v.co.x if ax == "X" else v.co.y
            t = (a - min_a) / span
            t = max(0.0, min(1.0, t))
            if not high_positive:
                t = 1.0 - t
            v.co.z = base_top_mm + (slope_delta_mm * t)

    mesh.update()


def make_box_mesh(width_mm: float, length_mm: float, height_mm: float, mesh_name: str) -> bpy.types.Mesh:
    mesh = bpy.data.meshes.new(mesh_name)
    bm = bmesh.new()

    w = width_mm * 0.5
    l = length_mm * 0.5
    z0 = 0.0
    z1 = height_mm

    v0 = bm.verts.new((-w, -l, z0))
    v1 = bm.verts.new(( w, -l, z0))
    v2 = bm.verts.new(( w,  l, z0))
    v3 = bm.verts.new((-w,  l, z0))
    v4 = bm.verts.new((-w, -l, z1))
    v5 = bm.verts.new(( w, -l, z1))
    v6 = bm.verts.new(( w,  l, z1))
    v7 = bm.verts.new((-w,  l, z1))

    # Face winding: all outward-facing normals (right-hand rule)
    bm.faces.new((v3, v2, v1, v0))  # bottom (normal -Z)
    bm.faces.new((v4, v5, v6, v7))  # top    (normal +Z)
    bm.faces.new((v0, v1, v5, v4))  # front  (normal -Y)
    bm.faces.new((v2, v3, v7, v6))  # back   (normal +Y)
    bm.faces.new((v1, v2, v6, v5))  # right  (normal +X)
    bm.faces.new((v3, v0, v4, v7))  # left   (normal -X)

    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.normal_update()
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()
    return mesh


def make_cylinder_mesh(diameter_mm: float, height_mm: float, segments: int, mesh_name: str) -> bpy.types.Mesh:
    mesh = bpy.data.meshes.new(mesh_name)
    bm = bmesh.new()

    r = max(0.001, diameter_mm * 0.5)
    bmesh.ops.create_cone(
        bm,
        cap_ends=True,
        cap_tris=False,
        segments=max(12, int(segments)),
        radius1=r,
        radius2=r,
        depth=height_mm,
    )

    # create_cone centers on origin; shift so bottom at z=0
    for v in bm.verts:
        v.co.z += height_mm * 0.5

    bm.normal_update()
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()
    return mesh


def make_box_base_half_round_mesh(
    width_mm: float,
    length_mm: float,
    radius_mm: float,
    segments: int,
    mesh_name: str,
) -> bpy.types.Mesh:
    """Build a continuous half-round perimeter band with mitered box corners."""
    bm = bmesh.new()
    r = max(0.1, float(radius_mm))
    seg = max(8, int(segments))

    corners_xy = [
        Vector((-width_mm * 0.5, -length_mm * 0.5, 0.0)),
        Vector((width_mm * 0.5, -length_mm * 0.5, 0.0)),
        Vector((width_mm * 0.5, length_mm * 0.5, 0.0)),
        Vector((-width_mm * 0.5, length_mm * 0.5, 0.0)),
    ]  # CCW

    def offset_corners(offset_d: float):
        pts = []
        for i, curr in enumerate(corners_xy):
            prev = corners_xy[(i - 1) % len(corners_xy)]
            nxt = corners_xy[(i + 1) % len(corners_xy)]
            t_prev = (curr - prev).normalized()
            t_next = (nxt - curr).normalized()
            n_prev = Vector((t_prev.y, -t_prev.x, 0.0))
            n_next = Vector((t_next.y, -t_next.x, 0.0))
            m = n_prev + n_next
            if m.length <= 1e-9:
                m = n_next.copy()
            m.normalize()
            denom = max(1e-6, m.dot(n_prev))
            p = curr + (m * (offset_d / denom))
            pts.append((p.x, p.y))
        return pts

    loops = []
    # Half-circle profile in (offset, z): z from 0..2r and offset from 0..r.
    for k in range(seg + 1):
        a = (-math.pi * 0.5) + (math.pi * k / seg)
        d = r * math.cos(a)
        z = r + (r * math.sin(a))
        loop_xy = offset_corners(d)
        loop = [bm.verts.new((x, y, z)) for (x, y) in loop_xy]
        loops.append(loop)

    def bridge_loops(loop_a, loop_b):
        n = len(loop_a)
        for i in range(n):
            i2 = (i + 1) % n
            v1 = loop_a[i]
            v2 = loop_a[i2]
            v3 = loop_b[i2]
            v4 = loop_b[i]
            try:
                bm.faces.new((v1, v2, v3, v4))
            except ValueError:
                pass

    # Outer curved surface.
    for k in range(seg):
        bridge_loops(loops[k], loops[k + 1])
    # Close profile against wall plane (straight segment between arc endpoints).
    bridge_loops(loops[-1], loops[0])

    return bm_to_mesh(bm, mesh_name)


def make_cyl_base_half_round_mesh(
    major_radius_mm: float,
    minor_radius_mm: float,
    major_segments: int,
    minor_segments: int,
    mesh_name: str,
) -> bpy.types.Mesh:
    """Build a torus ring for cylinder base trim."""
    mesh = bpy.data.meshes.new(mesh_name)
    bm = bmesh.new()

    major_r = max(0.1, float(major_radius_mm))
    minor_r = max(0.1, min(float(minor_radius_mm), max(0.1, major_r - 0.1)))
    seg_major = max(24, int(major_segments))
    seg_minor = max(12, int(minor_segments))

    rings = []
    for i in range(seg_major):
        a = (2.0 * math.pi * i) / seg_major
        ca = math.cos(a)
        sa = math.sin(a)
        ring = []
        for j in range(seg_minor):
            b = (2.0 * math.pi * j) / seg_minor
            cb = math.cos(b)
            sb = math.sin(b)
            rr = major_r + (minor_r * cb)
            x = rr * ca
            y = rr * sa
            z = minor_r + (minor_r * sb)
            ring.append(bm.verts.new((x, y, z)))
        rings.append(ring)

    for i in range(seg_major):
        i2 = (i + 1) % seg_major
        for j in range(seg_minor):
            j2 = (j + 1) % seg_minor
            v1 = rings[i][j]
            v2 = rings[i2][j]
            v3 = rings[i2][j2]
            v4 = rings[i][j2]
            try:
                bm.faces.new((v1, v2, v3, v4))
            except ValueError:
                pass

    bm.normal_update()
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()
    return mesh


def translate_mesh(mesh: bpy.types.Mesh, vec: Vector):
    for v in mesh.vertices:
        v.co += vec
    mesh.update()


def clamp_instance_count(count: int, minimum: int = 0, maximum: int = MAX_PERIMETER_DETAIL_INSTANCES) -> int:
    return max(int(minimum), min(int(count), int(maximum)))


def estimate_perimeter_instance_count(
    shape: str,
    width_mm: float,
    length_mm: float,
    diameter_mm: float,
    spacing_mm: float,
    minimum: int,
) -> int:
    spacing = max(1e-6, float(spacing_mm))
    if shape == "BOX":
        perimeter = 2.0 * (max(0.0, float(width_mm)) + max(0.0, float(length_mm)))
    else:
        perimeter = math.pi * max(0.0, float(diameter_mm))
    return max(int(minimum), int(perimeter / spacing))


def rope_perimeter_mm(shape: str, width_mm: float, length_mm: float, diameter_mm: float, rope_dia_mm: float) -> float:
    r_total = max(0.1, float(rope_dia_mm) * 0.5)
    base_offset = r_total * 0.5
    if shape == "BOX":
        return 2.0 * ((max(0.0, float(width_mm)) + (2.0 * base_offset)) + (max(0.0, float(length_mm)) + (2.0 * base_offset)))
    rr = max(0.001, (max(0.0, float(diameter_mm)) * 0.5) + base_offset)
    return 2.0 * math.pi * rr


def rope_sample_count(perimeter_mm: float, rope_pitch_mm: float) -> int:
    pitch = max(0.5, float(rope_pitch_mm))
    twists = max(1.0, float(perimeter_mm) / pitch)
    return clamp_instance_count(max(24, int(twists * ROPE_SAMPLES_PER_TWIST)), minimum=24)


def rect_perimeter_point_and_normal(hx: float, hy: float, d: float):
    hx = max(0.001, float(hx))
    hy = max(0.001, float(hy))
    per = 4.0 * (hx + hy)
    d = d % per
    segx = 2.0 * hx
    segy = 2.0 * hy
    if d < segx:
        return (hx - d, -hy), Vector((0.0, -1.0, 0.0))
    if d < segx + segy:
        d2 = d - segx
        return (-hx, -hy + d2), Vector((-1.0, 0.0, 0.0))
    if d < segx + segy + segx:
        d2 = d - (segx + segy)
        return (-hx + d2, hy), Vector((0.0, 1.0, 0.0))
    d2 = d - (segx + segy + segx)
    return (hx, hy - d2), Vector((1.0, 0.0, 0.0))


def rect_perimeter_points_from_extents(hx: float, hy: float, count: int):
    count = clamp_instance_count(count, minimum=0)
    if count <= 0:
        return []
    hx = max(0.001, float(hx))
    hy = max(0.001, float(hy))
    per = 4.0 * (hx + hy)
    step = per / count
    start = step * 0.5
    pts = []

    def point_at(d):
        d = d % per
        segx = 2.0 * hx
        segy = 2.0 * hy
        if d < segx:
            return (hx - d, -hy)
        if d < segx + segy:
            d2 = d - segx
            return (-hx, -hy + d2)
        if d < segx + segy + segx:
            d2 = d - (segx + segy)
            return (-hx + d2, hy)
        d2 = d - (segx + segy + segx)
        return (hx, hy - d2)

    for i in range(count):
        pts.append(point_at(start + (i * step)))
    return pts


def bm_add_box(bm: bmesh.types.BMesh, sx: float, sy: float, sz: float, center, rot_z_rad: float = 0.0):
    res = bmesh.ops.create_cube(bm, size=1.0)
    verts = list(res["verts"])
    bmesh.ops.scale(bm, verts=verts, vec=Vector((max(0.001, sx) * 0.5, max(0.001, sy) * 0.5, max(0.001, sz) * 0.5)))
    if abs(rot_z_rad) > 1e-9:
        rot = Matrix.Rotation(rot_z_rad, 3, "Z")
        bmesh.ops.rotate(bm, verts=verts, cent=Vector((0.0, 0.0, 0.0)), matrix=rot)
    bmesh.ops.translate(bm, verts=verts, vec=Vector(center))


def bm_add_cylinder_z(bm: bmesh.types.BMesh, radius: float, height: float, center, segments: int):
    res = bmesh.ops.create_cone(
        bm,
        cap_ends=True,
        cap_tris=False,
        segments=max(12, int(segments)),
        radius1=max(0.001, float(radius)),
        radius2=max(0.001, float(radius)),
        depth=max(0.001, float(height)),
    )
    verts = list(res["verts"])
    bmesh.ops.translate(bm, verts=verts, vec=Vector(center))


def bm_add_cylinder_between_points(bm: bmesh.types.BMesh, radius: float, p0, p1, segments: int):
    p0v = Vector(p0)
    p1v = Vector(p1)
    d = p1v - p0v
    length = d.length
    if length <= 1e-6:
        return

    res = bmesh.ops.create_cone(
        bm,
        cap_ends=True,
        cap_tris=False,
        segments=max(10, int(segments)),
        radius1=max(0.001, float(radius)),
        radius2=max(0.001, float(radius)),
        depth=length,
    )
    verts = list(res["verts"])

    z_axis = Vector((0.0, 0.0, 1.0))
    dir_n = d.normalized()
    if (dir_n - z_axis).length > 1e-9:
        rot = z_axis.rotation_difference(dir_n).to_matrix()
        bmesh.ops.rotate(bm, verts=verts, cent=Vector((0.0, 0.0, 0.0)), matrix=rot)

    bmesh.ops.translate(bm, verts=verts, vec=((p0v + p1v) * 0.5))


def bm_add_sphere(bm: bmesh.types.BMesh, radius: float, center, u_segments: int = 24, v_segments: int = 12, scale_xyz=(1.0, 1.0, 1.0)):
    res = bmesh.ops.create_uvsphere(
        bm,
        u_segments=max(8, int(u_segments)),
        v_segments=max(6, int(v_segments)),
        radius=max(0.001, float(radius)),
    )
    verts = list(res["verts"])
    sx, sy, sz = scale_xyz
    if abs(sx - 1.0) > 1e-9 or abs(sy - 1.0) > 1e-9 or abs(sz - 1.0) > 1e-9:
        bmesh.ops.scale(bm, verts=verts, vec=Vector((sx, sy, sz)))
    bmesh.ops.translate(bm, verts=verts, vec=Vector(center))


def bm_to_mesh(bm: bmesh.types.BMesh, mesh_name: str) -> bpy.types.Mesh:
    mesh = bpy.data.meshes.new(mesh_name)
    bm.normal_update()
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()
    return mesh


def make_stepped_layers_mesh(
    shape: str,
    width_mm: float,
    length_mm: float,
    diameter_mm: float,
    height_mm: float,
    steps_count: int,
    step_height_mm: float,
    step_offset_mm: float,
    at_top: bool,
    segments: int,
    mesh_name: str,
) -> bpy.types.Mesh:
    bm = bmesh.new()
    n = max(1, int(steps_count))
    h = max(0.1, float(step_height_mm))
    off = max(0.0, float(step_offset_mm))
    for i in range(n):
        level = i + 1
        zc = (height_mm - ((i + 0.5) * h)) if at_top else ((i + 0.5) * h)
        if shape == "BOX":
            w = width_mm + (2.0 * off * level)
            l = length_mm + (2.0 * off * level)
            bm_add_box(bm, w, l, h, (0.0, 0.0, zc))
        else:
            d = diameter_mm + (2.0 * off * level)
            bm_add_cylinder_z(bm, d * 0.5, h, (0.0, 0.0, zc), segments=max(24, int(segments)))
    return bm_to_mesh(bm, mesh_name)


def make_vertical_flute_cutters_mesh(
    shape: str,
    width_mm: float,
    length_mm: float,
    diameter_mm: float,
    height_mm: float,
    flute_count: int,
    flute_width_mm: float,
    flute_depth_mm: float,
    z_margin_mm: float,
    segments: int,
    mesh_name: str,
) -> bpy.types.Mesh:
    bm = bmesh.new()
    r = max(0.1, flute_width_mm * 0.5)
    depth = max(0.05, float(flute_depth_mm))
    h = max(0.2, height_mm - (2.0 * max(0.0, z_margin_mm)))
    zc = max(0.1, z_margin_mm) + (h * 0.5)
    n = max(1, int(flute_count))
    pts = []
    if shape == "BOX":
        hx = (width_mm * 0.5) + r - depth
        hy = (length_mm * 0.5) + r - depth
        pts = rect_perimeter_points_from_extents(hx, hy, n)
    else:
        rc = (diameter_mm * 0.5) + r - depth
        for i in range(n):
            a = (2.0 * math.pi * i) / n
            pts.append((rc * math.cos(a), rc * math.sin(a)))
    for (x, y) in pts:
        bm_add_cylinder_z(bm, r, h, (x, y, zc), segments=max(16, int(segments)))
    return bm_to_mesh(bm, mesh_name)


def make_recessed_panels_cutters_mesh(
    shape: str,
    width_mm: float,
    length_mm: float,
    diameter_mm: float,
    height_mm: float,
    panel_depth_mm: float,
    panel_border_mm: float,
    panel_height_ratio: float,
    panel_count_cyl: int,
    segments: int,
    mesh_name: str,
) -> bpy.types.Mesh:
    bm = bmesh.new()
    depth = max(0.1, float(panel_depth_mm))
    border = max(0.0, float(panel_border_mm))
    panel_h = max(0.5, height_mm * max(0.1, min(0.95, panel_height_ratio)))
    zc = height_mm * 0.5
    if shape == "BOX":
        pw = max(0.5, width_mm - (2.0 * border))
        pl = max(0.5, length_mm - (2.0 * border))
        bm_add_box(bm, pw, depth * 2.0, panel_h, (0.0, (length_mm * 0.5) - depth, zc))
        bm_add_box(bm, pw, depth * 2.0, panel_h, (0.0, -(length_mm * 0.5) + depth, zc))
        bm_add_box(bm, depth * 2.0, pl, panel_h, ((width_mm * 0.5) - depth, 0.0, zc))
        bm_add_box(bm, depth * 2.0, pl, panel_h, (-(width_mm * 0.5) + depth, 0.0, zc))
    else:
        n = max(3, int(panel_count_cyl))
        panel_w = max(0.5, (math.pi * diameter_mm * 0.45) / n)
        rr = (diameter_mm * 0.5) + (panel_w * 0.5) - depth
        for i in range(n):
            a = (2.0 * math.pi * i) / n
            bm_add_cylinder_z(
                bm,
                panel_w * 0.5,
                panel_h,
                (rr * math.cos(a), rr * math.sin(a), zc),
                segments=max(12, int(segments)),
            )
    return bm_to_mesh(bm, mesh_name)


def make_bead_border_mesh(
    shape: str,
    width_mm: float,
    length_mm: float,
    diameter_mm: float,
    height_mm: float,
    bead_size_mm: float,
    bead_spacing_mm: float,
    bead_rows: int,
    at_top: bool,
    mesh_name: str,
) -> bpy.types.Mesh:
    bm = bmesh.new()
    r = max(0.1, bead_size_mm * 0.5)
    spacing = max(0.5, float(bead_spacing_mm))
    rows = max(1, int(bead_rows))
    for row in range(rows):
        z = (height_mm - r - (row * bead_size_mm * 0.9)) if at_top else (r + (row * bead_size_mm * 0.9))
        # Clamp z so beads never go below 0 or above height
        z = max(r, min(height_mm - r, z))
        if shape == "BOX":
            per = 2.0 * (width_mm + length_mm)
            n = clamp_instance_count(max(4, int(per / spacing)), minimum=4)
            pts = rect_perimeter_points_from_extents((width_mm * 0.5) + (r * 0.4), (length_mm * 0.5) + (r * 0.4), n)
            for (x, y) in pts:
                bm_add_sphere(bm, r, (x, y, z), u_segments=16, v_segments=8)
        else:
            per = math.pi * diameter_mm
            n = clamp_instance_count(max(6, int(per / spacing)), minimum=6)
            rr = (diameter_mm * 0.5) + (r * 0.4)
            for i in range(n):
                a = (2.0 * math.pi * i) / n
                bm_add_sphere(bm, r, (rr * math.cos(a), rr * math.sin(a), z), u_segments=16, v_segments=8)
    return bm_to_mesh(bm, mesh_name)


def make_rope_band_mesh(
    shape: str,
    width_mm: float,
    length_mm: float,
    diameter_mm: float,
    height_mm: float,
    rope_dia_mm: float,
    rope_pitch_mm: float,
    at_top: bool,
    mesh_name: str,
) -> bpy.types.Mesh:
    bm = bmesh.new()
    r_total = max(0.1, rope_dia_mm * 0.5)
    strand_r = max(0.05, r_total * 0.58)
    strand_amp = max(0.01, r_total * 0.42)
    base_offset = r_total * 0.5
    zc = (height_mm - r_total) if at_top else r_total

    per = rope_perimeter_mm(shape, width_mm, length_mm, diameter_mm, rope_dia_mm)
    n = rope_sample_count(per, rope_pitch_mm)
    desired_twists = max(1.0, per / max(0.5, float(rope_pitch_mm)))
    actual_twists = max(1, int(round(desired_twists)))
    twist_factor = 2.0 * math.pi * float(actual_twists)

    base_points = []
    base_normals = []

    if shape == "BOX":
        hx = (width_mm * 0.5) + base_offset
        hy = (length_mm * 0.5) + base_offset
        step = per / n
        start = step * 0.5
        for i in range(n):
            (x, y), nrm = rect_perimeter_point_and_normal(hx, hy, start + (i * step))
            base_points.append(Vector((x, y, zc)))
            base_normals.append(nrm)
    else:
        rr = (diameter_mm * 0.5) + base_offset
        for i in range(n):
            a = (2.0 * math.pi * i) / n
            nx = math.cos(a)
            ny = math.sin(a)
            base_points.append(Vector((rr * nx, rr * ny, zc)))
            base_normals.append(Vector((nx, ny, 0.0)))

    up = Vector((0.0, 0.0, 1.0))
    strand0 = []
    strand1 = []

    for i, base in enumerate(base_points):
        t = i / n
        phase = twist_factor * t
        nrm = base_normals[i]
        offset0 = (nrm * (strand_amp * math.cos(phase))) + (up * (strand_amp * math.sin(phase)))
        offset1 = (nrm * (strand_amp * math.cos(phase + math.pi))) + (up * (strand_amp * math.sin(phase + math.pi)))
        strand0.append(base + offset0)
        strand1.append(base + offset1)

    cyl_segments = 12
    for i in range(n):
        i2 = (i + 1) % n
        bm_add_cylinder_between_points(bm, strand_r, strand0[i], strand0[i2], segments=cyl_segments)
        bm_add_cylinder_between_points(bm, strand_r, strand1[i], strand1[i2], segments=cyl_segments)
    return bm_to_mesh(bm, mesh_name)


def make_dentil_course_mesh(
    shape: str,
    width_mm: float,
    length_mm: float,
    diameter_mm: float,
    height_mm: float,
    dentil_w_mm: float,
    dentil_d_mm: float,
    dentil_h_mm: float,
    dentil_spacing_mm: float,
    at_top: bool,
    mesh_name: str,
) -> bpy.types.Mesh:
    bm = bmesh.new()
    w = max(0.2, float(dentil_w_mm))
    d = max(0.2, float(dentil_d_mm))
    h = max(0.2, float(dentil_h_mm))
    spacing = max(0.3, float(dentil_spacing_mm))
    zc = (height_mm - (h * 0.5)) if at_top else (h * 0.5)
    if shape == "BOX":
        per = 2.0 * (width_mm + length_mm)
        n = clamp_instance_count(max(4, int(per / max(spacing, w))), minimum=4)
        pts = rect_perimeter_points_from_extents((width_mm * 0.5) + (d * 0.5), (length_mm * 0.5) + (d * 0.5), n)
        for (x, y) in pts:
            bm_add_box(bm, w, w, h, (x, y, zc))
    else:
        per = math.pi * diameter_mm
        n = clamp_instance_count(max(6, int(per / max(spacing, w))), minimum=6)
        rr = (diameter_mm * 0.5) + (d * 0.5)
        for i in range(n):
            a = (2.0 * math.pi * i) / n
            x = rr * math.cos(a)
            y = rr * math.sin(a)
            bm_add_box(bm, w, d, h, (x, y, zc), rot_z_rad=a)
    return bm_to_mesh(bm, mesh_name)


def make_scallop_cutters_mesh(
    shape: str,
    width_mm: float,
    length_mm: float,
    diameter_mm: float,
    scallop_count: int,
    scallop_radius_mm: float,
    scallop_depth_mm: float,
    scallop_z_mm: float,
    mesh_name: str,
) -> bpy.types.Mesh:
    bm = bmesh.new()
    n = max(3, int(scallop_count))
    r = max(0.1, float(scallop_radius_mm))
    depth = max(0.05, float(scallop_depth_mm))
    z = max(r * 0.5, float(scallop_z_mm))
    pts = []
    if shape == "BOX":
        hx = (width_mm * 0.5) + r - depth
        hy = (length_mm * 0.5) + r - depth
        pts = rect_perimeter_points_from_extents(hx, hy, n)
    else:
        rr = (diameter_mm * 0.5) + r - depth
        for i in range(n):
            a = (2.0 * math.pi * i) / n
            pts.append((rr * math.cos(a), rr * math.sin(a)))
    for (x, y) in pts:
        bm_add_sphere(bm, r, (x, y, z), u_segments=16, v_segments=10)
    return bm_to_mesh(bm, mesh_name)


def make_bosses_mesh(
    shape: str,
    width_mm: float,
    length_mm: float,
    diameter_mm: float,
    boss_shape: str,
    boss_size_mm: float,
    boss_relief_mm: float,
    boss_inset_mm: float,
    boss_count_cyl: int,
    boss_z_ratio: float,
    height_mm: float,
    mesh_name: str,
) -> bpy.types.Mesh:
    bm = bmesh.new()
    r = max(0.1, float(boss_size_mm) * 0.5)
    relief = max(0.1, float(boss_relief_mm))
    z = max(r * 0.5, min(height_mm - (r * 0.5), height_mm * max(0.05, min(0.95, boss_z_ratio))))
    if shape == "BOX":
        inset = max(0.0, float(boss_inset_mm))
        hx = max(0.001, (width_mm * 0.5) - inset)
        hy = max(0.001, (length_mm * 0.5) - inset)
        pts = [(-hx, -hy), (hx, -hy), (hx, hy), (-hx, hy)]
    else:
        n = max(3, int(boss_count_cyl))
        rr = max(0.001, (diameter_mm * 0.5) - max(0.0, float(boss_inset_mm)))
        pts = []
        for i in range(n):
            a = (2.0 * math.pi * i) / n
            pts.append((rr * math.cos(a), rr * math.sin(a)))

    for (x, y) in pts:
        if boss_shape == "DISC":
            bm_add_sphere(bm, r, (x, y, z), u_segments=16, v_segments=10, scale_xyz=(1.0, 1.0, max(0.1, relief / (2.0 * r))))
        else:
            bm_add_sphere(bm, r, (x, y, z), u_segments=16, v_segments=10)
    return bm_to_mesh(bm, mesh_name)


def make_nameplate_cutter_mesh(
    shape: str,
    width_mm: float,
    length_mm: float,
    diameter_mm: float,
    height_mm: float,
    plate_w_mm: float,
    plate_h_mm: float,
    plate_d_mm: float,
    plate_side: str,
    plate_z_ratio: float,
    mesh_name: str,
) -> bpy.types.Mesh:
    bm = bmesh.new()
    pw = max(0.5, float(plate_w_mm))
    ph = max(0.5, float(plate_h_mm))
    pd = max(0.1, float(plate_d_mm))
    zc = max(ph * 0.5, min(height_mm - (ph * 0.5), height_mm * max(0.05, min(0.95, plate_z_ratio))))

    if shape == "BOX":
        if plate_side == "POS_X":
            bm_add_box(bm, pd * 2.0, pw, ph, ((width_mm * 0.5) - pd, 0.0, zc))
        elif plate_side == "NEG_X":
            bm_add_box(bm, pd * 2.0, pw, ph, (-(width_mm * 0.5) + pd, 0.0, zc))
        elif plate_side == "NEG_Y":
            bm_add_box(bm, pw, pd * 2.0, ph, (0.0, -(length_mm * 0.5) + pd, zc))
        else:
            bm_add_box(bm, pw, pd * 2.0, ph, (0.0, (length_mm * 0.5) - pd, zc))
    else:
        rr = max(0.5, (diameter_mm * 0.5) - pd)
        bm_add_box(bm, pw, pd * 2.0, ph, (0.0, rr, zc))
    return bm_to_mesh(bm, mesh_name)


def make_feet_mesh(
    shape: str,
    width_mm: float,
    length_mm: float,
    diameter_mm: float,
    feet_type: str,
    feet_radius_mm: float,
    feet_height_mm: float,
    feet_inset_mm: float,
    feet_count_cyl: int,
    mesh_name: str,
) -> bpy.types.Mesh:
    bm = bmesh.new()
    r = max(0.1, float(feet_radius_mm))
    h = max(0.1, float(feet_height_mm))
    inset = max(0.0, float(feet_inset_mm))

    if shape == "BOX":
        hx = max(0.001, (width_mm * 0.5) - inset)
        hy = max(0.001, (length_mm * 0.5) - inset)
        pts = [(-hx, -hy), (hx, -hy), (hx, hy), (-hx, hy)]
    else:
        n = max(3, int(feet_count_cyl))
        rr = max(0.001, (diameter_mm * 0.5) - inset)
        pts = []
        for i in range(n):
            a = (2.0 * math.pi * i) / n
            pts.append((rr * math.cos(a), rr * math.sin(a)))

    for (x, y) in pts:
        if feet_type == "BUN":
            bm_add_sphere(bm, r, (x, y, r * 0.8), u_segments=16, v_segments=10)
        else:
            bm_add_cylinder_z(bm, r, h, (x, y, h * 0.5), segments=20)
    return bm_to_mesh(bm, mesh_name)


def apply_surface_texture_stamp(
    mesh: bpy.types.Mesh,
    shape: str,
    strength_mm: float,
    scale_mm: float,
    seed: int,
    zone: str,
    width_mm: float,
    length_mm: float,
):
    s = float(strength_mm)
    if abs(s) < 1e-9:
        return
    sc = max(0.1, float(scale_mm))
    if not mesh or not mesh.vertices:
        return

    z_min = min(v.co.z for v in mesh.vertices)
    z_max = max(v.co.z for v in mesh.vertices)
    z_pad = max(0.2, 0.02 * max(1.0, z_max - z_min))
    x_den = max(0.001, width_mm * 0.5)
    y_den = max(0.001, length_mm * 0.5)

    for v in mesh.vertices:
        if zone == "SIDES" and (v.co.z <= z_min + z_pad or v.co.z >= z_max - z_pad):
            continue

        n1 = math.sin((v.co.x + (seed * 3.17)) / sc)
        n2 = math.sin((v.co.y - (seed * 1.73)) / (sc * 1.31))
        n3 = math.sin((v.co.z + (seed * 0.91)) / (sc * 0.73))
        noise_val = (n1 + n2 + n3) / 3.0
        disp = s * noise_val

        if shape == "CYL":
            d = Vector((v.co.x, v.co.y, 0.0))
            if d.length <= 1e-9:
                continue
            d.normalize()
        else:
            nx = abs(v.co.x) / x_den
            ny = abs(v.co.y) / y_den
            if nx >= ny:
                d = Vector((1.0 if v.co.x >= 0.0 else -1.0, 0.0, 0.0))
            else:
                d = Vector((0.0, 1.0 if v.co.y >= 0.0 else -1.0, 0.0))
        v.co += d * disp
    mesh.update()


# -----------------------------
# Hollow cutter builders (open or sealed bottom)
# -----------------------------
def make_hollow_box_cutter_mesh(
    width_mm: float,
    length_mm: float,
    height_mm: float,
    wall_thickness_mm: float,
    top_thickness_mm: float,
    sealed_bottom: bool,
    bottom_thickness_mm: float,
    slope_enabled: bool,
    slope_delta_mm: float,
    slope_axis: str,
    high_positive: bool,
) -> bpy.types.Mesh:
    inner_w = max(0.001, width_mm - 2.0 * wall_thickness_mm)
    inner_l = max(0.001, length_mm - 2.0 * wall_thickness_mm)

    target_top = max(0.001, height_mm - top_thickness_mm)
    mesh = make_box_mesh(inner_w, inner_l, target_top, "Plinth_HollowBoxMesh_v3_3")

    if slope_enabled and slope_delta_mm > 0.0:
        slope_top_only(mesh, target_top, slope_delta_mm, slope_axis, high_positive)

    # Keep cutter top at or below the inner roof height.
    clamp_mesh_top_z(mesh, target_top)

    # Place vertically: open bottom extends below 0; sealed starts at bottom thickness
    z_min = min(v.co.z for v in mesh.vertices)
    if sealed_bottom:
        target_bottom = max(0.0, bottom_thickness_mm)
    else:
        target_bottom = -OVERSHOOT_MM
    dz = target_bottom - z_min
    for v in mesh.vertices:
        v.co.z += dz
    mesh.update()
    return mesh


def make_hollow_cyl_cutter_mesh(
    diameter_mm: float,
    height_mm: float,
    wall_thickness_mm: float,
    top_thickness_mm: float,
    sealed_bottom: bool,
    bottom_thickness_mm: float,
    slope_enabled: bool,
    slope_delta_mm: float,
    slope_axis: str,
    high_positive: bool,
    segments: int,
) -> bpy.types.Mesh:
    inner_d = max(0.001, diameter_mm - 2.0 * wall_thickness_mm)
    target_top = max(0.001, height_mm - top_thickness_mm)

    mesh = make_cylinder_mesh(inner_d, target_top, segments, "Plinth_HollowCylMesh_v3_3")

    if slope_enabled and slope_delta_mm > 0.0:
        slope_top_only(mesh, target_top, slope_delta_mm, slope_axis, high_positive)

    clamp_mesh_top_z(mesh, target_top)

    z_min = min(v.co.z for v in mesh.vertices)
    if sealed_bottom:
        target_bottom = max(0.0, bottom_thickness_mm)
    else:
        target_bottom = -OVERSHOOT_MM
    dz = target_bottom - z_min
    for v in mesh.vertices:
        v.co.z += dz
    mesh.update()
    return mesh


# -----------------------------
# Point utilities for stable cutter placement.
# Deduplicate and separate points to avoid overlapping cutters.
# -----------------------------
def uniq_points(points, grid_mm=0.001):
    """Deduplicate points by snapping to a tiny grid."""
    seen = set()
    out = []
    for (x, y) in points:
        kx = int(round(x / grid_mm))
        ky = int(round(y / grid_mm))
        key = (kx, ky)
        if key not in seen:
            seen.add(key)
            out.append((x, y))
    return out


def filter_points_by_min_distance(points, avoid_points, min_dist):
    """Remove points that are too close to avoid_points."""
    if not avoid_points:
        return list(points)
    out = []
    min2 = min_dist * min_dist
    for (x, y) in points:
        ok = True
        for (ax, ay) in avoid_points:
            dx = x - ax
            dy = y - ay
            if (dx * dx + dy * dy) < min2:
                ok = False
                break
        if ok:
            out.append((x, y))
    return out


# -----------------------------
# Magnet placement
# -----------------------------
def rect_perimeter_centered_points(width_mm, length_mm, inset_mm, radius_mm, count):
    count = max(0, int(count))
    if count == 0:
        return []
    if count == 1:
        return [(0.0, 0.0)]

    hx = max(0.001, width_mm * 0.5 - inset_mm - radius_mm)
    hy = max(0.001, length_mm * 0.5 - inset_mm - radius_mm)
    per = 4.0 * (hx + hy)
    if per <= 1e-9:
        return []

    step = per / count
    start = step * 0.5
    pts = []

    def point_at(d):
        d = d % per
        seg1 = 2.0 * hx
        seg2 = 2.0 * hy
        if d < seg1:
            x = hx - d
            y = -hy
        elif d < seg1 + seg2:
            d2 = d - seg1
            x = -hx
            y = -hy + d2
        elif d < seg1 + seg2 + seg1:
            d2 = d - (seg1 + seg2)
            x = -hx + d2
            y = hy
        else:
            d2 = d - (seg1 + seg2 + seg1)
            x = hx
            y = hy - d2
        return (x, y)

    for i in range(count):
        pts.append(point_at(start + i * step))
    return pts


def rect_corner_points(width_mm, length_mm, inset_mm, radius_mm, count):
    count = max(0, int(count))
    if count == 0:
        return []
    if count == 1:
        return [(0.0, 0.0)]

    hx = max(0.001, width_mm * 0.5 - inset_mm - radius_mm)
    hy = max(0.001, length_mm * 0.5 - inset_mm - radius_mm)
    corners = [(-hx, -hy), (hx, -hy), (hx, hy), (-hx, hy)]
    if count <= 4:
        return corners[:count]
    rest = rect_perimeter_centered_points(width_mm, length_mm, inset_mm, radius_mm, count - 4)
    return corners + rest


def circle_ring_points(diameter_mm, inset_mm, radius_mm, count):
    count = max(0, int(count))
    if count == 0:
        return []
    if count == 1:
        return [(0.0, 0.0)]
    r_outer = diameter_mm * 0.5
    r_place = max(0.001, r_outer - inset_mm - radius_mm)
    pts = []
    for i in range(count):
        ang = (2.0 * math.pi * i) / count
        pts.append((r_place * math.cos(ang), r_place * math.sin(ang)))
    return pts


# -----------------------------
# Cutter mesh builder (single mesh of cutters)
# -----------------------------
def build_vertical_cylinder_cutters_mesh(
    radius_mm: float,
    depth_mm: float,
    positions_xy,
    mesh_name: str,
    segments=48,
    overshoot_mm=OVERSHOOT_MM
) -> bpy.types.Mesh:
    """
    Build all cutters into one mesh.
    Each cutter spans z=-overshoot_mm .. z=depth_mm.
    """
    mesh = bpy.data.meshes.new(mesh_name)
    bm = bmesh.new()

    depth_total = max(0.001, depth_mm + overshoot_mm)
    shift_z = (-overshoot_mm) - (-depth_total * 0.5)

    for (x, y) in positions_xy:
        res = bmesh.ops.create_cone(
            bm,
            cap_ends=True,
            cap_tris=False,
            segments=max(12, segments),
            radius1=max(0.001, radius_mm),
            radius2=max(0.001, radius_mm),
            depth=depth_total,
        )
        verts = [v for v in res["verts"]]
        bmesh.ops.translate(bm, verts=verts, vec=Vector((x, y, shift_z)))

    bm.normal_update()
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()
    return mesh


def add_boolean_modifier(target_obj: bpy.types.Object, cutter_obj: bpy.types.Object, name: str):
    mod = target_obj.modifiers.new(name=name, type="BOOLEAN")
    mod.operation = "DIFFERENCE"
    mod.solver = "EXACT"
    mod.object = cutter_obj
    return mod


def add_boolean_union_modifier(target_obj: bpy.types.Object, union_obj: bpy.types.Object, name: str):
    mod = target_obj.modifiers.new(name=name, type="BOOLEAN")
    mod.operation = "UNION"
    mod.solver = "EXACT"
    mod.object = union_obj
    return mod


def move_modifier_to_end(obj: bpy.types.Object, modifier_name: str):
    idx = obj.modifiers.find(modifier_name)
    if idx < 0:
        return
    last = len(obj.modifiers) - 1
    if idx != last:
        obj.modifiers.move(idx, last)


def add_helper_boolean_object(
    coll: bpy.types.Collection,
    mesh: bpy.types.Mesh,
    obj_name: str,
    show_cutters: bool,
) -> bpy.types.Object:
    obj = bpy.data.objects.new(obj_name, mesh)
    coll.objects.link(obj)
    obj.hide_set(not show_cutters)
    obj.hide_render = True
    return obj


def apply_all_modifiers(obj: bpy.types.Object) -> list[str]:
    """Apply all modifiers on *obj*. Returns list of modifier names that failed."""
    view_layer = bpy.context.view_layer
    prev_active = view_layer.objects.active
    prev_selected = [o for o in bpy.context.selected_objects]

    try:
        if bpy.context.object and bpy.context.object.mode != 'OBJECT' and bpy.ops.object.mode_set.poll():
            bpy.ops.object.mode_set(mode='OBJECT')
    except Exception:
        pass

    view_layer.objects.active = obj
    obj.select_set(True)
    failed = []
    try:
        for m in list(obj.modifiers):
            try:
                bpy.ops.object.modifier_apply(modifier=m.name)
            except Exception as exc:
                failed.append(m.name)
                print(f"[PlinthGen] WARNING: modifier '{m.name}' failed to apply: {exc}")
                # Remove the broken modifier so it doesn't block later operations
                try:
                    obj.modifiers.remove(m)
                except Exception:
                    pass
    finally:
        obj.select_set(False)
        # Restore previous context
        try:
            view_layer.objects.active = prev_active
            for o in prev_selected:
                if o and o.name in bpy.data.objects:
                    o.select_set(True)
        except Exception:
            pass
    return failed


# -----------------------------
# Drain / vent hole placement
# -----------------------------
def drain_positions_box(width_mm, length_mm, inset_mm, radius_mm, count):
    count = max(0, int(count))
    if count == 0:
        return []

    hx = max(0.001, width_mm * 0.5 - inset_mm - radius_mm)
    hy = max(0.001, length_mm * 0.5 - inset_mm - radius_mm)

    if count == 1:
        return [(hx, hy)]
    if count == 2:
        return [(hx, hy), (-hx, -hy)]

    return rect_perimeter_centered_points(width_mm, length_mm, inset_mm, radius_mm, count)


def drain_positions_cyl(diameter_mm, inset_mm, radius_mm, count):
    count = max(0, int(count))
    if count == 0:
        return []
    r_outer = diameter_mm * 0.5
    r_place = max(0.001, r_outer - inset_mm - radius_mm)
    if count == 1:
        return [(r_place, 0.0)]
    if count == 2:
        return [(r_place, 0.0), (-r_place, 0.0)]
    pts = []
    for i in range(count):
        ang = (2.0 * math.pi * i) / count
        pts.append((r_place * math.cos(ang), r_place * math.sin(ang)))
    return pts


# -----------------------------
# Manifold Guarantee (preview only)
# -----------------------------
def bm_cleanup_and_normals(mesh: bpy.types.Mesh, merge_dist_mm: float = MERGE_DIST_MM):
    """Non-context cleanup: remove doubles, delete loose, recalc normals."""
    bm = bmesh.new()
    bm.from_mesh(mesh)

    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=max(merge_dist_mm, 1e-9))

    loose_edges = [e for e in bm.edges if len(e.link_faces) == 0]
    if loose_edges:
        bmesh.ops.delete(bm, geom=loose_edges, context='EDGES')

    loose_verts = [v for v in bm.verts if len(v.link_faces) == 0 and len(v.link_edges) == 0]
    if loose_verts:
        bmesh.ops.delete(bm, geom=loose_verts, context='VERTS')

    if bm.faces:
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)

    bm.to_mesh(mesh)
    bm.free()
    mesh.update()


def mesh_is_watertight(mesh: bpy.types.Mesh) -> bool:
    """Watertight test: every edge has exactly 2 linked faces."""
    bm = bmesh.new()
    bm.from_mesh(mesh)
    ok = True
    for e in bm.edges:
        if len(e.link_faces) != 2:
            ok = False
            break
    bm.free()
    return ok


def apply_voxel_remesh(obj: bpy.types.Object, voxel_size_mm: float) -> bool:
    """Apply voxel remesh modifier (context op). Returns True on success."""
    try:
        if bpy.context.object and bpy.context.object.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
    except Exception:
        pass

    view_layer = bpy.context.view_layer
    prev_active = view_layer.objects.active
    # Only deselect our target, not the whole scene
    obj.select_set(True)
    view_layer.objects.active = obj

    mod = obj.modifiers.new(name="VOXEL_REMESH_GUARANTEE", type='REMESH')
    mod.mode = 'VOXEL'
    mod.voxel_size = max(0.01, float(voxel_size_mm))  # mm because 1BU=1mm
    mod.use_smooth_shade = False
    mod.use_remove_disconnected = False
    mod.adaptivity = 0.0

    try:
        bpy.ops.object.modifier_apply(modifier=mod.name)
    except Exception as exc:
        print(f"[PlinthGen] WARNING: voxel remesh failed: {exc}")
        # Remove broken modifier if still present
        if obj.modifiers.get(mod.name):
            obj.modifiers.remove(obj.modifiers.get(mod.name))
        return False

    # Validate the remesh produced geometry
    if not obj.data or len(obj.data.vertices) == 0:
        print("[PlinthGen] WARNING: voxel remesh produced empty mesh")
        return False

    return True


def manifold_guarantee_on_preview(preview_obj: bpy.types.Object, voxel_size_mm: float) -> bool:
    """Run cleanup and optional voxel remesh. Returns True if remesh was successfully applied."""
    remeshed = False
    bm_cleanup_and_normals(preview_obj.data, merge_dist_mm=MERGE_DIST_MM)
    if not mesh_is_watertight(preview_obj.data):
        if apply_voxel_remesh(preview_obj, voxel_size_mm=voxel_size_mm):
            remeshed = True
            bm_cleanup_and_normals(preview_obj.data, merge_dist_mm=MERGE_DIST_MM)
        else:
            print("[PlinthGen] WARNING: manifold guarantee voxel remesh failed; mesh may not be watertight.")
    return remeshed


def _mesh_signed_volume(mesh: bpy.types.Mesh) -> float:
    """Signed volume in BU^3 (mm^3 with current unit settings)."""
    bm = bmesh.new()
    bm.from_mesh(mesh)
    vol = 0.0
    for f in bm.faces:
        if len(f.verts) < 3:
            continue
        v0 = f.verts[0].co
        for i in range(1, len(f.verts) - 1):
            v1 = f.verts[i].co
            v2 = f.verts[i + 1].co
            vol += v0.dot(v1.cross(v2)) / 6.0
    bm.free()
    return vol


def evaluate_preview_mesh_health(
    mesh: bpy.types.Mesh,
    degenerate_area_mm2: float = DEFAULT_DEGENERATE_FACE_AREA_MM2,
):
    """Return mesh health metrics and pass/fail."""
    bm = bmesh.new()
    bm.from_mesh(mesh)
    face_count = len(bm.faces)

    non_manifold_edges = 0
    boundary_edges = 0
    loose_edges = 0
    degenerate_faces = 0
    for e in bm.edges:
        lf = len(e.link_faces)
        if lf != 2:
            non_manifold_edges += 1
        if lf == 1:
            boundary_edges += 1
        elif lf == 0:
            loose_edges += 1

    loose_verts = sum(1 for v in bm.verts if len(v.link_edges) == 0)
    for f in bm.faces:
        if f.calc_area() <= max(1e-12, float(degenerate_area_mm2)):
            degenerate_faces += 1

    # Connected face islands.
    bm.faces.ensure_lookup_table()
    bm.faces.index_update()
    components = 0
    unseen = set(range(len(bm.faces)))
    while unseen:
        components += 1
        stack = [bm.faces[unseen.pop()]]
        while stack:
            face = stack.pop()
            for e in face.edges:
                for nf in e.link_faces:
                    nidx = nf.index
                    if nidx in unseen:
                        unseen.remove(nidx)
                        stack.append(nf)
    bm.free()

    watertight = (non_manifold_edges == 0)
    signed_volume = _mesh_signed_volume(mesh)
    inverted_normals = watertight and (abs(signed_volume) > 1e-6) and (signed_volume < 0.0)

    passed = (
        face_count > 0
        and watertight
        and loose_edges == 0
        and loose_verts == 0
        and degenerate_faces == 0
        and components <= 1
        and not inverted_normals
    )

    return {
        "passed": bool(passed),
        "watertight": bool(watertight),
        "non_manifold_edges": int(non_manifold_edges),
        "boundary_edges": int(boundary_edges),
        "loose_edges": int(loose_edges),
        "loose_verts": int(loose_verts),
        "degenerate_faces": int(degenerate_faces),
        "components": int(components),
        "inverted_normals": bool(inverted_normals),
        "signed_volume_mm3": float(signed_volume),
        "face_count": int(face_count),
    }


def reset_health_report(props: "PlinthGenProps", summary: str = "No health report available."):
    props.health_last_ran = False
    props.health_last_pass = False
    props.health_last_watertight = False
    props.health_last_non_manifold_edges = 0
    props.health_last_boundary_edges = 0
    props.health_last_loose_edges = 0
    props.health_last_loose_verts = 0
    props.health_last_degenerate_faces = 0
    props.health_last_components = 0
    props.health_last_inverted_normals = False
    props.health_last_remesh_used = False
    props.health_last_summary = summary


def store_health_report(props: "PlinthGenProps", report, remesh_used: bool):
    props.health_last_ran = True
    props.health_last_pass = bool(report["passed"])
    props.health_last_watertight = bool(report["watertight"])
    props.health_last_non_manifold_edges = int(report["non_manifold_edges"])
    props.health_last_boundary_edges = int(report["boundary_edges"])
    props.health_last_loose_edges = int(report["loose_edges"])
    props.health_last_loose_verts = int(report["loose_verts"])
    props.health_last_degenerate_faces = int(report["degenerate_faces"])
    props.health_last_components = int(report["components"])
    props.health_last_inverted_normals = bool(report["inverted_normals"])
    props.health_last_remesh_used = bool(remesh_used)
    if report["passed"]:
        props.health_last_summary = "PASS"
    else:
        issues = []
        if not report["watertight"]:
            issues.append("non-watertight")
        if report["loose_verts"] > 0 or report["loose_edges"] > 0:
            issues.append("loose geometry")
        if report["degenerate_faces"] > 0:
            issues.append("degenerate faces")
        if report["components"] > 1:
            issues.append("multiple islands")
        if report["inverted_normals"]:
            issues.append("inverted normals")
        props.health_last_summary = "FAIL: " + ", ".join(issues) if issues else "FAIL"


# -----------------------------
# Unit sync helpers
# -----------------------------
_unit_sync_lock = False  # module-level lock; avoids polluting undo stack / .blend file


def _sync_in_from_mm(props, mm_attr: str, in_attr: str):
    global _unit_sync_lock
    if _unit_sync_lock:
        return
    try:
        _unit_sync_lock = True
        setattr(props, in_attr, max(0.0, getattr(props, mm_attr) / MM_PER_INCH))
    finally:
        _unit_sync_lock = False


def _sync_mm_from_in(props, mm_attr: str, in_attr: str):
    global _unit_sync_lock
    if _unit_sync_lock:
        return
    try:
        _unit_sync_lock = True
        setattr(props, mm_attr, max(0.0, getattr(props, in_attr) * MM_PER_INCH))
    finally:
        _unit_sync_lock = False


def _on_width_mm_update(self, context):
    _sync_in_from_mm(self, "width_mm", "width_in")


def _on_length_mm_update(self, context):
    _sync_in_from_mm(self, "length_mm", "length_in")


def _on_height_mm_update(self, context):
    _sync_in_from_mm(self, "height_mm", "height_in")


def _on_diameter_mm_update(self, context):
    _sync_in_from_mm(self, "diameter_mm", "diameter_in")


def _on_cyl_height_mm_update(self, context):
    _sync_in_from_mm(self, "cyl_height_mm", "cyl_height_in")


def _on_width_in_update(self, context):
    _sync_mm_from_in(self, "width_mm", "width_in")


def _on_length_in_update(self, context):
    _sync_mm_from_in(self, "length_mm", "length_in")


def _on_height_in_update(self, context):
    _sync_mm_from_in(self, "height_mm", "height_in")


def _on_diameter_in_update(self, context):
    _sync_mm_from_in(self, "diameter_mm", "diameter_in")


def _on_cyl_height_in_update(self, context):
    _sync_mm_from_in(self, "cyl_height_mm", "cyl_height_in")


def _on_unit_input_update(self, context):
    # Keep inch fields aligned with mm values when user switches into inch-entry mode.
    if self.unit_input == "IN":
        _sync_in_from_mm(self, "width_mm", "width_in")
        _sync_in_from_mm(self, "length_mm", "length_in")
        _sync_in_from_mm(self, "height_mm", "height_in")
        _sync_in_from_mm(self, "diameter_mm", "diameter_in")
        _sync_in_from_mm(self, "cyl_height_mm", "cyl_height_in")


# -----------------------------
# Properties
# -----------------------------
class PlinthGenProps(bpy.types.PropertyGroup):
    unit_input: bpy.props.EnumProperty(
        name="Input Units",
        items=[("MM", "Millimeters", ""), ("IN", "Inches", "")],
        default="MM",
        update=_on_unit_input_update,
    )

    shape: bpy.props.EnumProperty(
        name="Plinth Type",
        items=[("BOX", "Box / Rectangle", ""), ("CYL", "Cylinder", "")],
        default="BOX",
    )

    # Box dims
    width_mm: bpy.props.FloatProperty(name="Width (mm)", default=76.2, min=1.0, update=_on_width_mm_update)
    length_mm: bpy.props.FloatProperty(name="Length (mm)", default=88.9, min=1.0, update=_on_length_mm_update)
    height_mm: bpy.props.FloatProperty(name="Height (mm)", default=57.15, min=1.0, update=_on_height_mm_update)
    width_in: bpy.props.FloatProperty(name="Width (in)", default=3.0, min=0.01, update=_on_width_in_update)
    length_in: bpy.props.FloatProperty(name="Length (in)", default=3.5, min=0.01, update=_on_length_in_update)
    height_in: bpy.props.FloatProperty(name="Height (in)", default=2.25, min=0.01, update=_on_height_in_update)

    # Cylinder dims
    diameter_mm: bpy.props.FloatProperty(name="Diameter (mm)", default=76.2, min=1.0, update=_on_diameter_mm_update)
    cyl_height_mm: bpy.props.FloatProperty(name="Height (mm)", default=57.15, min=1.0, update=_on_cyl_height_mm_update)
    diameter_in: bpy.props.FloatProperty(name="Diameter (in)", default=3.0, min=0.01, update=_on_diameter_in_update)
    cyl_height_in: bpy.props.FloatProperty(name="Height (in)", default=2.25, min=0.01, update=_on_cyl_height_in_update)
    cyl_segments: bpy.props.IntProperty(name="Cylinder Segments", default=64, min=12, max=256)

    # Slope
    slope_enabled: bpy.props.BoolProperty(name="Enable Slope", default=False)
    slope_delta_mm: bpy.props.FloatProperty(name="Slope Delta (mm)", default=0.0, min=0.0)
    slope_axis: bpy.props.EnumProperty(
        name="Slope Axis",
        items=[("X", "Along Width (X)", ""), ("Y", "Along Length (Y)", "")],
        default="Y",
    )
    slope_high_side: bpy.props.EnumProperty(
        name="High Side",
        items=[("POS", "Positive Axis Side", ""), ("NEG", "Negative Axis Side", "")],
        default="POS",
    )

    # Hollow
    hollow_enabled: bpy.props.BoolProperty(name="Enable Hollow", default=False)
    sealed_bottom: bpy.props.BoolProperty(name="Sealed Bottom", default=False)
    wall_thickness_mm: bpy.props.FloatProperty(name="Wall Thickness (mm)", default=6.0, min=0.5)
    top_thickness_mm: bpy.props.FloatProperty(name="Top Thickness (mm)", default=12.0, min=0.5)
    bottom_thickness_mm: bpy.props.FloatProperty(name="Bottom Thickness (mm)", default=3.0, min=0.5)

    # Base trim
    base_trim_enabled: bpy.props.BoolProperty(name="Decorative Half-Round Base", default=False)
    base_trim_radius_mm: bpy.props.FloatProperty(name="Half-Round Radius (mm)", default=2.5, min=0.1, max=50.0)
    base_trim_segments: bpy.props.IntProperty(name="Trim Segments", default=32, min=12, max=128)

    # Decorative profile band (ogee/cove/convex)
    profile_band_enabled: bpy.props.BoolProperty(name="Profile Band", default=False)
    profile_band_style: bpy.props.EnumProperty(
        name="Profile Style",
        items=[("OGEE", "Ogee", ""), ("COVE", "Cove", ""), ("CONVEX", "Convex", "")],
        default="OGEE",
    )
    profile_band_position: bpy.props.EnumProperty(
        name="Band Position",
        items=[("BASE", "Base", ""), ("TOP", "Top", "")],
        default="BASE",
    )
    profile_band_height_mm: bpy.props.FloatProperty(name="Band Height (mm)", default=4.0, min=0.2, max=100.0)
    profile_band_depth_mm: bpy.props.FloatProperty(name="Band Depth (mm)", default=1.5, min=0.1, max=50.0)
    profile_band_segments: bpy.props.IntProperty(name="Band Segments", default=24, min=12, max=128)

    # Stepped layers
    steps_enabled: bpy.props.BoolProperty(name="Stepped Layers", default=False)
    steps_count: bpy.props.IntProperty(name="Step Count", default=2, min=1, max=6)
    steps_height_mm: bpy.props.FloatProperty(name="Step Height (mm)", default=2.0, min=0.1, max=50.0)
    steps_offset_mm: bpy.props.FloatProperty(name="Step Offset (mm)", default=1.5, min=0.0, max=50.0)
    steps_position: bpy.props.EnumProperty(
        name="Steps Position",
        items=[("BASE", "Base", ""), ("TOP", "Top", "")],
        default="BASE",
    )

    # Vertical fluting
    fluting_enabled: bpy.props.BoolProperty(name="Vertical Fluting", default=False)
    fluting_count: bpy.props.IntProperty(name="Flute Count", default=16, min=1, max=128)
    fluting_width_mm: bpy.props.FloatProperty(name="Flute Width (mm)", default=2.5, min=0.2, max=50.0)
    fluting_depth_mm: bpy.props.FloatProperty(name="Flute Depth (mm)", default=0.8, min=0.05, max=25.0)
    fluting_z_margin_mm: bpy.props.FloatProperty(name="Flute Z Margin (mm)", default=2.0, min=0.0, max=50.0)

    # Recessed side panels
    panels_enabled: bpy.props.BoolProperty(name="Recessed Side Panels", default=False)
    panel_depth_mm: bpy.props.FloatProperty(name="Panel Depth (mm)", default=1.0, min=0.1, max=25.0)
    panel_border_mm: bpy.props.FloatProperty(name="Panel Border (mm)", default=6.0, min=0.0, max=100.0)
    panel_height_ratio: bpy.props.FloatProperty(name="Panel Height Ratio", default=0.6, min=0.1, max=0.95)
    panel_count_cyl: bpy.props.IntProperty(name="Panel Count (Cylinder)", default=4, min=3, max=24)

    # Bead border
    beads_enabled: bpy.props.BoolProperty(name="Bead Border", default=False)
    bead_size_mm: bpy.props.FloatProperty(name="Bead Size (mm)", default=1.5, min=0.2, max=20.0)
    bead_spacing_mm: bpy.props.FloatProperty(name="Bead Spacing (mm)", default=5.0, min=0.5, max=100.0)
    bead_rows: bpy.props.IntProperty(name="Bead Rows", default=1, min=1, max=4)
    bead_position: bpy.props.EnumProperty(
        name="Bead Position",
        items=[("BASE", "Base", ""), ("TOP", "Top", "")],
        default="BASE",
    )

    # Rope twist band
    rope_enabled: bpy.props.BoolProperty(name="Rope Twist Band", default=False)
    rope_dia_mm: bpy.props.FloatProperty(name="Rope Diameter (mm)", default=2.0, min=0.2, max=30.0)
    rope_pitch_mm: bpy.props.FloatProperty(name="Rope Pitch (mm)", default=6.0, min=0.5, max=100.0)
    rope_position: bpy.props.EnumProperty(
        name="Rope Position",
        items=[("BASE", "Base", ""), ("TOP", "Top", "")],
        default="TOP",
    )

    # Dentil course
    dentil_enabled: bpy.props.BoolProperty(name="Dentil Course", default=False)
    dentil_width_mm: bpy.props.FloatProperty(name="Dentil Width (mm)", default=2.0, min=0.2, max=50.0)
    dentil_depth_mm: bpy.props.FloatProperty(name="Dentil Depth (mm)", default=1.5, min=0.1, max=25.0)
    dentil_height_mm: bpy.props.FloatProperty(name="Dentil Height (mm)", default=2.0, min=0.1, max=25.0)
    dentil_spacing_mm: bpy.props.FloatProperty(name="Dentil Spacing (mm)", default=4.0, min=0.2, max=100.0)
    dentil_position: bpy.props.EnumProperty(
        name="Dentil Position",
        items=[("TOP", "Top", ""), ("BASE", "Base", "")],
        default="TOP",
    )

    # Scalloped skirt
    scallop_enabled: bpy.props.BoolProperty(name="Scalloped Skirt", default=False)
    scallop_count: bpy.props.IntProperty(name="Scallop Count", default=12, min=3, max=128)
    scallop_radius_mm: bpy.props.FloatProperty(name="Scallop Radius (mm)", default=2.5, min=0.1, max=50.0)
    scallop_depth_mm: bpy.props.FloatProperty(name="Scallop Depth (mm)", default=1.0, min=0.05, max=25.0)
    scallop_z_mm: bpy.props.FloatProperty(name="Scallop Center Z (mm)", default=3.0, min=0.0, max=1000.0)

    # Corner bosses / medallions
    bosses_enabled: bpy.props.BoolProperty(name="Corner Bosses / Medallions", default=False)
    boss_shape: bpy.props.EnumProperty(
        name="Boss Shape",
        items=[("DISC", "Disc", ""), ("SPHERE", "Sphere", "")],
        default="DISC",
    )
    boss_size_mm: bpy.props.FloatProperty(name="Boss Size (mm)", default=4.0, min=0.2, max=100.0)
    boss_relief_mm: bpy.props.FloatProperty(name="Boss Relief (mm)", default=1.5, min=0.1, max=50.0)
    boss_inset_mm: bpy.props.FloatProperty(name="Boss Inset (mm)", default=4.0, min=0.0, max=100.0)
    boss_count_cyl: bpy.props.IntProperty(name="Boss Count (Cylinder)", default=6, min=3, max=64)
    boss_z_ratio: bpy.props.FloatProperty(name="Boss Z Ratio", default=0.5, min=0.05, max=0.95)

    # Nameplate recess
    nameplate_enabled: bpy.props.BoolProperty(name="Nameplate Recess", default=False)
    nameplate_width_mm: bpy.props.FloatProperty(name="Nameplate Width (mm)", default=24.0, min=0.5, max=500.0)
    nameplate_height_mm: bpy.props.FloatProperty(name="Nameplate Height (mm)", default=12.0, min=0.5, max=500.0)
    nameplate_depth_mm: bpy.props.FloatProperty(name="Nameplate Depth (mm)", default=1.0, min=0.1, max=50.0)
    nameplate_side: bpy.props.EnumProperty(
        name="Nameplate Side",
        items=[
            ("POS_Y", "Front (+Y)", ""),
            ("NEG_Y", "Back (-Y)", ""),
            ("POS_X", "Right (+X)", ""),
            ("NEG_X", "Left (-X)", ""),
        ],
        default="POS_Y",
    )
    nameplate_z_ratio: bpy.props.FloatProperty(name="Nameplate Z Ratio", default=0.5, min=0.05, max=0.95)

    # Surface texture stamp
    texture_enabled: bpy.props.BoolProperty(name="Surface Texture Stamp", default=False)
    texture_strength_mm: bpy.props.FloatProperty(name="Texture Strength (mm)", default=0.2, min=0.0, max=10.0)
    texture_scale_mm: bpy.props.FloatProperty(name="Texture Scale (mm)", default=3.0, min=0.1, max=100.0)
    texture_seed: bpy.props.IntProperty(name="Texture Seed", default=1, min=0, max=1000000)
    texture_zone: bpy.props.EnumProperty(
        name="Texture Zone",
        items=[("SIDES", "Sides Only", ""), ("ALL", "All Faces", "")],
        default="SIDES",
    )

    # Foot pads / bun feet
    feet_enabled: bpy.props.BoolProperty(name="Foot Pads / Bun Feet", default=False)
    feet_type: bpy.props.EnumProperty(
        name="Feet Type",
        items=[("PAD", "Pad", ""), ("BUN", "Bun", "")],
        default="PAD",
    )
    feet_radius_mm: bpy.props.FloatProperty(name="Feet Radius (mm)", default=2.0, min=0.1, max=100.0)
    feet_height_mm: bpy.props.FloatProperty(name="Feet Height (mm)", default=2.0, min=0.1, max=100.0)
    feet_inset_mm: bpy.props.FloatProperty(name="Feet Inset (mm)", default=4.0, min=0.0, max=200.0)
    feet_count_cyl: bpy.props.IntProperty(name="Feet Count (Cylinder)", default=4, min=3, max=64)

    # Magnets
    magnets_count: bpy.props.IntProperty(name="# Magnets", default=4, min=0, max=64)
    magnet_layout_box: bpy.props.EnumProperty(
        name="Magnet Layout (Box)",
        items=[("PERIMETER", "Perimeter", ""), ("CORNERS", "Corners", "")],
        default="PERIMETER",
    )
    magnet_dia_mm: bpy.props.FloatProperty(name="Magnet Dia (mm)", default=5.0, min=0.5)
    magnet_hole_depth_mm: bpy.props.FloatProperty(name="Magnet Hole Depth (mm)", default=2.0, min=0.1)
    dia_tol_mm: bpy.props.FloatProperty(name="Diameter Tolerance + (mm)", default=0.2, min=0.0)
    depth_tol_mm: bpy.props.FloatProperty(name="Depth Tolerance + (mm)", default=0.3, min=0.0)
    inset_mm: bpy.props.FloatProperty(name="Magnet Inset (mm)", default=6.0, min=0.0)

    # Drains
    drain_enabled: bpy.props.BoolProperty(name="Drain/Vent Holes", default=True)
    drain_count: bpy.props.IntProperty(name="# Drain Holes", default=2, min=0, max=12)
    drain_dia_mm: bpy.props.FloatProperty(name="Drain Dia (mm)", default=4.0, min=0.5)
    drain_inset_mm: bpy.props.FloatProperty(name="Drain Inset (mm)", default=8.0, min=0.0)
    drain_at_magnet_centers: bpy.props.BoolProperty(
        name="Drain at Magnet Centers",
        default=False,
        description="Add drain holes centered inside magnet pockets (sealed hollow bottoms only).",
    )
    magnet_center_drain_dia_mm: bpy.props.FloatProperty(
        name="Magnet Center Drain Dia (mm)",
        default=1.5,
        min=0.2,
        max=10.0,
    )

    # Visual/debug
    show_cutters: bpy.props.BoolProperty(name="Show Cutters", default=False)
    preview_cuts_duplicate: bpy.props.BoolProperty(
        name="Preview Cuts (Duplicate)",
        default=True,
        description="Creates a duplicate with booleans applied (export this).",
    )

    # Manifold guarantee
    manifold_guarantee: bpy.props.BoolProperty(
        name="Manifold Guarantee (Preview)",
        default=True,
        description="If preview isn't watertight after booleans, apply voxel remesh (only when needed).",
    )
    voxel_size_mm: bpy.props.FloatProperty(
        name="Voxel Size (mm)",
        default=DEFAULT_VOXEL_MM,
        min=0.05,
        max=2.0,
        description="Used only when manifold guarantee triggers voxel remesh.",
    )

    # Post-build health check (preview mesh)
    health_check_enabled: bpy.props.BoolProperty(
        name="Post-Build Health Check",
        default=True,
        description="Analyze preview mesh after booleans/manifold processing.",
    )
    health_block_preview_on_fail: bpy.props.BoolProperty(
        name="Block Preview On Fail",
        default=True,
        description="Hide preview/export mesh when health check fails. Recommended for 3D printing.",
    )
    health_degenerate_area_mm2: bpy.props.FloatProperty(
        name="Degenerate Face Threshold (mm^2)",
        default=DEFAULT_DEGENERATE_FACE_AREA_MM2,
        min=1e-8,
        max=1.0,
        precision=6,
    )

    # Stored health report (latest build)
    health_last_ran: bpy.props.BoolProperty(default=False, options={"HIDDEN"})
    health_last_pass: bpy.props.BoolProperty(default=False, options={"HIDDEN"})
    health_last_watertight: bpy.props.BoolProperty(default=False, options={"HIDDEN"})
    health_last_non_manifold_edges: bpy.props.IntProperty(default=0, options={"HIDDEN"})
    health_last_boundary_edges: bpy.props.IntProperty(default=0, options={"HIDDEN"})
    health_last_loose_edges: bpy.props.IntProperty(default=0, options={"HIDDEN"})
    health_last_loose_verts: bpy.props.IntProperty(default=0, options={"HIDDEN"})
    health_last_degenerate_faces: bpy.props.IntProperty(default=0, options={"HIDDEN"})
    health_last_components: bpy.props.IntProperty(default=0, options={"HIDDEN"})
    health_last_inverted_normals: bpy.props.BoolProperty(default=False, options={"HIDDEN"})
    health_last_remesh_used: bpy.props.BoolProperty(default=False, options={"HIDDEN"})
    health_last_summary: bpy.props.StringProperty(default="No health report available.", options={"HIDDEN"})

    # Magnet/drain overlap safety (prevents “missing” holes)
    avoid_overlap_enabled: bpy.props.BoolProperty(
        name="Avoid Magnet/Drain Overlap",
        default=True,
        description="Keeps drains away from magnets to prevent boolean weirdness and missing holes.",
    )
    overlap_safety_mm: bpy.props.FloatProperty(
        name="Overlap Safety (mm)",
        default=1.0,
        min=0.0,
        max=10.0,
        description="Extra spacing between magnet and drain holes.",
    )


# -----------------------------
# Preflight validator
# -----------------------------
def preflight_validate(props: PlinthGenProps):
    errors = []
    warnings = []

    if props.shape == "BOX":
        body_h = props.height_mm
        body_min_planar = min(props.width_mm, props.length_mm)
    else:
        body_h = props.cyl_height_mm
        body_min_planar = props.diameter_mm

    if props.hollow_enabled:
        if props.shape == "BOX":
            inner_w = props.width_mm - (2.0 * props.wall_thickness_mm)
            inner_l = props.length_mm - (2.0 * props.wall_thickness_mm)
            if inner_w <= 0.0 or inner_l <= 0.0:
                errors.append("Wall thickness is too large for selected box dimensions.")
        else:
            inner_d = props.diameter_mm - (2.0 * props.wall_thickness_mm)
            if inner_d <= 0.0:
                errors.append("Wall thickness is too large for selected cylinder diameter.")

        roof_z = body_h - props.top_thickness_mm
        if roof_z <= 0.0:
            errors.append("Top thickness must be less than total height when Hollow is enabled.")

        if props.sealed_bottom:
            if props.bottom_thickness_mm >= body_h:
                errors.append("Bottom thickness must be less than total height.")
            if props.bottom_thickness_mm >= roof_z:
                errors.append("Bottom thickness must be less than (height - top thickness).")
    elif props.sealed_bottom:
        warnings.append("Sealed Bottom is ignored unless Hollow is enabled.")

    if props.magnets_count > 0:
        magnet_cutter_dia = max(0.1, props.magnet_dia_mm + props.dia_tol_mm)
        magnet_r = magnet_cutter_dia * 0.5
        requested_depth = max(0.1, props.magnet_hole_depth_mm + props.depth_tol_mm)

        if props.shape == "BOX":
            max_inset_x = (props.width_mm * 0.5) - magnet_r
            max_inset_y = (props.length_mm * 0.5) - magnet_r
            if max_inset_x <= 0.0 or max_inset_y <= 0.0:
                errors.append("Magnet diameter/tolerance is too large for selected box dimensions.")
            elif props.inset_mm > min(max_inset_x, max_inset_y):
                warnings.append("Magnet inset exceeds available space; placement will be clamped.")
        else:
            max_inset = (props.diameter_mm * 0.5) - magnet_r
            if max_inset <= 0.0:
                errors.append("Magnet diameter/tolerance is too large for selected cylinder diameter.")
            elif props.inset_mm > max_inset:
                warnings.append("Magnet inset exceeds available space; placement will be clamped.")

        if props.hollow_enabled and props.sealed_bottom:
            max_safe = props.bottom_thickness_mm - MAGNET_CLAMP_MARGIN_MM
            if max_safe <= 0.0:
                warnings.append("Magnet holes are disabled because sealed bottom is at/below clamp margin.")
            elif requested_depth > max_safe:
                warnings.append(f"Magnet hole depth will clamp to {max_safe:.2f}mm due to sealed bottom.")

        if props.drain_enabled and props.drain_at_magnet_centers:
            if props.magnet_center_drain_dia_mm >= magnet_cutter_dia:
                warnings.append("Magnet center drain diameter should be smaller than magnet hole diameter.")

    if props.drain_enabled:
        if not props.hollow_enabled:
            warnings.append("Drain holes are ignored unless Hollow is enabled.")
        else:
            if props.drain_count > 0:
                drain_r = max(0.1, props.drain_dia_mm * 0.5)
                if props.shape == "BOX":
                    max_inset_x = (props.width_mm * 0.5) - drain_r
                    max_inset_y = (props.length_mm * 0.5) - drain_r
                    if max_inset_x <= 0.0 or max_inset_y <= 0.0:
                        errors.append("Drain diameter is too large for selected box dimensions.")
                    elif props.drain_inset_mm > min(max_inset_x, max_inset_y):
                        warnings.append("Drain inset exceeds available space; placement will be clamped.")
                else:
                    max_inset = (props.diameter_mm * 0.5) - drain_r
                    if max_inset <= 0.0:
                        errors.append("Drain diameter is too large for selected cylinder diameter.")
                    elif props.drain_inset_mm > max_inset:
                        warnings.append("Drain inset exceeds available space; placement will be clamped.")

            if props.drain_at_magnet_centers:
                if not props.sealed_bottom:
                    warnings.append("Drain at Magnet Centers requires Sealed Bottom.")
                if props.magnets_count <= 0:
                    warnings.append("Drain at Magnet Centers requires at least one magnet.")
    elif props.drain_at_magnet_centers:
        warnings.append("Drain at Magnet Centers is ignored while Drain/Vent Holes is disabled.")

    if props.base_trim_enabled:
        if props.shape == "BOX":
            max_trim = min(props.width_mm, props.length_mm) * 0.5
            if props.base_trim_radius_mm >= max_trim:
                warnings.append("Base trim radius is very large relative to box footprint.")
        else:
            max_minor = (props.diameter_mm * 0.5) - 0.1
            if max_minor <= 0.0:
                errors.append("Cylinder diameter is too small for base trim.")
            elif props.base_trim_radius_mm > max_minor:
                warnings.append(f"Cylinder trim radius will clamp to {max_minor:.2f}mm.")

    if props.manifold_guarantee and props.voxel_size_mm > max(0.2, body_min_planar * 0.2):
        warnings.append("Voxel size is coarse for current dimensions and may remove detail.")

    if props.health_check_enabled and not props.preview_cuts_duplicate:
        warnings.append("Post-build health check requires Preview Cuts (Duplicate).")
    if props.health_block_preview_on_fail and not props.health_check_enabled:
        warnings.append("Block Preview On Fail is ignored when Post-Build Health Check is disabled.")

    # Decorative feature sanity checks.
    if props.steps_enabled and (props.steps_count * props.steps_height_mm) > body_h:
        warnings.append("Stepped layer stack is taller than body height.")
    if props.fluting_enabled and (2.0 * props.fluting_z_margin_mm) >= body_h:
        warnings.append("Flute Z margin leaves little or no usable flute height.")
    if props.panels_enabled:
        if props.shape == "BOX":
            if (2.0 * props.panel_border_mm) >= props.width_mm or (2.0 * props.panel_border_mm) >= props.length_mm:
                warnings.append("Panel border is too large for current box dimensions.")
        elif props.panel_count_cyl < 3:
            warnings.append("Cylinder panel count should be at least 3.")
    if props.nameplate_enabled:
        if props.shape == "BOX":
            if props.nameplate_side in {"POS_Y", "NEG_Y"} and props.nameplate_width_mm >= props.width_mm:
                warnings.append("Nameplate width is large for selected side.")
            if props.nameplate_side in {"POS_X", "NEG_X"} and props.nameplate_width_mm >= props.length_mm:
                warnings.append("Nameplate width is large for selected side.")
        else:
            if props.nameplate_width_mm >= (math.pi * props.diameter_mm * 0.5):
                warnings.append("Nameplate width is large for selected cylinder diameter.")
    if props.texture_enabled and props.texture_strength_mm > max(0.2, body_min_planar * 0.05):
        warnings.append("Texture strength is high relative to plinth size.")
    if props.feet_enabled:
        if props.shape == "BOX":
            if props.feet_inset_mm >= (min(props.width_mm, props.length_mm) * 0.5):
                warnings.append("Feet inset is large and may collapse feet positions.")
        else:
            if props.feet_inset_mm >= (props.diameter_mm * 0.5):
                warnings.append("Feet inset is large and may collapse feet positions.")

    # Security/safety: bound perimeter-driven decorative instance counts.
    if props.beads_enabled:
        bead_min = 4 if props.shape == "BOX" else 6
        bead_n = estimate_perimeter_instance_count(
            shape=props.shape,
            width_mm=props.width_mm,
            length_mm=props.length_mm,
            diameter_mm=props.diameter_mm,
            spacing_mm=props.bead_spacing_mm,
            minimum=bead_min,
        )
        bead_total = bead_n * max(1, int(props.bead_rows))
        if bead_total > MAX_PERIMETER_DETAIL_INSTANCES:
            errors.append(
                f"Bead Border would create {bead_total} beads (limit {MAX_PERIMETER_DETAIL_INSTANCES}). "
                "Increase bead spacing or reduce plinth dimensions."
            )

    if props.rope_enabled:
        rope_per = rope_perimeter_mm(
            shape=props.shape,
            width_mm=props.width_mm,
            length_mm=props.length_mm,
            diameter_mm=props.diameter_mm,
            rope_dia_mm=props.rope_dia_mm,
        )
        rope_n = rope_sample_count(rope_per, props.rope_pitch_mm)
        rope_total = rope_n * 2
        if rope_total > MAX_PERIMETER_DETAIL_INSTANCES:
            errors.append(
                f"Rope Twist Band would create {rope_total} strand elements (limit {MAX_PERIMETER_DETAIL_INSTANCES}). "
                "Increase rope pitch or reduce plinth dimensions."
            )

    if props.dentil_enabled:
        dentil_min = 4 if props.shape == "BOX" else 6
        dentil_spacing = max(props.dentil_spacing_mm, props.dentil_width_mm)
        dentil_n = estimate_perimeter_instance_count(
            shape=props.shape,
            width_mm=props.width_mm,
            length_mm=props.length_mm,
            diameter_mm=props.diameter_mm,
            spacing_mm=dentil_spacing,
            minimum=dentil_min,
        )
        if dentil_n > MAX_PERIMETER_DETAIL_INSTANCES:
            errors.append(
                f"Dentil Course would create {dentil_n} dentils (limit {MAX_PERIMETER_DETAIL_INSTANCES}). "
                "Increase dentil spacing/width or reduce plinth dimensions."
            )

    # Deduplicate while preserving order.
    dedup_errors = list(dict.fromkeys(errors))
    dedup_warnings = list(dict.fromkeys(warnings))
    return dedup_errors, dedup_warnings


def preflight_report_to_operator(op: bpy.types.Operator, errors, warnings):
    if errors:
        op.report({'ERROR'}, f"Preflight failed ({len(errors)} issue(s)).")
        for msg in errors[:5]:
            op.report({'ERROR'}, msg)
        if len(errors) > 5:
            op.report({'ERROR'}, f"... and {len(errors) - 5} more.")
        return False
    if warnings:
        op.report({'WARNING'}, f"Preflight warning(s): {len(warnings)}. See panel for details.")
    return True


# -----------------------------
# Build core
# -----------------------------
def build_plinth(context, props: PlinthGenProps):
    """Build geometry. Returns (preview_blocked, block_message)."""
    ensure_units_mm()
    clear_plinthgen_artifacts()
    reset_health_report(props, summary="Health check has not run yet.")
    preview_blocked = False
    preview_block_message = ""

    coll = get_or_create_collection(COLL_NAME)

    high_positive = (props.slope_high_side == "POS")
    slope_on = props.slope_enabled and props.slope_delta_mm > 0.0
    body_h = props.height_mm if props.shape == "BOX" else props.cyl_height_mm
    body_w = props.width_mm if props.shape == "BOX" else props.diameter_mm
    body_l = props.length_mm if props.shape == "BOX" else props.diameter_mm

    # MAIN
    if props.shape == "BOX":
        mesh_main = make_box_mesh(props.width_mm, props.length_mm, props.height_mm, "Plinth_MainBoxMesh_v3_3")
        if slope_on:
            slope_top_only(mesh_main, props.height_mm, props.slope_delta_mm, props.slope_axis, high_positive)
        ground_mesh_to_z0(mesh_main)
    else:
        mesh_main = make_cylinder_mesh(props.diameter_mm, props.cyl_height_mm, props.cyl_segments, "Plinth_MainCylMesh_v3_3")
        if slope_on:
            slope_top_only(mesh_main, props.cyl_height_mm, props.slope_delta_mm, props.slope_axis, high_positive)
        ground_mesh_to_z0(mesh_main)

    main_obj = bpy.data.objects.new(OBJ_MAIN, mesh_main)
    coll.objects.link(main_obj)

    # HOLLOW (cutter)
    if props.hollow_enabled:
        if props.shape == "BOX":
            mesh_hollow = make_hollow_box_cutter_mesh(
                width_mm=props.width_mm,
                length_mm=props.length_mm,
                height_mm=props.height_mm,
                wall_thickness_mm=props.wall_thickness_mm,
                top_thickness_mm=props.top_thickness_mm,
                sealed_bottom=props.sealed_bottom,
                bottom_thickness_mm=props.bottom_thickness_mm,
                slope_enabled=slope_on,
                slope_delta_mm=props.slope_delta_mm,
                slope_axis=props.slope_axis,
                high_positive=high_positive,
            )
        else:
            mesh_hollow = make_hollow_cyl_cutter_mesh(
                diameter_mm=props.diameter_mm,
                height_mm=props.cyl_height_mm,
                wall_thickness_mm=props.wall_thickness_mm,
                top_thickness_mm=props.top_thickness_mm,
                sealed_bottom=props.sealed_bottom,
                bottom_thickness_mm=props.bottom_thickness_mm,
                slope_enabled=slope_on,
                slope_delta_mm=props.slope_delta_mm,
                slope_axis=props.slope_axis,
                high_positive=high_positive,
                segments=props.cyl_segments,
            )

        hollow_obj = bpy.data.objects.new(OBJ_HOLLOW, mesh_hollow)
        coll.objects.link(hollow_obj)
        hollow_obj.hide_set(not props.show_cutters)
        hollow_obj.hide_render = True
        add_boolean_modifier(main_obj, hollow_obj, "HollowCut")

    # MAGNETS
    magnet_pts = []
    drain_pts = []
    post_remesh_functional_cutters = []

    if props.magnets_count > 0:
        cutter_dia = max(0.1, props.magnet_dia_mm + props.dia_tol_mm)
        cutter_radius = cutter_dia * 0.5
        requested_depth = max(0.1, props.magnet_hole_depth_mm + props.depth_tol_mm)

        # Clamp magnet depth for sealed hollow bottoms.
        actual_depth = requested_depth
        if props.hollow_enabled and props.sealed_bottom:
            max_safe = props.bottom_thickness_mm - MAGNET_CLAMP_MARGIN_MM
            actual_depth = min(requested_depth, max(0.0, max_safe))

        if props.shape == "BOX":
            if props.magnet_layout_box == "CORNERS":
                magnet_pts = rect_corner_points(props.width_mm, props.length_mm, props.inset_mm, cutter_radius, props.magnets_count)
            else:
                magnet_pts = rect_perimeter_centered_points(props.width_mm, props.length_mm, props.inset_mm, cutter_radius, props.magnets_count)
        else:
            magnet_pts = circle_ring_points(props.diameter_mm, props.inset_mm, cutter_radius, props.magnets_count)

        # Deduplicate coincident magnet points.
        magnet_pts = uniq_points(magnet_pts, grid_mm=0.001)

        if actual_depth > 0.0 and magnet_pts:
            cutters_mesh = build_vertical_cylinder_cutters_mesh(
                radius_mm=cutter_radius,
                depth_mm=actual_depth,
                positions_xy=magnet_pts,
                mesh_name="Plinth_MagnetCuttersMesh_v3_3",
                segments=48,
                overshoot_mm=OVERSHOOT_MM
            )
            cutters_obj = bpy.data.objects.new(OBJ_CUTTERS, cutters_mesh)
            coll.objects.link(cutters_obj)
            cutters_obj.hide_set(not props.show_cutters)
            cutters_obj.hide_render = True
            add_boolean_modifier(main_obj, cutters_obj, "MagnetCut")
            post_remesh_functional_cutters.append(cutters_obj)
        else:
            # No safe depth remains after clamp; skip magnet cutters.
            magnet_pts = []

    # DRAINS (only meaningful when hollow is enabled)
    if props.drain_enabled and props.hollow_enabled and props.drain_count > 0:
        drain_radius = max(0.1, props.drain_dia_mm * 0.5)

        if props.sealed_bottom:
            drain_depth = max(3.0, props.bottom_thickness_mm + 2.0)
            drain_overshoot = 0.0
        else:
            drain_depth = 6.0
            drain_overshoot = OVERSHOOT_MM

        if props.shape == "BOX":
            drain_pts = drain_positions_box(props.width_mm, props.length_mm, props.drain_inset_mm, drain_radius, props.drain_count)
        else:
            drain_pts = drain_positions_cyl(props.diameter_mm, props.drain_inset_mm, drain_radius, props.drain_count)

        drain_pts = uniq_points(drain_pts, grid_mm=0.001)

        # Keep drain points clear of magnet points.
        if props.avoid_overlap_enabled and magnet_pts:
            min_sep = (drain_radius + (props.magnet_dia_mm + props.dia_tol_mm) * 0.5) + max(0.0, props.overlap_safety_mm)
            drain_pts = filter_points_by_min_distance(drain_pts, magnet_pts, min_sep)

            # If all drains were filtered out, try center; if that also overlaps, skip drains entirely.
            if not drain_pts:
                center_candidate = [(0.0, 0.0)]
                center_candidate = filter_points_by_min_distance(center_candidate, magnet_pts, min_sep)
                if center_candidate:
                    drain_pts = center_candidate
                else:
                    print("[PlinthGen] WARNING: all drain positions overlap with magnets; drains skipped.")

        if drain_pts:
            drains_mesh = build_vertical_cylinder_cutters_mesh(
                radius_mm=drain_radius,
                depth_mm=drain_depth,
                positions_xy=drain_pts,
                mesh_name="Plinth_DrainCuttersMesh_v3_3",
                segments=48,
                overshoot_mm=drain_overshoot
            )
            drains_obj = bpy.data.objects.new(OBJ_DRAINS, drains_mesh)
            coll.objects.link(drains_obj)
            drains_obj.hide_set(not props.show_cutters)
            drains_obj.hide_render = True
            add_boolean_modifier(main_obj, drains_obj, "DrainCut")
            post_remesh_functional_cutters.append(drains_obj)

    # DRAINS AT MAGNET CENTERS (sealed hollow bottoms)
    if (
        props.drain_enabled
        and props.hollow_enabled
        and props.sealed_bottom
        and props.drain_at_magnet_centers
        and magnet_pts
    ):
        center_pts = uniq_points(magnet_pts, grid_mm=0.001)
        center_radius = max(0.1, props.magnet_center_drain_dia_mm * 0.5)
        center_depth = max(3.0, props.bottom_thickness_mm + 2.0)

        center_mesh = build_vertical_cylinder_cutters_mesh(
            radius_mm=center_radius,
            depth_mm=center_depth,
            positions_xy=center_pts,
            mesh_name="Plinth_MagnetCenterDrainCuttersMesh_v3_3",
            segments=48,
            overshoot_mm=0.0,
        )
        center_obj = bpy.data.objects.new(OBJ_DRAINS_MAGNET_CENTER, center_mesh)
        coll.objects.link(center_obj)
        center_obj.hide_set(not props.show_cutters)
        center_obj.hide_render = True
        add_boolean_modifier(main_obj, center_obj, "DrainAtMagnetCenters")
        post_remesh_functional_cutters.append(center_obj)

    # BASE TRIM (decorative half-round at base)
    if props.base_trim_enabled and props.base_trim_radius_mm > 0.0:
        trim_radius = max(0.1, float(props.base_trim_radius_mm))
        if props.shape == "BOX":
            trim_mesh = make_box_base_half_round_mesh(
                width_mm=props.width_mm,
                length_mm=props.length_mm,
                radius_mm=trim_radius,
                segments=props.base_trim_segments,
                mesh_name="Plinth_BaseTrimBoxMesh_v3_3",
            )
        else:
            trim_mesh = make_cyl_base_half_round_mesh(
                major_radius_mm=props.diameter_mm * 0.5,
                minor_radius_mm=trim_radius,
                major_segments=max(24, int(props.cyl_segments)),
                minor_segments=props.base_trim_segments,
                mesh_name="Plinth_BaseTrimCylMesh_v3_3",
            )

        trim_obj = bpy.data.objects.new(OBJ_BASE_TRIM, trim_mesh)
        coll.objects.link(trim_obj)
        trim_obj.hide_set(not props.show_cutters)
        trim_obj.hide_render = True
        add_boolean_union_modifier(main_obj, trim_obj, "BaseTrimUnion")

    # PROFILE BAND (ogee / cove / convex)
    if props.profile_band_enabled:
        band_h = max(0.2, props.profile_band_height_mm)
        band_d = max(0.1, props.profile_band_depth_mm)
        at_top = (props.profile_band_position == "TOP")
        band_center = (body_h - (band_h * 0.5)) if at_top else (band_h * 0.5)

        if props.profile_band_style in {"CONVEX", "OGEE"}:
            zc = band_center - (band_d * 0.25 if props.profile_band_style == "OGEE" else 0.0)
            if props.shape == "BOX":
                mesh_union = make_box_base_half_round_mesh(
                    props.width_mm,
                    props.length_mm,
                    band_d,
                    props.profile_band_segments,
                    "Plinth_ProfileBandUnionBoxMesh_v3_3",
                )
            else:
                mesh_union = make_cyl_base_half_round_mesh(
                    props.diameter_mm * 0.5,
                    band_d,
                    max(24, int(props.cyl_segments)),
                    props.profile_band_segments,
                    "Plinth_ProfileBandUnionCylMesh_v3_3",
                )
            translate_mesh(mesh_union, Vector((0.0, 0.0, zc - band_d)))
            obj_union = add_helper_boolean_object(coll, mesh_union, "Plinth_ProfileBandUnion_v3_3", props.show_cutters)
            add_boolean_union_modifier(main_obj, obj_union, "ProfileBandUnion")

        if props.profile_band_style in {"COVE", "OGEE"}:
            zc = band_center + (band_d * 0.25 if props.profile_band_style == "OGEE" else 0.0)
            if props.shape == "BOX":
                mesh_cut = make_box_base_half_round_mesh(
                    props.width_mm,
                    props.length_mm,
                    band_d,
                    props.profile_band_segments,
                    "Plinth_ProfileBandCutBoxMesh_v3_3",
                )
            else:
                mesh_cut = make_cyl_base_half_round_mesh(
                    props.diameter_mm * 0.5,
                    band_d,
                    max(24, int(props.cyl_segments)),
                    props.profile_band_segments,
                    "Plinth_ProfileBandCutCylMesh_v3_3",
                )
            translate_mesh(mesh_cut, Vector((0.0, 0.0, zc - band_d)))
            obj_cut = add_helper_boolean_object(coll, mesh_cut, "Plinth_ProfileBandCut_v3_3", props.show_cutters)
            add_boolean_modifier(main_obj, obj_cut, "ProfileBandCut")

    # STEPPED LAYERS
    if props.steps_enabled:
        mesh_steps = make_stepped_layers_mesh(
            shape=props.shape,
            width_mm=props.width_mm,
            length_mm=props.length_mm,
            diameter_mm=props.diameter_mm,
            height_mm=body_h,
            steps_count=props.steps_count,
            step_height_mm=props.steps_height_mm,
            step_offset_mm=props.steps_offset_mm,
            at_top=(props.steps_position == "TOP"),
            segments=max(24, int(props.cyl_segments)),
            mesh_name="Plinth_SteppedLayersMesh_v3_3",
        )
        obj_steps = add_helper_boolean_object(coll, mesh_steps, "Plinth_SteppedLayers_v3_3", props.show_cutters)
        add_boolean_union_modifier(main_obj, obj_steps, "SteppedLayersUnion")

    # VERTICAL FLUTING
    if props.fluting_enabled:
        mesh_flutes = make_vertical_flute_cutters_mesh(
            shape=props.shape,
            width_mm=props.width_mm,
            length_mm=props.length_mm,
            diameter_mm=props.diameter_mm,
            height_mm=body_h,
            flute_count=props.fluting_count,
            flute_width_mm=props.fluting_width_mm,
            flute_depth_mm=props.fluting_depth_mm,
            z_margin_mm=props.fluting_z_margin_mm,
            segments=max(16, int(props.cyl_segments)),
            mesh_name="Plinth_FlutingCuttersMesh_v3_3",
        )
        obj_flutes = add_helper_boolean_object(coll, mesh_flutes, "Plinth_FlutingCutters_v3_3", props.show_cutters)
        add_boolean_modifier(main_obj, obj_flutes, "FlutingCut")

    # RECESSED SIDE PANELS
    if props.panels_enabled:
        mesh_panels = make_recessed_panels_cutters_mesh(
            shape=props.shape,
            width_mm=props.width_mm,
            length_mm=props.length_mm,
            diameter_mm=props.diameter_mm,
            height_mm=body_h,
            panel_depth_mm=props.panel_depth_mm,
            panel_border_mm=props.panel_border_mm,
            panel_height_ratio=props.panel_height_ratio,
            panel_count_cyl=props.panel_count_cyl,
            segments=max(16, int(props.cyl_segments)),
            mesh_name="Plinth_RecessedPanelsCuttersMesh_v3_3",
        )
        obj_panels = add_helper_boolean_object(coll, mesh_panels, "Plinth_RecessedPanelsCutters_v3_3", props.show_cutters)
        add_boolean_modifier(main_obj, obj_panels, "PanelCut")

    # BEAD BORDER
    if props.beads_enabled:
        mesh_beads = make_bead_border_mesh(
            shape=props.shape,
            width_mm=props.width_mm,
            length_mm=props.length_mm,
            diameter_mm=props.diameter_mm,
            height_mm=body_h,
            bead_size_mm=props.bead_size_mm,
            bead_spacing_mm=props.bead_spacing_mm,
            bead_rows=props.bead_rows,
            at_top=(props.bead_position == "TOP"),
            mesh_name="Plinth_BeadBorderMesh_v3_3",
        )
        obj_beads = add_helper_boolean_object(coll, mesh_beads, "Plinth_BeadBorder_v3_3", props.show_cutters)
        add_boolean_union_modifier(main_obj, obj_beads, "BeadBorderUnion")

    # ROPE TWIST BAND
    if props.rope_enabled:
        mesh_rope = make_rope_band_mesh(
            shape=props.shape,
            width_mm=props.width_mm,
            length_mm=props.length_mm,
            diameter_mm=props.diameter_mm,
            height_mm=body_h,
            rope_dia_mm=props.rope_dia_mm,
            rope_pitch_mm=props.rope_pitch_mm,
            at_top=(props.rope_position == "TOP"),
            mesh_name="Plinth_RopeBandMesh_v3_3",
        )
        obj_rope = add_helper_boolean_object(coll, mesh_rope, "Plinth_RopeBand_v3_3", props.show_cutters)
        add_boolean_union_modifier(main_obj, obj_rope, "RopeBandUnion")

    # DENTIL COURSE
    if props.dentil_enabled:
        mesh_dentil = make_dentil_course_mesh(
            shape=props.shape,
            width_mm=props.width_mm,
            length_mm=props.length_mm,
            diameter_mm=props.diameter_mm,
            height_mm=body_h,
            dentil_w_mm=props.dentil_width_mm,
            dentil_d_mm=props.dentil_depth_mm,
            dentil_h_mm=props.dentil_height_mm,
            dentil_spacing_mm=props.dentil_spacing_mm,
            at_top=(props.dentil_position == "TOP"),
            mesh_name="Plinth_DentilCourseMesh_v3_3",
        )
        obj_dentil = add_helper_boolean_object(coll, mesh_dentil, "Plinth_DentilCourse_v3_3", props.show_cutters)
        add_boolean_union_modifier(main_obj, obj_dentil, "DentilUnion")

    # SCALLOPED SKIRT
    if props.scallop_enabled:
        mesh_scallop = make_scallop_cutters_mesh(
            shape=props.shape,
            width_mm=props.width_mm,
            length_mm=props.length_mm,
            diameter_mm=props.diameter_mm,
            scallop_count=props.scallop_count,
            scallop_radius_mm=props.scallop_radius_mm,
            scallop_depth_mm=props.scallop_depth_mm,
            scallop_z_mm=props.scallop_z_mm,
            mesh_name="Plinth_ScallopCuttersMesh_v3_3",
        )
        obj_scallop = add_helper_boolean_object(coll, mesh_scallop, "Plinth_ScallopCutters_v3_3", props.show_cutters)
        add_boolean_modifier(main_obj, obj_scallop, "ScallopCut")

    # CORNER BOSSES / MEDALLIONS
    if props.bosses_enabled:
        mesh_boss = make_bosses_mesh(
            shape=props.shape,
            width_mm=props.width_mm,
            length_mm=props.length_mm,
            diameter_mm=props.diameter_mm,
            boss_shape=props.boss_shape,
            boss_size_mm=props.boss_size_mm,
            boss_relief_mm=props.boss_relief_mm,
            boss_inset_mm=props.boss_inset_mm,
            boss_count_cyl=props.boss_count_cyl,
            boss_z_ratio=props.boss_z_ratio,
            height_mm=body_h,
            mesh_name="Plinth_BossesMesh_v3_3",
        )
        obj_boss = add_helper_boolean_object(coll, mesh_boss, "Plinth_Bosses_v3_3", props.show_cutters)
        add_boolean_union_modifier(main_obj, obj_boss, "BossUnion")

    # NAMEPLATE RECESS
    if props.nameplate_enabled:
        mesh_nameplate = make_nameplate_cutter_mesh(
            shape=props.shape,
            width_mm=props.width_mm,
            length_mm=props.length_mm,
            diameter_mm=props.diameter_mm,
            height_mm=body_h,
            plate_w_mm=props.nameplate_width_mm,
            plate_h_mm=props.nameplate_height_mm,
            plate_d_mm=props.nameplate_depth_mm,
            plate_side=props.nameplate_side,
            plate_z_ratio=props.nameplate_z_ratio,
            mesh_name="Plinth_NameplateCutterMesh_v3_3",
        )
        obj_nameplate = add_helper_boolean_object(coll, mesh_nameplate, "Plinth_NameplateCutter_v3_3", props.show_cutters)
        add_boolean_modifier(main_obj, obj_nameplate, "NameplateCut")

    # FOOT PADS / BUN FEET
    if props.feet_enabled:
        mesh_feet = make_feet_mesh(
            shape=props.shape,
            width_mm=props.width_mm,
            length_mm=props.length_mm,
            diameter_mm=props.diameter_mm,
            feet_type=props.feet_type,
            feet_radius_mm=props.feet_radius_mm,
            feet_height_mm=props.feet_height_mm,
            feet_inset_mm=props.feet_inset_mm,
            feet_count_cyl=props.feet_count_cyl,
            mesh_name="Plinth_FeetMesh_v3_3",
        )
        obj_feet = add_helper_boolean_object(coll, mesh_feet, "Plinth_Feet_v3_3", props.show_cutters)
        add_boolean_union_modifier(main_obj, obj_feet, "FeetUnion")

    # Keep functional holes as late-stage cuts so additive decorations do not refill them.
    for mod_name in ("DrainCut", "DrainAtMagnetCenters", "MagnetCut"):
        move_modifier_to_end(main_obj, mod_name)

    # PREVIEW (export this)
    if props.preview_cuts_duplicate:
        preview = main_obj.copy()
        preview.data = main_obj.data.copy()
        preview.name = OBJ_PREVIEW
        coll.objects.link(preview)

        modifier_failures = apply_all_modifiers(preview)
        if modifier_failures:
            print(f"[PlinthGen] WARNING: {len(modifier_failures)} modifier(s) failed on preview: {modifier_failures}")
        ground_mesh_to_z0(preview.data)

        if props.texture_enabled and props.texture_strength_mm > 0.0:
            apply_surface_texture_stamp(
                preview.data,
                shape=props.shape,
                strength_mm=props.texture_strength_mm,
                scale_mm=props.texture_scale_mm,
                seed=props.texture_seed,
                zone=props.texture_zone,
                width_mm=body_w,
                length_mm=body_l,
            )
            ground_mesh_to_z0(preview.data)

        remesh_used = False
        if props.manifold_guarantee:
            remesh_used = manifold_guarantee_on_preview(preview, voxel_size_mm=props.voxel_size_mm)
            ground_mesh_to_z0(preview.data)
            if remesh_used and post_remesh_functional_cutters:
                # Restore crisp functional holes after voxel remesh.
                for idx, cutter_obj in enumerate(post_remesh_functional_cutters):
                    add_boolean_modifier(preview, cutter_obj, f"PostRemeshFunctionalCut_{idx + 1}")
                post_failures = apply_all_modifiers(preview)
                if post_failures:
                    print(f"[PlinthGen] WARNING: post-remesh modifier(s) failed: {post_failures}")
                bm_cleanup_and_normals(preview.data, merge_dist_mm=MERGE_DIST_MM)
                ground_mesh_to_z0(preview.data)

        if props.health_check_enabled:
            health = evaluate_preview_mesh_health(
                preview.data,
                degenerate_area_mm2=props.health_degenerate_area_mm2,
            )
            store_health_report(props, health, remesh_used=remesh_used)

            if props.health_block_preview_on_fail and not health["passed"]:
                preview.hide_set(True)
                preview.hide_render = True
                main_obj.hide_set(False)
                main_obj.hide_render = False
                preview.select_set(False)
                bpy.context.view_layer.objects.active = main_obj
                main_obj.select_set(True)
                preview_blocked = True
                preview_block_message = f"Preview blocked by health check: {props.health_last_summary}"
        else:
            reset_health_report(props, summary="Health check disabled.")

        # hide driver
        if not preview_blocked:
            main_obj.hide_set(True)
            main_obj.hide_render = True
            bpy.context.view_layer.objects.active = preview
            preview.select_set(True)
    else:
        reset_health_report(props, summary="Health check requires Preview Cuts (Duplicate).")
        bpy.context.view_layer.objects.active = main_obj
        main_obj.select_set(True)

    purge_orphans()
    return preview_blocked, preview_block_message


# -----------------------------
# Operators
# -----------------------------
def _execute_build(op: bpy.types.Operator, context) -> set:
    """Shared implementation for Create and Rebuild operators."""
    props = getattr(context.scene, PROP_NAME)
    errors, warnings = preflight_validate(props)
    if not preflight_report_to_operator(op, errors, warnings):
        return {"CANCELLED"}
    delete_plinthgen_objects_only()
    ensure_units_mm()
    preview_blocked, block_message = build_plinth(context, props)
    if preview_blocked:
        op.report({'ERROR'}, block_message)
    return {"FINISHED"}


class PLINTHGEN_OT_create(bpy.types.Operator):
    bl_idname = "plinthgen.create_v3_3"
    bl_label = "Create Plinth v3.3"
    bl_description = "Generate a new parametric plinth from current settings (removes previous plinth)"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.scene is not None and context.mode == 'OBJECT'

    def execute(self, context):
        return _execute_build(self, context)


class PLINTHGEN_OT_rebuild(bpy.types.Operator):
    bl_idname = "plinthgen.rebuild_v3_3"
    bl_label = "Force Rebuild"
    bl_description = "Rebuild the plinth from scratch using current settings"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.scene is not None and context.mode == 'OBJECT'

    def execute(self, context):
        return _execute_build(self, context)


class PLINTHGEN_OT_export_stl(bpy.types.Operator):
    bl_idname = "plinthgen.export_stl_v3_3"
    bl_label = "Export Plinth STL"
    bl_description = "Export the preview mesh as an STL file for 3D printing"
    bl_options = {"REGISTER"}

    filepath: bpy.props.StringProperty(subtype='FILE_PATH', default="plinth.stl")
    filter_glob: bpy.props.StringProperty(default="*.stl", options={"HIDDEN"})

    @classmethod
    def poll(cls, context):
        return bpy.data.objects.get(OBJ_PREVIEW) is not None

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        import os

        preview = bpy.data.objects.get(OBJ_PREVIEW)
        if not preview:
            self.report({'ERROR'}, "No preview mesh found. Run Create/Rebuild first.")
            return {"CANCELLED"}

        # Warn if health check failed
        props = getattr(context.scene, PROP_NAME)
        if props.health_last_ran and not props.health_last_pass:
            self.report({'WARNING'}, f"Exporting despite health check failure: {props.health_last_summary}")

        # Ensure only the preview is selected for export
        bpy.ops.object.select_all(action='DESELECT')
        preview.select_set(True)
        context.view_layer.objects.active = preview

        filepath = self.filepath
        if not filepath.lower().endswith(".stl"):
            filepath += ".stl"

        try:
            bpy.ops.wm.stl_export(
                filepath=filepath,
                export_selected_objects=True,
                global_scale=1.0,
                ascii_format=False,
            )
            self.report({'INFO'}, f"Exported: {os.path.basename(filepath)}")
        except Exception as exc:
            # Fallback for older Blender versions that use the legacy exporter
            try:
                bpy.ops.export_mesh.stl(
                    filepath=filepath,
                    use_selection=True,
                    global_scale=1.0,
                    ascii=False,
                )
                self.report({'INFO'}, f"Exported: {os.path.basename(filepath)}")
            except Exception as exc2:
                self.report({'ERROR'}, f"STL export failed: {exc2}")
                return {"CANCELLED"}

        return {"FINISHED"}


# -----------------------------
# UI Panel
# -----------------------------
class PLINTHGEN_PT_panel(bpy.types.Panel):
    bl_label = "Plinth v3.3"
    bl_idname = "PLINTHGEN_PT_panel_v3_3"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Plinth v3.3"

    def draw(self, context):
        layout = self.layout
        p = getattr(context.scene, PROP_NAME)
        errors, warnings = preflight_validate(p)

        # Health status banner (prominent, at top)
        if p.health_last_ran:
            if p.health_last_pass:
                hb = layout.row()
                hb.label(text="Mesh Health: PASS", icon="CHECKMARK")
            else:
                hb = layout.box()
                hb.alert = True
                hb.label(text=f"Mesh Health: {p.health_last_summary}", icon="ERROR")
                if p.health_last_remesh_used:
                    hb.label(text="Voxel remesh was applied.", icon="INFO")

        row = layout.row(align=True)
        row.operator("plinthgen.create_v3_3", text="Create", icon="MESH_CUBE")
        row.operator("plinthgen.rebuild_v3_3", text="Force Rebuild", icon="FILE_REFRESH")
        row2 = layout.row(align=True)
        row2.operator("plinthgen.export_stl_v3_3", text="Export STL", icon="EXPORT")

        layout.separator()
        layout.prop(p, "shape")

        pf = layout.box()
        pf.label(text="Preflight")
        if not errors and not warnings:
            pf.label(text="No issues detected.", icon="CHECKMARK")
        else:
            for msg in errors[:5]:
                pf.label(text=msg, icon="ERROR")
            if len(errors) > 5:
                pf.label(text=f"... and {len(errors) - 5} more error(s).", icon="ERROR")
            for msg in warnings[:5]:
                pf.label(text=msg, icon="INFO")
            if len(warnings) > 5:
                pf.label(text=f"... and {len(warnings) - 5} more warning(s).", icon="INFO")

        dims = layout.box()
        dims.label(text="Dimensions")
        dims.prop(p, "unit_input")
        if p.shape == "BOX":
            if p.unit_input == "IN":
                dims.prop(p, "width_in")
                dims.label(text=f"Width: {p.width_mm:.3f} mm")
                dims.prop(p, "length_in")
                dims.label(text=f"Length: {p.length_mm:.3f} mm")
                dims.prop(p, "height_in")
                dims.label(text=f"Height: {p.height_mm:.3f} mm")
            else:
                dims.prop(p, "width_mm")
                dims.prop(p, "length_mm")
                dims.prop(p, "height_mm")
        else:
            if p.unit_input == "IN":
                dims.prop(p, "diameter_in")
                dims.label(text=f"Diameter: {p.diameter_mm:.3f} mm")
                dims.prop(p, "cyl_height_in")
                dims.label(text=f"Height: {p.cyl_height_mm:.3f} mm")
            else:
                dims.prop(p, "diameter_mm")
                dims.prop(p, "cyl_height_mm")
            dims.prop(p, "cyl_segments")

        sl = layout.box()
        sl.label(text="Slope (Top Only)")
        sl.prop(p, "slope_enabled")
        col = sl.column()
        col.enabled = p.slope_enabled
        col.prop(p, "slope_delta_mm")
        col.prop(p, "slope_axis")
        col.prop(p, "slope_high_side")

        ho = layout.box()
        ho.label(text="Hollow")
        ho.prop(p, "hollow_enabled")
        col = ho.column()
        col.enabled = p.hollow_enabled
        col.prop(p, "sealed_bottom")
        col.prop(p, "wall_thickness_mm")
        col.prop(p, "top_thickness_mm")
        col2 = col.column()
        col2.enabled = p.sealed_bottom
        col2.prop(p, "bottom_thickness_mm")
        ho.label(text=f"Magnet clamp margin: {MAGNET_CLAMP_MARGIN_MM}mm (sealed bottom)")

        bt = layout.box()
        bt.label(text="Base Trim")
        bt.prop(p, "base_trim_enabled")
        col = bt.column()
        col.enabled = p.base_trim_enabled
        col.prop(p, "base_trim_radius_mm")
        col.prop(p, "base_trim_segments")

        deco = layout.box()
        deco.label(text="Decorations")

        p1 = deco.box()
        p1.label(text="1) Ogee / Cove / Convex Band")
        p1.prop(p, "profile_band_enabled")
        col = p1.column()
        col.enabled = p.profile_band_enabled
        col.prop(p, "profile_band_style")
        col.prop(p, "profile_band_position")
        col.prop(p, "profile_band_height_mm")
        col.prop(p, "profile_band_depth_mm")
        col.prop(p, "profile_band_segments")

        p2 = deco.box()
        p2.label(text="2) Stepped Layers")
        p2.prop(p, "steps_enabled")
        col = p2.column()
        col.enabled = p.steps_enabled
        col.prop(p, "steps_count")
        col.prop(p, "steps_height_mm")
        col.prop(p, "steps_offset_mm")
        col.prop(p, "steps_position")

        p3 = deco.box()
        p3.label(text="3) Vertical Fluting")
        p3.prop(p, "fluting_enabled")
        col = p3.column()
        col.enabled = p.fluting_enabled
        col.prop(p, "fluting_count")
        col.prop(p, "fluting_width_mm")
        col.prop(p, "fluting_depth_mm")
        col.prop(p, "fluting_z_margin_mm")

        p4 = deco.box()
        p4.label(text="4) Recessed Side Panels")
        p4.prop(p, "panels_enabled")
        col = p4.column()
        col.enabled = p.panels_enabled
        col.prop(p, "panel_depth_mm")
        col.prop(p, "panel_border_mm")
        col.prop(p, "panel_height_ratio")
        if p.shape == "CYL":
            col.prop(p, "panel_count_cyl")

        p5 = deco.box()
        p5.label(text="5) Bead Border")
        p5.prop(p, "beads_enabled")
        col = p5.column()
        col.enabled = p.beads_enabled
        col.prop(p, "bead_size_mm")
        col.prop(p, "bead_spacing_mm")
        col.prop(p, "bead_rows")
        col.prop(p, "bead_position")

        p6 = deco.box()
        p6.label(text="6) Rope Twist Band")
        p6.prop(p, "rope_enabled")
        col = p6.column()
        col.enabled = p.rope_enabled
        col.prop(p, "rope_dia_mm")
        col.prop(p, "rope_pitch_mm")
        col.prop(p, "rope_position")

        p7 = deco.box()
        p7.label(text="7) Dentil Course")
        p7.prop(p, "dentil_enabled")
        col = p7.column()
        col.enabled = p.dentil_enabled
        col.prop(p, "dentil_width_mm")
        col.prop(p, "dentil_depth_mm")
        col.prop(p, "dentil_height_mm")
        col.prop(p, "dentil_spacing_mm")
        col.prop(p, "dentil_position")

        p8 = deco.box()
        p8.label(text="8) Scalloped Skirt")
        p8.prop(p, "scallop_enabled")
        col = p8.column()
        col.enabled = p.scallop_enabled
        col.prop(p, "scallop_count")
        col.prop(p, "scallop_radius_mm")
        col.prop(p, "scallop_depth_mm")
        col.prop(p, "scallop_z_mm")

        p9 = deco.box()
        p9.label(text="9) Corner Bosses / Medallions")
        p9.prop(p, "bosses_enabled")
        col = p9.column()
        col.enabled = p.bosses_enabled
        col.prop(p, "boss_shape")
        col.prop(p, "boss_size_mm")
        col.prop(p, "boss_relief_mm")
        col.prop(p, "boss_inset_mm")
        col.prop(p, "boss_z_ratio")
        if p.shape == "CYL":
            col.prop(p, "boss_count_cyl")

        p10 = deco.box()
        p10.label(text="10) Nameplate Recess")
        p10.prop(p, "nameplate_enabled")
        col = p10.column()
        col.enabled = p.nameplate_enabled
        col.prop(p, "nameplate_width_mm")
        col.prop(p, "nameplate_height_mm")
        col.prop(p, "nameplate_depth_mm")
        if p.shape == "BOX":
            col.prop(p, "nameplate_side")
        col.prop(p, "nameplate_z_ratio")

        p11 = deco.box()
        p11.label(text="11) Surface Texture Stamp")
        p11.prop(p, "texture_enabled")
        col = p11.column()
        col.enabled = p.texture_enabled
        col.prop(p, "texture_strength_mm")
        col.prop(p, "texture_scale_mm")
        col.prop(p, "texture_seed")
        col.prop(p, "texture_zone")

        p12 = deco.box()
        p12.label(text="12) Foot Pads / Bun Feet")
        p12.prop(p, "feet_enabled")
        col = p12.column()
        col.enabled = p.feet_enabled
        col.prop(p, "feet_type")
        col.prop(p, "feet_radius_mm")
        col.prop(p, "feet_height_mm")
        col.prop(p, "feet_inset_mm")
        if p.shape == "CYL":
            col.prop(p, "feet_count_cyl")

        mg = layout.box()
        mg.label(text="Magnets")
        mg.prop(p, "magnets_count")
        if p.shape == "BOX":
            mg.prop(p, "magnet_layout_box")
        mg.prop(p, "magnet_dia_mm")
        mg.prop(p, "magnet_hole_depth_mm")
        mg.prop(p, "dia_tol_mm")
        mg.prop(p, "depth_tol_mm")
        mg.prop(p, "inset_mm")

        dr = layout.box()
        dr.label(text="Drain / Vent Holes (Resin)")
        dr.prop(p, "drain_enabled")
        col = dr.column()
        col.enabled = p.drain_enabled and p.hollow_enabled
        col.prop(p, "drain_count")
        col.prop(p, "drain_dia_mm")
        col.prop(p, "drain_inset_mm")
        col.prop(p, "drain_at_magnet_centers")
        col2 = col.column()
        col2.enabled = p.drain_at_magnet_centers and p.sealed_bottom and p.magnets_count > 0
        col2.prop(p, "magnet_center_drain_dia_mm")
        col.prop(p, "avoid_overlap_enabled")
        col3 = col.column()
        col3.enabled = p.avoid_overlap_enabled
        col3.prop(p, "overlap_safety_mm")

        mf = layout.box()
        mf.label(text="Manifold Guarantee (Preview)")
        mf.prop(p, "manifold_guarantee")
        col = mf.column()
        col.enabled = p.manifold_guarantee
        col.prop(p, "voxel_size_mm")
        mf.label(text="Voxel remesh runs ONLY if preview isn't watertight.")

        hc = layout.box()
        hc.label(text="Post-Build Health Check")
        hc.prop(p, "health_check_enabled")
        col = hc.column()
        col.enabled = p.health_check_enabled
        col.prop(p, "health_block_preview_on_fail")
        col.prop(p, "health_degenerate_area_mm2")

        if p.health_last_ran:
            if p.health_last_pass:
                hc.label(text="Status: PASS", icon="CHECKMARK")
            else:
                hc.label(text=f"Status: {p.health_last_summary}", icon="ERROR")
            hc.label(text=f"Watertight: {'Yes' if p.health_last_watertight else 'No'}")
            hc.label(text=f"Non-manifold edges: {p.health_last_non_manifold_edges}")
            hc.label(text=f"Loose edges/verts: {p.health_last_loose_edges}/{p.health_last_loose_verts}")
            hc.label(text=f"Degenerate faces: {p.health_last_degenerate_faces}")
            hc.label(text=f"Face islands: {p.health_last_components}")
            if p.health_last_inverted_normals:
                hc.label(text="Inverted normals detected.", icon="ERROR")
            if p.health_last_remesh_used:
                hc.label(text="Voxel remesh was applied by manifold guarantee.", icon="INFO")
        else:
            hc.label(text=p.health_last_summary, icon="INFO")

        vd = layout.box()
        vd.label(text="Visual / Debug")
        vd.prop(p, "show_cutters")
        vd.prop(p, "preview_cuts_duplicate")


# -----------------------------
# Register
# -----------------------------
classes = (
    PlinthGenProps,
    PLINTHGEN_OT_create,
    PLINTHGEN_OT_rebuild,
    PLINTHGEN_OT_export_stl,
    PLINTHGEN_PT_panel,
)


def register():
    for c in classes:
        bpy.utils.register_class(c)
    setattr(bpy.types.Scene, PROP_NAME, bpy.props.PointerProperty(type=PlinthGenProps))


def unregister():
    if hasattr(bpy.types.Scene, PROP_NAME):
        delattr(bpy.types.Scene, PROP_NAME)
    for c in reversed(classes):
        bpy.utils.unregister_class(c)


if __name__ == "__main__":
    register()
