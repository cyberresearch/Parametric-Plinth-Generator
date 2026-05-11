# Fix Queue — v1.0 Ship Readiness

> **Derived from**: `CODE_REVIEW.md` (April 7, 2026) + baseline harness run on Blender 5.0.1 (39/39 PASS).
> **Owner**: Justin Sharp.
> **Status**: Phase 2 + critical-fix Phase 3 complete. See `CODE_REVIEW.md` for per-item resolution SHAs and `FUTURE_WORK.md` for deferred medium items.

The baseline harness shows zero failures, so buckets 1 and 3 from the handoff
("issues that also break the harness") are empty. Every entry below is a
known-risk item that the harness does not currently exercise — most fixes will
require **adding a new harness case** before implementing the fix, per the
TDD-style protocol in Phase 3 of `HANDOFF.md`.

Test ID conventions:
- **Existing** — harness case already exists and is expected to keep passing.
- **New** — case to be added as part of the fix.
- **N/A** — issue is not headlessly testable (UX placement, tooltip text, performance feel).

---

## Bucket 2 — Critical issues, no harness coverage (customer risk)

Order matches `HANDOFF.md` Phase 3 suggested order.

### 1. CR-#4 — `delete_mesh_objects_only()` destroys all scene meshes

- **One-liner**: `Create` and `Force Rebuild` call a helper that removes every mesh in the scene, not just plinth-owned objects.
- **Related tests**: T18 (existing, covers the *cancelled* path only). **New**: a case that places a non-plinth cube in the scene, runs a successful `Create`, and asserts the cube survives.
- **Fix approach**: Tag plinth-owned objects on creation (custom property like `["plinthgen_owned"] = True` or a name prefix `Plinth_*`), and have `delete_mesh_objects_only()` filter on that tag. A dedicated `Plinth` collection is a viable alternative but adds visible scene clutter — prefer the custom-property approach unless owner prefers collections.

**Status**: RESOLVED — see CODE_REVIEW.md.

### 2. CR-#3 — No STL export operator

- **One-liner**: Customers must use Blender's native `File > Export > STL` themselves; no one-click export.
- **Related tests**: T29 (existing) assumes the export operator exists and is blocked by failed health. Currently passes because the operator stub blocks correctly, but full export behavior is untested. **New**: a case that runs `Create` with a passing health check, invokes export, and asserts a valid `.stl` is written to a tempdir.
- **Fix approach**: Add `PLINTHGEN_OT_export_stl` with a file dialog. Respect `health_block_preview_on_fail`. Default filename: `Plinth_v3.4_{timestamp}.stl`. Place button in panel near `Create`. Confirm with user before overwriting.

**Status**: RESOLVED — see CODE_REVIEW.md.

### 3. CR-#1 — `apply_all_modifiers` swallows per-modifier failures

