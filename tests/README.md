# TEST_PLAN Harness

Automated harness for `TEST_PLAN.md` lives at:

- `tests/test_plan_harness.py`

## Run

From repo root:

```bash
blender --background --factory-startup --python tests/test_plan_harness.py
```

If `blender` is not on `PATH` on macOS, use the app bundle binary directly:

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

Write JSON report:

```bash
blender --background --factory-startup --python tests/test_plan_harness.py -- --json-out /tmp/plinth_test_report.json
```

## Notes

- The harness maps one test handler per `T01`..`T26`.
- Visual outcomes in the manual plan are represented with headless structural checks where possible (modifiers, object states, dimensions, health/preflight status).
- Each case runs from a reset baseline so unrelated feature defaults do not interfere with targeted assertions.
