# Code Review: Parametric Plinth Generator v3.4

**Reviewed**: April 7, 2026
**File**: `addon/plinth_generator_v3_4.py` (3,211 lines)
**Target**: Blender 5.0.0
**Goal**: Product readiness for commercial sale

---

## Critical Issues (Fix Before Selling)

### 1. Modifier Apply Can Fail Silently — Corrupted Exports

**Lines 1201-1214 (`apply_all_modifiers`)**

The function uses `bpy.ops.object.modifier_apply()` in a loop, but if any single modifier fails (e.g., boolean solver error on complex geometry), the exception is not caught per-modifier. The `try/finally` only ensures `select_set(False)` runs — it does NOT detect or report failed modifiers.

**Impact**: A customer exports the preview mesh thinking booleans were applied, but one or more modifiers silently failed. The exported STL has unapplied cuts (solid where hollow should be, missing magnet holes, etc.). They waste resin/filament printing a bad part.

**Same pattern at line 1312** (`apply_voxel_remesh`) — no validation that the remesh actually produced valid output.

### 2. Default Settings Let Bad Geometry Through

**Line 1786: `health_block_preview_on_fail` defaults to `False`**

The health check runs and may report FAIL, but the preview mesh is still visible and exportable. Most customers won't notice a small "Status: FAIL" label buried at the bottom of a long panel. They'll export and print non-watertight geometry.

**Recommendation**: Default this to `True`, or at minimum surface the health status prominently at the top of the panel near the Create/Rebuild buttons.

### 3. No Export Operator

The addon generates geometry but provides no export button. Customers must navigate `File > Export > STL` themselves. Every competing paid Blender addon for 3D printing includes a one-click export. This is a major UX gap for a commercial product.

### 4. `delete_mesh_objects_only()` Deletes ALL Mesh Objects in Scene

**Lines 70-74, called at lines 2568 and 2588**

```python
def delete_mesh_objects_only():
    for obj in list(bpy.context.scene.objects):
        if obj.type == "MESH":
            bpy.data.objects.remove(obj, do_unlink=True)
```

