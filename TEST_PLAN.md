# Parametric Plinth Generator Test Plan

This plan targets broad coverage of geometry generation, preflight validation, manifold processing, and post-build health reporting.

## How To Use
1. Open Blender with a new scene.
2. Enable the addon from `addon/plinth_generator_v3_3.py`.
3. Open `View3D > Sidebar > Plinth v3.3`.
4. For each test case, apply the listed settings and run `Create` (or `Force Rebuild`).
5. Record `PASS` or `FAIL` in the `Result` column and add notes if behavior differs.

## Notes
- By design, successful `Create`/`Force Rebuild` removes mesh objects in the scene before building.
- Preflight hard errors cancel before mesh deletion.
- Health checks only run when `Preview Cuts (Duplicate)` is enabled.

## Test Cases

| ID | Scenario | Settings / Action | Expected Outcome | Result | Notes |
|---|---|---|---|---|---|
| T01 | BOX smoke test | Defaults (`BOX`, preview duplicate on, manifold on, health on), click `Create` | Build succeeds. `Preflight` shows no errors. Preview object is selected and main object hidden. Health report is populated. |  |  |
| T02 | CYL smoke test | Set `shape=CYL`, keep defaults, click `Create` | Build succeeds with cylindrical plinth. Preflight clean. Health report populated. |  |  |
| T03 | Slope direction | `slope_enabled=ON`, `slope_delta_mm=5`, `slope_axis=X`, `slope_high_side=POS`, build; then switch high side to `NEG` and rebuild | Top slope flips from +X high side to -X high side. |  |  |
| T04 | Hollow open bottom | `hollow_enabled=ON`, `sealed_bottom=OFF`, `drain_enabled=ON`, build | Hollow cavity opens through bottom. Drain holes cut per settings. |  |  |
| T05 | Sealed magnet clamp warning | `hollow=ON`, `sealed=ON`, `bottom_thickness=1.0`, `magnet_hole_depth=2.0`, `depth_tol=0.3`, build | Preflight warning: `Magnet hole depth will clamp to 0.50mm due to sealed bottom.` Build succeeds with shallow magnets. |  |  |
| T06 | Sealed margin disables magnets | `hollow=ON`, `sealed=ON`, `bottom_thickness=0.4`, magnets enabled, build | Preflight warning: `Magnet holes are disabled because sealed bottom is at/below clamp margin.` No magnet holes are cut. |  |  |
| T07 | Center drains in magnets | `hollow=ON`, `sealed=ON`, `magnets_count=4`, `drain_enabled=ON`, `drain_at_magnet_centers=ON`, `drain_count=0`, build | Drain holes are cut at each magnet center. |  |  |
| T08 | Center drains without sealed bottom | Same as T07 but `sealed_bottom=OFF` | Preflight warning: `Drain at Magnet Centers requires Sealed Bottom.` Center drains are not generated. |  |  |
| T09 | Center drains without magnets | `drain_at_magnet_centers=ON`, `magnets_count=0`, `hollow=ON`, `sealed=ON`, build | Preflight warning: `Drain at Magnet Centers requires at least one magnet.` No center drains. |  |  |
| T10 | Center drain size warning | Set magnet cutter dia to ~5.2 (`magnet_dia=5`, `dia_tol=0.2`), set `magnet_center_drain_dia_mm=5.2`, build | Preflight warning: `Magnet center drain diameter should be smaller than magnet hole diameter.` Build still runs. |  |  |
| T11 | BOX base trim | `shape=BOX`, `base_trim_enabled=ON`, `base_trim_radius_mm=2.5`, build | Half-round trim appears along box base perimeter. |  |  |
| T12 | CYL base trim | `shape=CYL`, `base_trim_enabled=ON`, `base_trim_radius_mm=2.5`, build | Half-round ring appears at cylinder base. |  |  |
| T13 | CYL trim clamp warning | `shape=CYL`, `diameter_mm=20`, `base_trim_radius_mm=15`, build | Preflight warning: `Cylinder trim radius will clamp to 9.90mm.` Build succeeds with clamped trim radius. |  |  |
| T14 | Error: wall too thick | `shape=BOX`, `width=20`, `length=20`, `hollow=ON`, `wall_thickness=11`, click `Create` | Preflight error: `Wall thickness is too large for selected box dimensions.` Build is cancelled. |  |  |
| T15 | Error: top too thick | `hollow=ON`, `height=10`, `top_thickness=10`, build | Preflight error: `Top thickness must be less than total height when Hollow is enabled.` Build is cancelled. |  |  |
| T16 | Error: bottom too thick | `hollow=ON`, `sealed=ON`, `height=20`, `top_thickness=5`, `bottom_thickness=15`, build | Preflight error: `Bottom thickness must be less than (height - top thickness).` Build is cancelled. |  |  |
| T17 | Error: drain too large | `shape=BOX`, `hollow=ON`, `width=20`, `length=20`, `drain_dia_mm=40`, build | Preflight error: `Drain diameter is too large for selected box dimensions.` Build is cancelled. |  |  |
| T18 | Cancel protects scene meshes | Add a regular Blender cube, trigger any hard-error case (for example T14), click `Create` | Operation cancels and existing cube remains (no mesh deletion). |  |  |
| T19 | Health requires preview duplicate | `preview_cuts_duplicate=OFF`, `health_check_enabled=ON`, build | Preflight warning: `Post-build health check requires Preview Cuts (Duplicate).` Health section shows `Health check requires Preview Cuts (Duplicate).` |  |  |
| T20 | Forced health fail + block preview | `shape=BOX`, `width=1`, `length=1`, `height=1`, `health_check_enabled=ON`, `health_block_preview_on_fail=ON`, `health_degenerate_area_mm2=1.0`, preview duplicate ON, build | Health fails (degenerate faces). Preview is hidden, main is visible, operator reports `Preview blocked by health check: ...`. |  |  |
| T21 | Manifold + health integration | `hollow=ON`, `sealed=OFF`, `manifold_guarantee=ON`, health ON, preview duplicate ON, build | Health report runs on final preview mesh and may display `Voxel remesh was applied by manifold guarantee.` when remesh is triggered. |  |  |

## Signoff

| Date | Tester | Blender Version | Addon File | Summary |
|---|---|---|---|---|
|  |  | 5.0 | `addon/plinth_generator_v3_3.py` |  |