- **One-liner**: A boolean solver failure on one modifier leaves the rest unapplied, but the operator reports success. Exported STL is silently corrupted.
- **Related tests**: None directly. **New**: a case that constructs a geometry config known to cause an EXACT-solver failure (very thin walls, concentric cuts) and asserts the operator reports `{'ERROR'}` rather than completing.
- **Fix approach**: Wrap each `bpy.ops.object.modifier_apply()` call in its own `try/except RuntimeError`. On failure, report which modifier failed via `self.report({'ERROR'}, ...)` and abort the build cleanly. Same pattern needed for `apply_voxel_remesh` (CR-#1 also flags line 1312).

**Status**: RESOLVED — see CODE_REVIEW.md.

### 4. CR-#2 — Bad health-check default + buried UI placement

- **One-liner**: `health_block_preview_on_fail` defaults to `False`, and the health status label is at the bottom of a long panel where customers won't see it.
- **Related tests**: T20 (existing) already exercises the *enabled* path. **New**: a case that defaults the property and confirms it is now `True`. Panel placement itself is **N/A** for the harness.
- **Fix approach**: Flip default to `True`. Move the health status indicator to a row immediately above (or below) the `Create / Rebuild / Export` buttons, with color-coded status (`PASS` green, `WARN` orange, `FAIL` red). Keep the detail breakdown where it currently lives.

**Status**: RESOLVED — see CODE_REVIEW.md.

---

## Bucket 4 — Medium issues, no harness coverage

Ordered by customer-impact risk (highest first), not by issue number.

### 5. CR-#7 — Magnet holes silently disabled by depth clamping

- **One-liner**: When sealed-bottom thickness is at/below the clamp margin, `magnet_pts` is silently emptied — user sees a preflight warning but the generated geometry shows zero magnets.
- **Related tests**: T05, T06 (existing — cover the warning text). The "silent zero-magnets" outcome is the *expected* behavior under T06, but there's no assertion on the *count* of magnet holes in the output mesh.
- **Fix approach**: Either (a) escalate the preflight warning to an error that blocks the build, or (b) keep the warning but make the disabled state extremely visible in the panel ("Magnets: disabled — sealed bottom too thin"). Confirm with owner which behavior they prefer; (a) is safer for refund risk, (b) is friendlier to power users.

**Status**: Deferred to FUTURE_WORK.md.

### 6. CR-#8 — Drain fallback overlaps with center magnet

- **One-liner**: When all drain positions are filtered out due to magnet overlap, the fallback drain at `(0,0)` collides with a single-count center magnet placed at the same coordinates.
- **Related tests**: None. **New**: a case that configures `magnets_count=1`, sets up conditions to trigger the drain fallback, and asserts the resulting mesh has no overlapping cutters at origin (either by checking drain is suppressed or moved).
- **Fix approach**: In the fallback path at lines 2183-2185, check whether `(0,0)` is occupied by a magnet center and either suppress the fallback drain or offset it. Suppression is simpler and safer.

**Status**: Deferred to FUTURE_WORK.md.

### 7. CR-#12 — Box face winding may produce inverted normals

- **One-liner**: `make_box_mesh` uses the same vertex order for top and bottom faces, which can produce inward normals on one of them. `bm.normal_update()` may not always recover.
- **Related tests**: T01 (existing — default BOX smoke passes, so winding works in the default case). **New**: a case that runs the addon's health check and explicitly asserts zero inverted-normal flags across several BOX configurations.
- **Fix approach**: Fix the winding at construction time — reverse the vertex order for one of the two end faces so both produce outward normals before `normal_update()` runs. This is a one-line tuple reversal.

**Status**: Deferred to FUTURE_WORK.md.

### 8. CR-#5 — `apply_all_modifiers` context fragility

- **One-liner**: Function clobbers `view_layer.objects.active` and selection state without restoring; if Blender is in Edit Mode on a different object, the wrong object's mode gets flipped.
- **Related tests**: None. **New**: a case that creates a sentinel object, makes it active and in Edit Mode, runs `Create`, and asserts the sentinel's mode and active-status are preserved.
- **Fix approach**: Save `(active_object, mode, selected_objects)` at entry, restore in a `finally` block.

**Status**: RESOLVED — see CODE_REVIEW.md.

### 9. CR-#6 — `apply_voxel_remesh` deselects everything

- **One-liner**: `bpy.ops.object.select_all(action='DESELECT')` wipes the user's existing selection.
- **Related tests**: None. **New**: a case that selects a sentinel object before running `Create`, then asserts the sentinel is still selected afterward.
- **Fix approach**: Replace the global deselect with explicit per-object selection toggling, scoped to the objects this function actually needs to act on. Restore prior selection in a `finally` block.

**Status**: Deferred to FUTURE_WORK.md.

### 10. CR-#9 — `PLINTHGEN_OT_create` and `PLINTHGEN_OT_rebuild` are identical

- **One-liner**: Both operators have the same `execute()` body. Two buttons doing the same thing confuses users.
- **Related tests**: None. **N/A** for harness (this is a UI/UX shape decision).
- **Fix approach**: Confirm with owner whether the intent was always one operator or whether `Rebuild` was supposed to differ (e.g., skip deletion, or force a remesh even if cached). If identical is the intent, drop one button (probably keep `Force Rebuild` as the only entry point, or rename). If they should differ, define the difference.

**Status**: RESOLVED in v1.0 (owner accepted into critical batch on 2026-05-11) — see CODE_REVIEW.md.

### 11. CR-#11 — No operator `poll()` methods

- **One-liner**: Operators don't define `poll()`, so they can be invoked in invalid contexts (e.g., Edit Mode, no scene).
- **Related tests**: None. **N/A** for harness in any meaningful way (the harness always runs in Object Mode).
- **Fix approach**: Add `@classmethod poll(cls, context)` returning `context.mode == 'OBJECT' and context.scene is not None` to all PLINTHGEN operators.

**Status**: RESOLVED — see CODE_REVIEW.md.

### 12. CR-#10 — `preflight_validate` runs on every panel draw

- **One-liner**: Validator runs on every redraw event (mouse hover, viewport navigation, property change). Causes micro-stutters on complex scenes.
- **Related tests**: None. **N/A** for harness (performance feel is not headlessly measurable here).
- **Fix approach**: Cache last-computed `(errors, warnings)` keyed on a hash of the relevant property values. Recompute only when the hash changes. Keep the cache invalidation logic dead simple — over-engineering this is worse than the original problem.

**Status**: Deferred to FUTURE_WORK.md.

---

## Bucket 5 — Lower-priority + hygiene (in-scope subset)

Per `HANDOFF.md`, only the following lower-priority items are in scope for v1.0. The rest go to `FUTURE_WORK.md`.

### 13. CR-#13 — Add `bl_description` tooltips to all operators

- **One-liner**: Hovering buttons shows no tooltip.
- **Related tests**: **N/A**.
- **Fix approach**: Add a `bl_description = "..."` attribute to every `PLINTHGEN_OT_*` class with a short, accurate description.

**Status**: RESOLVED — see CODE_REVIEW.md.

### 14. CR-#20 — `__pycache__/` already in `.gitignore`; verify no `.pyc` committed

- **One-liner**: Original audit found a `.pyc` in the repo; `.gitignore` was tightened in commit `00dc3c3`.
- **Related tests**: **N/A**.
- **Fix approach**: Verify `git ls-files | grep pyc` returns nothing. If any tracked `.pyc` remains, `git rm` it.

**Status**: RESOLVED — see CODE_REVIEW.md.

### 15. CR-#18 — Defensive property access in handlers

- **One-liner**: Full version-migration is out of scope, but any handler that reads scene properties should tolerate a renamed/missing property without crashing on file load.
- **Related tests**: **N/A** (would require multi-version `.blend` fixtures).
- **Fix approach**: Audit `@persistent`/`load_post` handlers and any `update=` callbacks. Wrap property reads in a `try/except AttributeError` that no-ops on miss.

**Status**: NOT APPLICABLE — see CODE_REVIEW.md.

---

## Out of scope for v1.0 — defer to `FUTURE_WORK.md`

Per `HANDOFF.md` Phase 5: **CR-#14, #15, #16, #17, #19** are explicitly deferred.

- CR-#14 — Hardcoded segment counts
- CR-#15 — `purge_orphans()` swallows all exceptions
- CR-#16 — `build_plinth()` is 506 lines
- CR-#17 — `unit_sync_lock` is a Blender property
- CR-#19 — High-detail decorations create massive meshes (perf)

These will be captured in `FUTURE_WORK.md` when it's created in Phase 5.

---

## Phase 3 entry checklist (for owner sign-off)

Before starting code changes, confirm:

1. **Branching**: commit each fix directly to `main`, or branch as `fix/<slug>`?
2. **CR-#7 disposition**: escalate clamp-disable to a hard error, or keep as warning with louder UI?
3. **CR-#9 disposition**: drop one of `Create` / `Force Rebuild`, or define how they differ?
4. **CR-#4 tagging**: custom property (`obj["plinthgen_owned"] = True`) or dedicated collection?
5. **Test-first protocol**: confirm we add the new harness case *before* the fix lands, even when the new case will initially fail.
