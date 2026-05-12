#!/usr/bin/env python3
"""
Install test for the Parametric Plinth Generator distribution zip.

Installs the zip into a hermetic Blender user-resources directory, enables the
addon, runs a default Create, and asserts the build finished. Mimics a buyer's
first-install experience.

Usage:
    BLENDER_USER_RESOURCES=$(mktemp -d) \
      /Applications/Blender.app/Contents/MacOS/Blender --background --factory-startup \
      --python tests/install_test.py -- dist/plinth_generator_v3.4.1.zip
"""

from __future__ import annotations

import os
import sys

try:
    import bpy
except ModuleNotFoundError as exc:
    raise SystemExit("This test must run inside Blender (bpy unavailable).") from exc


ADDON_MODULE = "plinth_generator_v3_4"


def _parse_zip_path(argv):
    if "--" not in argv:
        raise SystemExit("Pass the zip path after `--`, e.g. `... -- dist/plinth_generator_v3.4.1.zip`")
    args = argv[argv.index("--") + 1 :]
    if not args:
        raise SystemExit("Missing zip path argument.")
    zip_path = os.path.abspath(args[0])
    if not os.path.exists(zip_path):
        raise SystemExit(f"Zip not found: {zip_path}")
    return zip_path


def main() -> int:
    zip_path = _parse_zip_path(sys.argv)
    print(f"Installing addon zip: {zip_path}")

    # Install + enable
    bpy.ops.preferences.addon_install(filepath=zip_path, overwrite=True)
    bpy.ops.preferences.addon_enable(module=ADDON_MODULE)

    # Property group should be attached to the scene
    props = getattr(bpy.context.scene, "plinthgen_props_v3_4", None)
    if props is None:
        raise SystemExit("Addon enabled but property group is missing from scene.")
    print("Property group attached to scene: OK")

    # The Create operator should be registered and pollable
    if not hasattr(bpy.ops.plinthgen, "create_v3_4"):
        raise SystemExit("plinthgen.create_v3_4 operator not registered.")
    if not bpy.ops.plinthgen.create_v3_4.poll():
        raise SystemExit("plinthgen.create_v3_4.poll() returned False on a fresh scene.")
    print("Create operator registered and poll-passes: OK")

    # Run a default Create
    result = bpy.ops.plinthgen.create_v3_4()
    if "FINISHED" not in set(result):
        raise SystemExit(f"Create did not FINISH; got {result}")
    print(f"Create returned: {result}")

    # Confirm a plinth object now exists in the scene
    main_obj = bpy.data.objects.get("Plinth_Main_v3_4")
    if main_obj is None:
        raise SystemExit("Create reported FINISHED but Plinth_Main_v3_4 object is missing.")
    preview_obj = bpy.data.objects.get("Plinth_Main_v3_4_PREVIEW")
    if preview_obj is None:
        raise SystemExit("Preview object missing after default Create.")
    print(f"Built objects: main={main_obj.name}, preview={preview_obj.name}")

    # Sanity: preview mesh has vertices
    if not preview_obj.data.vertices:
        raise SystemExit("Preview mesh has zero vertices.")
    print(f"Preview vertex count: {len(preview_obj.data.vertices)}")

    print("\nINSTALL TEST: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
