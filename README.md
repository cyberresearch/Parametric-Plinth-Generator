# Parametric Plinth Generator

Build display plinths for tabletop miniatures and resin 3D printing — parametric, customizable, and 3D-print-ready.

![Screenshot placeholder — add a panel screenshot or demo GIF before listing]

## What it does

Drive a panel of parameters and generate a watertight plinth mesh, ready to print:

- **Shape**: box or cylinder
- **Slope**: angle the top surface in any direction
- **Hollow shell**: sealed or open bottom, configurable wall, top, and floor thickness
- **Magnet pockets**: precise cylindrical cuts for embedding rare-earth magnets (perimeter, corners, ring, or single centered)
- **Drain / vent holes**: prevent resin pooling on hollow prints, including optional drains at magnet centers
- **Decorative trim**: half-round base trim plus 12 profile families — ogee/cove/convex bands, stepped layers, vertical fluting, recessed side panels, bead borders, rope twist, dentil courses, scalloped skirts, corner bosses/medallions, nameplate recess, surface texture stamp, foot pads / bun feet
- **Preflight validator**: checks parameters before build and flags hard errors and warnings
- **Mesh health check**: post-build watertightness, loose-geometry, degenerate-face, island-count, and inverted-normal validation
- **Manifold guarantee**: optional voxel remesh, applied only when the preview isn't watertight
- **One-click STL export**: ready for your slicer

## Installation

1. Download `plinth_generator_v3.4.1.zip` from your Gumroad or Blender Market purchase.
2. Open Blender (version 4.2 LTS or later).
3. `Edit > Preferences > Add-ons > Install...`, select the zip file.
4. Enable the **Parametric Plinth Generator** entry.
5. The panel appears at `View3D > Sidebar (N key) > Plinth v3.4`.

## Quick start

1. Open the panel.
2. Click **Create**. A default box plinth is built.
3. Tweak parameters in the panel — shape, dimensions, slope, decorations, magnets, drains.
4. Click **Force Rebuild** to update the plinth in place.
5. When you're happy with the result, click **Export STL** and save to your slicer's import folder.

## Inputs and units

By default the addon works in millimeters. To enter dimensions in inches, switch the **Input Units** dropdown to `IN`; values are converted to mm automatically and the converted value is shown under each field. Non-dimension controls (wall thickness, drain diameter, trim radius, etc.) remain mm-based.

## Mesh health check

After every build, the addon validates the preview mesh for watertight geometry, loose edges/verts, degenerate faces, face-island count, and inverted normals. If any check fails, the failure is reported in the panel banner.

To prevent exporting a failed mesh, leave **Block Preview On Fail** enabled in the **Post-Build Health Check** box. With that option on, the preview is hidden when the health check fails so you can't accidentally export a corrupted model.

## Compatibility

- **Blender**: 4.2 LTS through latest stable (currently 5.0). Tested on Blender 5.0.1.
- **Operating systems**: macOS and Windows are officially supported. Linux should work (pure-Python addon) but is untested.

## License

GPLv3. See `LICENSE` for the full text. You may use, modify, and redistribute the addon; redistributions must remain GPL and include source.

## Changelog

See `CHANGELOG.md` for the full version history.

## Bugs and support

File issues at https://github.com/cyberresearch/Parametric-Plinth-Generator/issues
