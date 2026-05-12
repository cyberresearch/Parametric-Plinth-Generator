# Development Notes

This file documents the development workflow for the Parametric Plinth Generator addon.
End-user installation and usage docs live in `README.md`.

## Repository layout

```
addon/
  plinth_generator_v3_4.py     <- the addon (single file)
tests/
  test_plan_harness.py         <- headless harness exercising the addon
  install_test.py              <- end-to-end install verification (added in Phase 6 Task 6)
scripts/
  build_dist.sh                <- produces dist/plinth_generator_v3.X.Y.zip (added in Phase 6 Task 5)
README.md                      <- end-user docs (what buyers read)
DEVELOPMENT.md                 <- this file
TEST_PLAN.md                   <- exhaustive test case matrix
CODE_REVIEW.md                 <- audit log of known issues
FIX_QUEUE.md                   <- triaged work queue
FUTURE_WORK.md                 <- deferred items
CHANGELOG.md                   <- shipped versions
LICENSE                        <- GPLv3
```

## Running the headless harness

```bash
/Applications/Blender.app/Contents/MacOS/Blender --background --factory-startup \
  --python tests/test_plan_harness.py -- --json-out ./test_report_baseline.json
```

Selected cases only:

```bash
/Applications/Blender.app/Contents/MacOS/Blender --background --factory-startup \
  --python tests/test_plan_harness.py -- --case T14 --case T18
```

List supported cases:

```bash
/Applications/Blender.app/Contents/MacOS/Blender --background --factory-startup \
  --python tests/test_plan_harness.py -- --list
```

All test cases listed in `TEST_PLAN.md` should pass on every commit to `main`.

## Manual testing

`delete_plinthgen_objects_only()` scopes mesh deletion to the `PlinthGen_v3_4` collection,
so manual testing in a scene with non-plinth objects is safe. Anything inside the
PlinthGen collection will be removed on every build/rebuild.

## Building the distribution zip

```bash
./scripts/build_dist.sh
```

Outputs `dist/plinth_generator_v3.X.Y.zip` containing only the four files a buyer needs:
- `plinth_generator_v3_4.py`
- `README.md`
- `LICENSE`
- `CHANGELOG.md`

Version number is derived from `bl_info["version"]` in the addon source.

## Install verification

After building, verify the zip installs cleanly on a fresh Blender profile:

```bash
HERMETIC=$(mktemp -d)
BLENDER_USER_RESOURCES="$HERMETIC" \
  /Applications/Blender.app/Contents/MacOS/Blender --background --factory-startup \
  --python tests/install_test.py -- dist/plinth_generator_v3.4.1.zip
rm -rf "$HERMETIC"
```

The install test runs in a temporary Blender user-resources directory so it doesn't
pollute your actual Blender profile. It installs the zip, enables the addon, runs a
default `Create`, and asserts the build succeeded.

## Coding conventions

- **Single-file addon.** Do not split into modules.
- **No external dependencies** beyond `bpy` and `bmesh`.
- Operators use the `PLINTHGEN_OT_*` naming convention.
- Wrap each `bpy.ops.object.modifier_apply()` in its own `try/except`.
- Prefer the low-level data API (`bpy.data`, `bmesh`) over `bpy.ops` for procedural geometry.

## Conducting a release

1. Ensure `main` is green on the full harness (`Ran N case(s): N PASS, 0 FAIL, 0 ERROR`).
2. Bump `bl_info["version"]` in `addon/plinth_generator_v3_4.py`.
3. Add a `CHANGELOG.md` entry for the new version.
4. Run `./scripts/build_dist.sh` to produce the zip.
5. Run `tests/install_test.py` against the zip to confirm a clean install.
6. Tag the release in git: `git tag -a v3.4.X -m "v3.4.X — <summary>" && git push --tags`.
7. Upload the zip to Gumroad / Blender Market.
