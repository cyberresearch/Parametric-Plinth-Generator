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


def delete_mesh_objects_only():
    """Delete mesh objects only (keeps cameras/lights/empties)."""
    for obj in list(bpy.context.scene.objects):
        if obj.type == "MESH":
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

    bm.faces.new((v0, v1, v2, v3))
    bm.faces.new((v4, v5, v6, v7))
    bm.faces.new((v0, v1, v5, v4))
    bm.faces.new((v1, v2, v6, v5))
    bm.faces.new((v2, v3, v7, v6))
    bm.faces.new((v3, v0, v4, v7))

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
    """Build half-round trim from four horizontal cylinders on the side walls."""
    mesh = bpy.data.meshes.new(mesh_name)
    bm = bmesh.new()

    r = max(0.1, float(radius_mm))
    seg = max(12, int(segments))

    def add_rod(depth_mm: float, center_xyz, axis: str):
        res = bmesh.ops.create_cone(
            bm,
            cap_ends=True,
            cap_tris=False,
            segments=seg,
            radius1=r,
            radius2=r,
            depth=max(0.1, float(depth_mm)),
        )
        rod_verts = list(res["verts"])
        if axis == "X":
            rot = Matrix.Rotation(math.pi * 0.5, 3, "Y")
        else:
            rot = Matrix.Rotation(-math.pi * 0.5, 3, "X")
        bmesh.ops.rotate(bm, verts=rod_verts, cent=Vector((0.0, 0.0, 0.0)), matrix=rot)
        bmesh.ops.translate(bm, verts=rod_verts, vec=Vector(center_xyz))

    half_w = width_mm * 0.5
    half_l = length_mm * 0.5
    zc = r

    add_rod(width_mm, (0.0, half_l, zc), axis="X")
    add_rod(width_mm, (0.0, -half_l, zc), axis="X")
    add_rod(length_mm, (half_w, 0.0, zc), axis="Y")
    add_rod(length_mm, (-half_w, 0.0, zc), axis="Y")

    bm.normal_update()
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()
    return mesh


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


def apply_all_modifiers(obj: bpy.types.Object):
    view_layer = bpy.context.view_layer
    try:
        if bpy.context.object and bpy.context.object.mode != 'OBJECT' and bpy.ops.object.mode_set.poll():
            bpy.ops.object.mode_set(mode='OBJECT')
    except Exception:
        pass
    view_layer.objects.active = obj
    obj.select_set(True)
    try:
        for m in list(obj.modifiers):
            bpy.ops.object.modifier_apply(modifier=m.name)
    finally:
        obj.select_set(False)


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


def apply_voxel_remesh(obj: bpy.types.Object, voxel_size_mm: float):
    """Apply voxel remesh modifier (context op)."""
    try:
        if bpy.context.object and bpy.context.object.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
    except Exception:
        pass

    view_layer = bpy.context.view_layer
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    view_layer.objects.active = obj

    mod = obj.modifiers.new(name="VOXEL_REMESH_GUARANTEE", type='REMESH')
    mod.mode = 'VOXEL'
    mod.voxel_size = max(0.01, float(voxel_size_mm))  # mm because 1BU=1mm
    mod.use_smooth_shade = False
    mod.use_remove_disconnected = False
    mod.adaptivity = 0.0

    bpy.ops.object.modifier_apply(modifier=mod.name)


def manifold_guarantee_on_preview(preview_obj: bpy.types.Object, voxel_size_mm: float) -> bool:
    """Run cleanup and optional voxel remesh. Returns True if remesh was applied."""
    remeshed = False
    bm_cleanup_and_normals(preview_obj.data, merge_dist_mm=MERGE_DIST_MM)
    if not mesh_is_watertight(preview_obj.data):
        apply_voxel_remesh(preview_obj, voxel_size_mm=voxel_size_mm)
        remeshed = True
        bm_cleanup_and_normals(preview_obj.data, merge_dist_mm=MERGE_DIST_MM)
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
# Properties
# -----------------------------
class PlinthGenProps(bpy.types.PropertyGroup):
    shape: bpy.props.EnumProperty(
        name="Plinth Type",
        items=[("BOX", "Box / Rectangle", ""), ("CYL", "Cylinder", "")],
        default="BOX",
    )

    # Box dims
    width_mm: bpy.props.FloatProperty(name="Width (mm)", default=76.2, min=1.0)
    length_mm: bpy.props.FloatProperty(name="Length (mm)", default=88.9, min=1.0)
    height_mm: bpy.props.FloatProperty(name="Height (mm)", default=57.15, min=1.0)

    # Cylinder dims
    diameter_mm: bpy.props.FloatProperty(name="Diameter (mm)", default=76.2, min=1.0)
    cyl_height_mm: bpy.props.FloatProperty(name="Height (mm)", default=57.15, min=1.0)
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
        default=False,
        description="Hide preview/export mesh when health check fails.",
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

            # If all drains are filtered out, place one at center as fallback.
            if not drain_pts:
                drain_pts = [(0.0, 0.0)]

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

    # PREVIEW (export this)
    if props.preview_cuts_duplicate:
        preview = main_obj.copy()
        preview.data = main_obj.data.copy()
        preview.name = OBJ_PREVIEW
        coll.objects.link(preview)

        apply_all_modifiers(preview)
        ground_mesh_to_z0(preview.data)

        remesh_used = False
        if props.manifold_guarantee:
            remesh_used = manifold_guarantee_on_preview(preview, voxel_size_mm=props.voxel_size_mm)
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
class PLINTHGEN_OT_create(bpy.types.Operator):
    bl_idname = "plinthgen.create_v3_3"
    bl_label = "Create Plinth v3.3"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        props = getattr(context.scene, PROP_NAME)
        errors, warnings = preflight_validate(props)
        if not preflight_report_to_operator(self, errors, warnings):
            return {"CANCELLED"}
        delete_mesh_objects_only()
        ensure_units_mm()
        preview_blocked, block_message = build_plinth(context, props)
        if preview_blocked:
            self.report({'ERROR'}, block_message)
        return {"FINISHED"}


class PLINTHGEN_OT_rebuild(bpy.types.Operator):
    bl_idname = "plinthgen.rebuild_v3_3"
    bl_label = "Force Rebuild"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        props = getattr(context.scene, PROP_NAME)
        errors, warnings = preflight_validate(props)
        if not preflight_report_to_operator(self, errors, warnings):
            return {"CANCELLED"}
        delete_mesh_objects_only()
        ensure_units_mm()
        preview_blocked, block_message = build_plinth(context, props)
        if preview_blocked:
            self.report({'ERROR'}, block_message)
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

        row = layout.row(align=True)
        row.operator("plinthgen.create_v3_3", text="Create", icon="MESH_CUBE")
        row.operator("plinthgen.rebuild_v3_3", text="Force Rebuild", icon="FILE_REFRESH")

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
        if p.shape == "BOX":
            dims.prop(p, "width_mm")
            dims.prop(p, "length_mm")
            dims.prop(p, "height_mm")
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
