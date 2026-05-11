# Parametric Plinth Generator Test Plan

This plan targets broad coverage of geometry generation, preflight validation, manifold processing, and post-build health reporting.

## How To Use
1. Open Blender with a new scene.
2. Enable the addon from `addon/plinth_generator_v3_4.py`.
3. Open `View3D > Sidebar > Plinth v3.4`.
4. For each test case, apply the listed settings and run `Create` (or `Force Rebuild`).
5. Record `PASS` or `FAIL` in the `Result` column and add notes if behavior differs.

## Notes
- By design, successful `Create`/`Force Rebuild` removes mesh objects in the scene before building.
- Preflight hard errors cancel before mesh deletion.
- Health checks only run when `Preview Cuts (Duplicate)` is enabled.

## Test Cases

| ID | Scenario | Settings / Action | Expected Outcome | Result | Notes |
|---|---|---|---|---|---|
| T01 | BOX smoke test | Defaults (`BOX`, preview duplicate on, manifold on, health on), click `Create` | Build succeeds. `Preflight` shows no errors. Preview object is selected and main object hidden. Health report is populated. | PASS |  |
| T02 | CYL smoke test | Set `shape=CYL`, keep defaults, click `Create` | Build succeeds with cylindrical plinth. Preflight clean. Health report populated. | PASS |  |
| T03 | Slope direction | `slope_enabled=ON`, `slope_delta_mm=5`, `slope_axis=X`, `slope_high_side=POS`, build; then switch high side to `NEG` and rebuild | Top slope flips from +X high side to -X high side. | PASS |  |
| T04 | Hollow open bottom | `hollow_enabled=ON`, `sealed_bottom=OFF`, `drain_enabled=ON`, build | Hollow cavity opens through bottom. Drain holes cut per settings. | PASS |  |
| T05 | Sealed magnet clamp warning | `hollow=ON`, `sealed=ON`, `bottom_thickness=1.0`, `magnet_hole_depth=2.0`, `depth_tol=0.3`, build | Preflight warning: `Magnet hole depth will clamp to 0.50mm due to sealed bottom.` Build succeeds with shallow magnets. | PASS |  |
| T06 | Sealed margin disables magnets | `hollow=ON`, `sealed=ON`, `bottom_thickness=0.4`, magnets enabled, build | Preflight warning: `Magnet holes are disabled because sealed bottom is at/below clamp margin.` No magnet holes are cut. | PASS |  |
| T07 | Center drains in magnets | `hollow=ON`, `sealed=ON`, `magnets_count=4`, `drain_enabled=ON`, `drain_at_magnet_centers=ON`, `drain_count=0`, build | Drain holes are cut at each magnet center. | PASS |  |
| T08 | Center drains without sealed bottom | Same as T07 but `sealed_bottom=OFF` | Preflight warning: `Drain at Magnet Centers requires Sealed Bottom.` Center drains are not generated. | PASS |  |
| T09 | Center drains without magnets | `drain_at_magnet_centers=ON`, `magnets_count=0`, `hollow=ON`, `sealed=ON`, build | Preflight warning: `Drain at Magnet Centers requires at least one magnet.` No center drains. | PASS |  |
| T10 | Center drain size warning | Set magnet cutter dia to ~5.2 (`magnet_dia=5`, `dia_tol=0.2`), set `magnet_center_drain_dia_mm=5.2`, build | Preflight warning: `Magnet center drain diameter should be smaller than magnet hole diameter.` Build still runs. | PASS |  |
| T11 | BOX base trim | `shape=BOX`, `base_trim_enabled=ON`, `base_trim_radius_mm=2.5`, build | Half-round trim appears along box base perimeter. | PASS |  |
| T12 | CYL base trim | `shape=CYL`, `base_trim_enabled=ON`, `base_trim_radius_mm=2.5`, build | Half-round ring appears at cylinder base. | PASS |  |
| T13 | CYL trim clamp warning | `shape=CYL`, `diameter_mm=20`, `base_trim_radius_mm=15`, build | Preflight warning: `Cylinder trim radius will clamp to 9.90mm.` Build succeeds with clamped trim radius. | PASS |  |
| T14 | Error: wall too thick | `shape=BOX`, `width=20`, `length=20`, `hollow=ON`, `wall_thickness=11`, click `Create` | Preflight error: `Wall thickness is too large for selected box dimensions.` Build is cancelled. | PASS |  |
| T15 | Error: top too thick | `hollow=ON`, `height=10`, `top_thickness=10`, build | Preflight error: `Top thickness must be less than total height when Hollow is enabled.` Build is cancelled. | PASS |  |
| T16 | Error: bottom too thick | `hollow=ON`, `sealed=ON`, `height=20`, `top_thickness=5`, `bottom_thickness=15`, build | Preflight error: `Bottom thickness must be less than (height - top thickness).` Build is cancelled. | PASS |  |
| T17 | Error: drain too large | `shape=BOX`, `hollow=ON`, `width=20`, `length=20`, `drain_dia_mm=40`, build | Preflight error: `Drain diameter is too large for selected box dimensions.` Build is cancelled. | PASS |  |
| T18 | Cancel protects scene meshes | Add a regular Blender cube, trigger any hard-error case (for example T14), click `Create` | Operation cancels and existing cube remains (no mesh deletion). | PASS |  |
| T19 | Health requires preview duplicate | `preview_cuts_duplicate=OFF`, `health_check_enabled=ON`, build | Preflight warning: `Post-build health check requires Preview Cuts (Duplicate).` Health section shows `Health check requires Preview Cuts (Duplicate).` | PASS |  |
| T20 | Forced health fail + block preview | `shape=BOX`, `width=1`, `length=1`, `height=1`, `health_check_enabled=ON`, `health_block_preview_on_fail=ON`, `health_degenerate_area_mm2=1.0`, preview duplicate ON, build | Health fails (degenerate faces). Preview is hidden, main is visible, operator reports `Preview blocked by health check: ...`. | PASS |  |
| T21 | Manifold + health integration | `hollow=ON`, `sealed=OFF`, `manifold_guarantee=ON`, health ON, preview duplicate ON, build | Health report runs on final preview mesh and may display `Voxel remesh was applied by manifold guarantee.` when remesh is triggered. | PASS |  |
| T22 | Unit input toggle (BOX) | `shape=BOX`, set `width_mm=76.2`, `length_mm=88.9`, `height_mm=57.15`, then switch `Input Units=IN` | Inch fields show `3.0`, `3.5`, `2.25` (or rounded equivalents). | PASS |  |
| T23 | Inch input drives mm (BOX) | `shape=BOX`, `Input Units=IN`, set `width_in=4.0`, `length_in=6.0`, `height_in=2.0` | Live labels show `101.600 mm`, `152.400 mm`, `50.800 mm`; build uses those mm dimensions. | PASS |  |
| T24 | Inch input drives mm (CYL) | `shape=CYL`, `Input Units=IN`, set `diameter_in=5.0`, `cyl_height_in=2.5` | Live labels show `127.000 mm` and `63.500 mm`; built plinth matches those values. | PASS |  |
| T25 | mm input back-sync to inches | `Input Units=MM`, set `width_mm=50.8`, `length_mm=76.2`, switch `Input Units=IN` | Inch fields display `2.0` and `3.0` (or rounded equivalents). | PASS |  |
| T26 | Unit mode does not break manifold/health path | `Input Units=IN`, enter valid inch dimensions, enable `preview duplicate`, `manifold_guarantee`, `health_check`, build | Build succeeds; manifold/health behavior is unchanged, and health report populates normally. | PASS |  |
| T27 | Sloped hollow roof thickness (BOX) | `shape=BOX`, `width=100`, `length=80`, `height=50`, `hollow=ON`, `sealed=ON`, `wall_thickness=5`, `top_thickness=10`, `bottom_thickness=3`, `slope_enabled=ON`, `slope_delta=5`, `slope_axis=X`, build | Hollow roof thickness remains `10mm` on both low and high sides of the slope. | PASS |  |
| T28 | Sloped hollow roof thickness (CYL) | `shape=CYL`, `diameter=100`, `height=50`, `hollow=ON`, `sealed=ON`, `wall_thickness=5`, `top_thickness=10`, `bottom_thickness=3`, `slope_enabled=ON`, `slope_delta=5`, `slope_axis=X`, build | Hollow roof thickness remains `10mm` on both low and high sides of the slope. | PASS |  |
| T29 | Export blocked after failed health | Use the forced-fail setup from T20, then try `Export STL` | Export button is unavailable while preview is blocked, and no STL is written. | PASS |  |
| T30 | BOX recessed panels default health | `shape=BOX`, `panels_enabled=ON`, `magnets_count=0`, `drain_enabled=OFF`, build | Build succeeds and post-build health reports `PASS`. | PASS |  |
| T31 | BOX nameplate default health | `shape=BOX`, `nameplate_enabled=ON`, `magnets_count=0`, `drain_enabled=OFF`, build | Build succeeds and post-build health reports `PASS`. | PASS |  |
| T32 | BOX dentil default health | `shape=BOX`, `dentil_enabled=ON`, `magnets_count=0`, `drain_enabled=OFF`, build | Build succeeds and post-build health reports `PASS`. | PASS |  |
| T33 | BOX dentil depth honored | Generate a BOX dentil course with `dentil_w=2`, `dentil_d=10`, `dentil_h=4` | Dentils project `10mm` from the box sides rather than collapsing to a shallower depth. | PASS |  |
| T34 | BOX rope default health | `shape=BOX`, `rope_enabled=ON`, `magnets_count=0`, `drain_enabled=OFF`, build | Build succeeds and post-build health reports `PASS`. | PASS |  |
| T35 | CYL rope default health | `shape=CYL`, `rope_enabled=ON`, `magnets_count=0`, `drain_enabled=OFF`, build | Build succeeds and post-build health reports `PASS`. | PASS |  |
| T36 | CYL bead border default health | `shape=CYL`, `beads_enabled=ON`, `magnets_count=0`, `drain_enabled=OFF`, build | Build succeeds and post-build health reports `PASS`. | PASS |  |
| T37 | Modifier failure escalates | Force `apply_all_modifiers` to return a failure via a harness-level monkey-patch; click `Create` | Operator reports `Modifier apply failed: ...`, returns `CANCELLED`, and no plinth objects remain in the scene. | PASS |  |
| T38 | Successful Create preserves user meshes | Add a plain Blender cube called `Harness_SuccessSentinel` to the scene, click `Create` with default settings | Build completes; the sentinel cube is still present after Create finishes. | PASS |  |
| T39 | STL export happy path | Default `Create` with health enabled, then click `Export STL` with a tempfile path | Export operator is enabled, returns `FINISHED`, and writes a non-empty binary STL file (>= 84 bytes). | PASS |  |
| T40 | Create / Force Rebuild button gating | In a clean scene, check button poll; click `Create`; recheck button poll; click `Force Rebuild` | Before Create: Create enabled, Force Rebuild disabled. After Create: Create disabled, Force Rebuild enabled. Force Rebuild succeeds. | PASS |  |

## Signoff

| Date | Tester | Blender Version | Addon File | Summary |
|---|---|---|---|---|
| 2026-05-11 | Headless harness (Blender 5.0.1) | 5.0.1 | `addon/plinth_generator_v3_4.py` | Baseline: 36/36 documented cases PASS. Harness also ran 3 regression cases (R01–R03), all PASS. Total 39/39. |
