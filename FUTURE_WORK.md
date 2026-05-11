# Future Work — Post-v1.0

Items intentionally deferred from the v1.0 ship-readiness pass. Revisit after
first-revenue feedback.

## From CODE_REVIEW.md (April 2026)

### CR-#6 — `apply_voxel_remesh` deselects everything
Side-effect that clobbers user selection. Lower-impact than CR-#5 because the
remesh path only fires when manifold-guarantee triggers. Fix protocol: save and
restore selection state around the deselect+select pattern, mirroring the
treatment in `apply_all_modifiers` after `65ab6ba`.

### CR-#7 — Magnet holes silently disabled by depth clamping
When sealed-bottom thickness is at/below the clamp margin, magnets are silently
zeroed. Owner decision (2026-05-11): escalate this from preflight *warning* to
preflight *error* so the build blocks. Implementation deferred until first
customer feedback confirms the desired blocking behavior.

### CR-#8 — Drain fallback at (0,0) can overlap a center magnet
When all drain positions are filtered, a single fallback drain is placed at
origin; a single-count magnet is also placed at origin. They collide. Fix:
suppress the fallback drain when magnets_count == 1.

### CR-#10 — `preflight_validate` runs on every panel draw
Micro-stutter on complex scenes. Cache last `(errors, warnings)` keyed on a
hash of relevant properties; invalidate on change.

### CR-#12 — Box face winding may produce inverted normals
The current `make_box_mesh` was reworked in `65ab6ba` to use right-hand-rule
winding and `bmesh.ops.recalc_face_normals`. The audit could not reproduce the
original issue, but adding a harness case that builds several BOX configs and
asserts health reports zero inverted-normal flags would prove it stays fixed.

### CR-#14 — Hardcoded segment counts in various functions
Cylinders, cones, bead borders, etc. use hardcoded segment values. Surface as
user-controllable properties when there is signal that customers want it.

### CR-#15 — `purge_orphans()` swallows all exceptions
If orphan purging silently fails, the .blend bloats over many rebuilds. Replace
the bare `except` with at least an `Exception` filter and log the failure.

### CR-#16 — `build_plinth()` is 506 lines long
Maintainability. Split into `_build_base`, `_build_decorations`,
`_build_functional_cuts`, `_apply_postprocessing`. Single-file addon constraint
stays; these are still in the same file, just smaller functions.

### CR-#17 — Unit sync lock uses a Blender property
`unit_sync_lock: bpy.props.BoolProperty(...)` participates in undo and saves to
the .blend. Replace with a module-level Python flag.

### CR-#19 — High-detail decorations create massive meshes
Performance ceiling on rope/bead/dentil combinations. Add a progress indicator
and/or a "decoration density" property that caps total primitive count.
