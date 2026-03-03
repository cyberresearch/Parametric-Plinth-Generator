# Parametric Plinth Generator

Blender addon for generating parametric plinth geometry for resin printing workflows.

## Current baseline
- Source: `addon/plinth_generator_v3_3.py`
- Blender target: 5.0

## Feature Highlights
- `BOX` and `CYL` plinth generation
- Dimension input units: `MM` or `IN` (inch entry always converts to mm for model generation)
- Top-only slope controls
- Hollow interior (open or sealed bottom)
- Magnet pockets (box perimeter/corners, cylinder ring)
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
3. Click `Install...` and select `addon/plinth_generator_v3_3.py`.
4. Enable the addon.
5. Open the 3D View sidebar (`N`) and find the `Plinth v3.3` tab.

## Update Existing Install
1. Save your current `.blend` file.
2. In Blender, go to `Edit > Preferences > Add-ons`.
3. Search for `Plinth` and disable the currently installed version.
4. Click the down arrow on the addon entry and choose `Remove` (if shown).
5. Click `Install...` and select the new `addon/plinth_generator_v3_3.py`.
6. Re-enable the addon.
7. Reopen your `.blend` file and run `Force Rebuild` once to refresh generated geometry.

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
