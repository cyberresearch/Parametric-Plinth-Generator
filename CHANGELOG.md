# Changelog

All notable changes to the Parametric Plinth Generator are documented here.

This project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html):
- **MAJOR** for breaking changes (e.g., property renames that invalidate older `.blend` files)
- **MINOR** for new features that are backward compatible
- **PATCH** for bug fixes and minor UX adjustments

## [3.4.1] — 2026-05-12

First commercial ship release. No new features — focused on hardening and packaging.

### Fixed

- **Modifier-apply failures no longer silently corrupt exports.** If any modifier in the build stack fails to apply, the addon now reports the failure as an error, cancels the build, and cleans up partial artifacts. Previously the failure was logged to the console only, allowing a half-applied modifier stack to reach STL export. (CR-#1)
- **Build fails fast on modifier errors.** When a modifier-apply failure is detected, the build aborts immediately rather than continuing through subsequent processing steps on a doomed mesh.

### Changed

- **Create and Force Rebuild now have distinct purposes.** `Create` is enabled only when no plinth exists in the scene; `Force Rebuild` is enabled only when one does. Tooltips updated to explain the relationship. (CR-#9)
- **`bl_info` polish for commercial release**: author set to Justin Sharp, minimum Blender bumped to 4.2 LTS, description reworked to lead with the buyer outcome (tabletop miniature display + resin 3D printing), and `doc_url` / `tracker_url` added pointing at the GitHub repository.

### Added

- GPLv3 LICENSE file.
- End-user README split out of the previous mixed README; developer content moved to `DEVELOPMENT.md`.
- Headless test harness coverage expanded from 39 to 44 cases:
  - **T37**: modifier-failure escalation pipeline through `build_plinth` and `_execute_build`.
  - **T38**: scene-mesh safety on a successful `Create` (sentinel cube survives).
  - **T39**: STL export happy path with binary STL header parsing (triangle count, exact file-size consistency).
  - **T40**: Create vs Force Rebuild poll-gating.
  - **T41**: `apply_all_modifiers` catches real Blender `RuntimeError` from a broken Boolean modifier (no monkey-patching).

## [3.4.0] — 2026-04-01

Initial v3.4 release after the geometry and health-check overhaul. Pre-commercial; distributed informally before the ship-readiness pass.

### Added

- Box and cylinder plinth shapes.
- Top-surface slope with selectable axis and high side.
- Hollow shell with sealed or open bottom, configurable wall and floor thickness.
- Magnet pocket cuts with depth clamping for sealed bottoms.
- Drain vents, including the option to drain through magnet centers for sealed hollow bodies.
- Decorative trim families: base bevels, profile bands, stepped layers, fluting, recessed panels, beads, rope, dentils, scallops, corner bosses, nameplate, surface texture stamp, and feet.
- Optional voxel remesh as a manifold guarantee for problematic geometry.
- Post-build mesh health check: watertight, non-manifold edges, degenerate faces, loose elements, inverted normals.
- Inch / millimeter input mode with live conversion.
- One-click STL export with health-fail gating.
- Preflight validator that surfaces parameter errors and warnings before build.