Both `Create` and `Force Rebuild` call this function, which **removes every mesh object in the entire scene** — not just plinth objects. If a customer has other meshes in their scene (reference models, a figure they're building a plinth for, etc.), clicking "Create" destroys them with no warning.

**This is the single most dangerous bug for customer trust.** One accidental click and their work is gone.

---

## Medium Issues (Should Fix)

### 5. `apply_all_modifiers` Context Fragility

**Lines 1201-1214**

The function manipulates `view_layer.objects.active` and `obj.select_set()` without restoring the previous state. If called from a context where another object was active, that state is lost. Combined with `bpy.ops.object.mode_set()` at line 1204, this is fragile — if Blender is in Edit Mode on a different object, the mode_set may affect the wrong object.

### 6. `apply_voxel_remesh` Uses `select_all(action='DESELECT')`

**Line 1301**

This deselects ALL objects in the scene as a side effect. If the user had a selection they cared about, it's gone after a rebuild.

### 7. Magnet Holes Silently Disabled by Depth Clamping

**Lines 2125-2158**

When hollow + sealed bottom is enabled, magnet depth is clamped to `bottom_thickness - 0.5mm`. If bottom thickness is 0.5mm or less, `max_safe` becomes 0 and magnets are completely disabled with no operator-level error — only a preflight warning that customers may dismiss.

The code at line 2157-2158 silently empties `magnet_pts = []`, meaning the user gets zero magnet holes with no clear feedback in the generated geometry.

### 8. Drain Fallback to Center Can Conflict with Magnets

**Lines 2183-2185**

When all drain positions are filtered out due to magnet overlap, the fallback is a single drain at `(0.0, 0.0)`. But if count=1 magnets also places at `(0.0, 0.0)` (lines 1051-1052, 1095-1096, 1112-1113), the drain overlaps with a magnet — the exact thing the overlap avoidance was trying to prevent.

### 9. `PLINTHGEN_OT_create` and `PLINTHGEN_OT_rebuild` Are Identical

**Lines 2558-2591**

Both operators have the exact same `execute()` body. This is confusing for users ("what's the difference?") and adds maintenance burden. If they're meant to be identical, one should call the other or they should be merged.

### 10. `preflight_validate` Runs on Every Panel Draw

**Line 2608**

```python
def draw(self, context):
    ...
    errors, warnings = preflight_validate(p)
```

The preflight validator is called every time the panel redraws (mouse hover, property change, viewport navigation, etc.). While the function is lightweight, it's doing floating-point math and string formatting on every draw call. This is poor Blender panel practice and can cause micro-stutters on complex scenes.

### 11. No Operator `poll()` Methods

**Lines 2558-2591**

Neither operator defines a `poll()` classmethod. Best practice is to check that the context is valid (e.g., correct mode, scene exists) before allowing the button to be clicked. Without this, the operator can be invoked in invalid contexts (e.g., from a script while in Edit Mode).

### 12. Box Face Winding May Be Inconsistent

**Lines 154-183 (`make_box_mesh`)**

The bottom face is wound `(v0, v1, v2, v3)` and the top face `(v4, v5, v6, v7)`. For consistent outward-facing normals on a box, one face should be CW and the other CCW when viewed from outside. The current winding produces inward normals on either the top or bottom face. While `bm.normal_update()` at line 179 should fix this, if it doesn't fully recalculate (which can happen with non-manifold intermediate states), the health check will report inverted normals.

---

## Lower Priority (Nice to Fix)

### 13. No `bl_description` on Operators

Users who hover over buttons see no tooltip explaining what "Create" vs "Force Rebuild" does.

### 14. Hardcoded Segment Counts in Various Functions

Lines 560, 697, 769, 806, 877, etc. use hardcoded segment values (12, 16, 20, etc.) instead of deriving them from a user-controllable property. This limits customer control over mesh density.

### 15. `purge_orphans()` Swallows All Exceptions

**Lines 55-59**

```python
def purge_orphans():
    try:
        bpy.ops.outliner.orphans_purge(do_recursive=True)
    except Exception:
        pass
```

If orphan purging fails, the user accumulates dead data-blocks with no indication. Over many rebuilds, this can bloat the .blend file.

### 16. `build_plinth()` is 506 Lines Long

The main build function (lines 2046-2552) handles everything from hollow cutters to decorative features to health checks. This makes it very hard to debug or extend. Breaking it into `_build_base()`, `_build_decorations()`, `_build_functional_cuts()`, `_apply_postprocessing()` would improve maintainability significantly.

### 17. Unit Sync Lock Uses a Blender Property

**Line 1538**

```python
unit_sync_lock: bpy.props.BoolProperty(default=False, options={"HIDDEN"})
```

Using a Blender property for a mutex-like lock means it's saved in the .blend file and participates in undo. A plain Python class attribute or module-level variable would be more appropriate.

### 18. No Version Migration / Compatibility

If a customer saves a .blend with v3.4 properties and later installs v3.5, there's no migration code to handle renamed/removed/added properties. This will cause `AttributeError` crashes on file load.

### 19. Performance: High-Detail Decorations Create Massive Meshes

Rope bands, bead borders, and dentil courses each create individual geometry primitives (cylinders, spheres) per instance. A plinth with beads + rope + dentils could easily generate 10,000+ individual primitives merged into a single bmesh, then boolean-unioned. This can take minutes on modest hardware with no progress indicator.

### 20. `__pycache__` Committed to Git

**File**: `addon/__pycache__/plinth_generator_v3_4.cpython-311.pyc`

Compiled Python bytecode is in the repo. This should be in `.gitignore`.

---

## Summary

| Priority | Count | Key Themes |
|----------|-------|------------|
| Critical | 4 | Scene data destruction, silent export corruption, no export button, bad defaults |
| Medium | 8 | Context fragility, silent feature disabling, UX confusion, API practices |
| Lower | 8 | Maintainability, performance, file hygiene |

**The #1 issue is `delete_mesh_objects_only()` — it will destroy customer work.** This alone could generate refund requests and bad reviews. The fix is straightforward: only delete objects that belong to the plinth generator (by name prefix or collection membership).

**The #2 priority is adding an export operator and making the health check more visible.** Customers are paying for a streamlined 3D-printing workflow; making them manually export and manually check mesh health undermines the value proposition.
