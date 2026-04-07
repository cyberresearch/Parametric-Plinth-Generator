# Parametric Plinth Generator

Blender addon for generating parametric plinth geometry for resin printing workflows.

## Current baseline
- Source: `addon/plinth_generator_v3_4.py`
- Blender target: 5.0

## Feature Highlights
- `BOX` and `CYL` plinth generation
- Dimension input units: `MM` or `IN` (inch entry always converts to mm for model generation)
- Top-only slope controls
- Hollow interior (open or sealed bottom)
- Magnet pockets (box perimeter/corners, cylinder ring)
- Single-magnet mode centers the pocket on the plinth
- Standard drain/vent holes plus optional drains at magnet centers (sealed hollow mode)
- Decorative half-round base trim
- Expanded decorative profile suite (bands, steps, fluting, panels, beads, rope, dentils, scallops, bosses, nameplate recess, texture stamp, feet)
- Optional manifold guarantee on preview (voxel remesh only when needed)
- Preflight validator before build/rebuild
- Post-build health check with optional preview block on fail

## Units Behavior
- Set `Dimensions > Input Units` to `Millimeters` or `Inches`.
- In inch mode, dimension fields accept inches and display live converted mm values directly below each field.
- Core geometry is always generated from mm properties internally (`1 in = 25.4 mm`).
- Non-dimension controls (for example wall thickness, drain diameter, trim radius) remain mm-based.

## New Install (First Time)
1. Open Blender.
2. Go to `Edit > Preferences > Add-ons`.
3. Click `Install...` and select `addon/plinth_generator_v3_4.py`.
4. Enable the addon.
5. Open the 3D View sidebar (`N`) and find the `Plinth v3.4` tab.

## Update Existing Install
1. Save your current `.blend` file.
2. In Blender, go to `Edit > Preferences > Add-ons`.
3. Search for `Plinth` and disable the currently installed version.
4. Click the down arrow on the addon entry and choose `Remove` (if shown).
5. Click `Install...` and select the new `addon/plinth_generator_v3_4.py`.
6. Re-enable the addon.
7. Reopen your `.blend` file and run `Force Rebuild` once to refresh generated geometry.

## Quick Use
1. Open the `Plinth v3.4` tab in the 3D View sidebar.
2. Choose `Box / Rectangle` or `Cylinder`.
3. Set `Input Units` before entering dimensions.
4. Enable and tune the features you need: slope, hollowing, magnets, drains, trim, and decorations.
5. Review the `Preflight` box and fix any hard errors before building.
6. Click `Create` for a fresh build in the current scene.
7. Use `Force Rebuild` after changing options on an existing plinth setup.

## Build Behavior
- `Create` builds a new plinth using the current panel settings.
- `Force Rebuild` reruns the build with the current settings and is the safer choice after updating the addon or changing many parameters.
- Successful `Create` and `Force Rebuild` remove existing mesh objects in the scene before generating the plinth.
- Preflight hard errors cancel the operation before mesh deletion.
- When `Preview Cuts (Duplicate)` is enabled, the preview mesh is the export-ready object and the driver object is hidden.

## Recommended Robust Workflow
1. Set `Input Units` first, then enter dimensions and feature options (`Hollow`, `Magnets`, `Drain / Vent Holes`, `Base Trim`, decorations).
2. Review the `Preflight` box and resolve any errors before building.
3. Keep `Preview Cuts (Duplicate)` enabled for export-ready mesh output.
4. Keep `Manifold Guarantee (Preview)` enabled for automatic watertight remediation.
5. Keep `Post-Build Health Check` enabled and review its status after each build.
6. Optionally enable `Block Preview On Fail` to prevent exporting failed preview geometry.

## Post-Build Health Check Notes
- Runs on the final preview mesh after boolean operations and manifold processing.
- Reports:
  - Watertight/non-manifold edge status
  - Loose edges/verts
  - Degenerate faces
  - Face island count
  - Inverted normals flag
- When manifold remesh runs, the health report indicates that remesh was applied.

## Development And Validation
- This addon does not have a separate packaging or compile step. Blender installs `addon/plinth_generator_v3_4.py` directly.
- Manual coverage lives in `TEST_PLAN.md`.
- Automated validation lives in `tests/test_plan_harness.py`.

Run the full headless harness from the repo root:

```bash
blender --background --factory-startup --python tests/test_plan_harness.py
```

If `blender` is not on `PATH` on macOS, use:

```bash
/Applications/Blender.app/Contents/MacOS/Blender --background --factory-startup --python tests/test_plan_harness.py
```

Run selected cases:

```bash
blender --background --factory-startup --python tests/test_plan_harness.py -- --case T14 --case T18
```

List supported test IDs:

```bash
blender --background --factory-startup --python tests/test_plan_harness.py -- --list
```

Write a JSON report:

```bash
blender --background --factory-startup --python tests/test_plan_harness.py -- --json-out /tmp/plinth_test_report.json
```
