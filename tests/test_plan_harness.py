#!/usr/bin/env python3
"""
Headless Blender harness for TEST_PLAN.md.

Run all tests:
  blender --background --factory-startup --python tests/test_plan_harness.py

Run selected test IDs:
  blender --background --factory-startup --python tests/test_plan_harness.py -- --case T14 --case T18

Write JSON report:
  blender --background --factory-startup --python tests/test_plan_harness.py -- --json-out /tmp/plinth_test_report.json
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
import sys
import traceback

try:
    import bpy
except ModuleNotFoundError as exc:
    raise SystemExit(
        "This harness must run inside Blender (bpy is unavailable)."
    ) from exc


EPS = 1e-4


def _default_addon_path() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.normpath(os.path.join(here, "..", "addon", "plinth_generator_v3_4.py"))


def _parse_cli_args(argv):
    if "--" in argv:
        argv = argv[argv.index("--") + 1 :]
    else:
        argv = []

    parser = argparse.ArgumentParser(description="Run Parametric Plinth TEST_PLAN harness.")
    parser.add_argument("--addon", default=_default_addon_path(), help="Path to addon/plinth_generator_v3_4.py")
    parser.add_argument("--case", action="append", default=[], help="Test ID to run (repeatable, e.g. --case T01)")
    parser.add_argument("--list", action="store_true", help="List supported case IDs and exit")
    parser.add_argument("--json-out", default="", help="Optional JSON report path")
    parser.add_argument("--stop-on-fail", action="store_true", help="Stop immediately on first failure")
    return parser.parse_args(argv)


class Harness:
    CASES = [
        ("T01", "BOX smoke test"),
        ("T02", "CYL smoke test"),
        ("T03", "Slope direction"),
        ("T04", "Hollow open bottom"),
        ("T05", "Sealed magnet clamp warning"),
        ("T06", "Sealed margin disables magnets"),
        ("T07", "Center drains in magnets"),
        ("T08", "Center drains without sealed bottom"),
        ("T09", "Center drains without magnets"),
        ("T10", "Center drain size warning"),
        ("T11", "BOX base trim"),
        ("T12", "CYL base trim"),
        ("T13", "CYL trim clamp warning"),
        ("T14", "Error: wall too thick"),
        ("T15", "Error: top too thick"),
        ("T16", "Error: bottom too thick"),
        ("T17", "Error: drain too large"),
        ("T18", "Cancel protects scene meshes"),
        ("T19", "Health requires preview duplicate"),
        ("T20", "Forced health fail + block preview"),
        ("T21", "Manifold + health integration"),
        ("T22", "Unit input toggle (BOX)"),
        ("T23", "Inch input drives mm (BOX)"),
        ("T24", "Inch input drives mm (CYL)"),
        ("T25", "mm input back-sync to inches"),
        ("T26", "Unit mode does not break manifold/health path"),
        ("T27", "Sloped hollow roof thickness (BOX)"),
        ("T28", "Sloped hollow roof thickness (CYL)"),
        ("T29", "Export blocked after failed health"),
        ("T30", "BOX recessed panels default health"),
        ("T31", "BOX nameplate default health"),
        ("T32", "BOX dentil default health"),
        ("T33", "BOX dentil depth honored"),
        ("T34", "BOX rope default health"),
        ("T35", "CYL rope default health"),
        ("T36", "CYL bead border default health"),
        ("T37", "Modifier failure escalates to operator ERROR"),
        ("T38", "Successful Create preserves non-plinth scene meshes"),
        ("T39", "STL export writes a valid file on passing health"),
        ("T40", "Create vs Force Rebuild poll differentiation"),
        ("R01", "Single BOX perimeter magnet centers"),
        ("R02", "Single BOX corner-layout magnet centers"),
        ("R03", "Single CYL magnet centers"),
    ]

    def __init__(self, addon_path: str):
        self.addon_path = os.path.abspath(addon_path)
        self.module = self._load_addon_module(self.addon_path)

    @staticmethod
    def case_ids():
        return [c[0] for c in Harness.CASES]

    @staticmethod
    def list_cases():
        for case_id, title in Harness.CASES:
            print(f"{case_id}: {title}")

    def _load_addon_module(self, addon_path: str):
        if not os.path.exists(addon_path):
            raise FileNotFoundError(f"Addon file not found: {addon_path}")

        module_name = "plinth_generator_v3_4_harness_target"
        spec = importlib.util.spec_from_file_location(module_name, addon_path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"Unable to load addon module from {addon_path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.register()
        return module

    @property
    def props(self):
        return getattr(bpy.context.scene, self.module.PROP_NAME)

    def cleanup(self):
        try:
            self.module.clear_plinthgen_artifacts()
        except Exception:
            pass
        try:
            self.module.unregister()
        except Exception:
            pass

    def _reset_props_to_defaults(self):
        p = self.props
        for rna_prop in p.bl_rna.properties:
            ident = rna_prop.identifier
            if ident == "rna_type" or rna_prop.is_readonly:
                continue
            try:
                if rna_prop.type in {"BOOLEAN", "INT", "FLOAT", "STRING", "ENUM"}:
                    setattr(p, ident, rna_prop.default)
                elif rna_prop.type == "INT_ARRAY":
                    setattr(p, ident, tuple(rna_prop.default_array))
                elif rna_prop.type == "FLOAT_ARRAY":
                    setattr(p, ident, tuple(rna_prop.default_array))
            except Exception:
                # Some properties may reject direct default assignment due to runtime context.
                pass

    def _delete_all_mesh_objects(self):
        for obj in list(bpy.context.scene.objects):
            if obj.type == "MESH":
                bpy.data.objects.remove(obj, do_unlink=True)

    def _apply_isolation_baseline(self):
        p = self.props
        # Keep tests deterministic by disabling unrelated features; each case reenables
        # what it needs to verify.
        p.unit_input = "MM"
        p.shape = "BOX"
        p.width_mm = 76.2
        p.length_mm = 88.9
        p.height_mm = 57.15
        p.diameter_mm = 76.2
        p.cyl_height_mm = 57.15
        p.cyl_segments = 64

        p.slope_enabled = False
        p.slope_delta_mm = 0.0
        p.hollow_enabled = False
        p.sealed_bottom = False
        # Explicit numeric defaults for hollow/magnet/drain dims so tests never see
        # stale values from a prior test if _reset_props_to_defaults() silently fails.
        p.wall_thickness_mm = 6.0
        p.top_thickness_mm = 12.0
        p.bottom_thickness_mm = 3.0
        p.magnet_dia_mm = 5.0
        p.magnet_hole_depth_mm = 2.0
        p.dia_tol_mm = 0.2
        p.depth_tol_mm = 0.3
        p.inset_mm = 6.0
        p.drain_dia_mm = 4.0
        p.drain_inset_mm = 8.0
        p.magnet_center_drain_dia_mm = 1.5
        p.base_trim_radius_mm = 2.5

        p.base_trim_enabled = False
        p.profile_band_enabled = False
        p.steps_enabled = False
        p.fluting_enabled = False
        p.panels_enabled = False
        p.beads_enabled = False
        p.rope_enabled = False
        p.dentil_enabled = False
        p.scallop_enabled = False
        p.bosses_enabled = False
        p.nameplate_enabled = False
        p.texture_enabled = False
        p.feet_enabled = False

        p.magnets_count = 0
        p.drain_enabled = False
        p.drain_count = 0
        p.drain_at_magnet_centers = False

        p.preview_cuts_duplicate = True
        p.manifold_guarantee = True
        p.health_check_enabled = True
        p.health_block_preview_on_fail = False
        p.health_degenerate_area_mm2 = self.module.DEFAULT_DEGENERATE_FACE_AREA_MM2

    def reset_state(self):
        self.module.clear_plinthgen_artifacts()
        self._delete_all_mesh_objects()
        self.module.ensure_units_mm()
        self._reset_props_to_defaults()
        self._apply_isolation_baseline()

    def _preflight(self):
        return self.module.preflight_validate(self.props)

    @staticmethod
    def _assert_true(cond: bool, message: str):
        if not cond:
            raise AssertionError(message)

    @staticmethod
    def _assert_close(actual: float, expected: float, tol: float, message: str):
        if abs(actual - expected) > tol:
            raise AssertionError(f"{message}: expected {expected:.6f}, got {actual:.6f}")

    @staticmethod
    def _assert_contains(messages, needle: str, label: str):
        if not any(needle in msg for msg in messages):
            joined = " | ".join(messages) if messages else "<none>"
            raise AssertionError(f"{label} missing expected fragment '{needle}'. Got: {joined}")

    def _assert_no_preflight_errors(self):
        errors, _warnings = self._preflight()
        self._assert_true(not errors, f"Expected no preflight errors, got: {errors}")

    def _assert_preflight_error_contains(self, needle: str):
        errors, _warnings = self._preflight()
        self._assert_contains(errors, needle, "Preflight error")

    def _assert_preflight_warning_contains(self, needle: str):
        _errors, warnings = self._preflight()
        self._assert_contains(warnings, needle, "Preflight warning")

    @staticmethod
    def _op_finished(op_result) -> bool:
        return "FINISHED" in set(op_result)

    @staticmethod
    def _op_cancelled(op_result) -> bool:
        return "CANCELLED" in set(op_result)

    def _invoke_operator(self, operator, expect_result=None, expect_runtime_error_fragment=None):
        try:
            result = operator()
        except RuntimeError as exc:
            if expect_runtime_error_fragment and expect_runtime_error_fragment in str(exc):
                return {"runtime_error": str(exc), "result": None}
            raise

        if expect_result == "FINISHED":
            self._assert_true(self._op_finished(result), f"Expected FINISHED, got: {result}")
        elif expect_result == "CANCELLED":
            self._assert_true(self._op_cancelled(result), f"Expected CANCELLED, got: {result}")
        return {"runtime_error": None, "result": result}

    def _run_create_expect_finished(self, expect_runtime_error_fragment=None):
        return self._invoke_operator(
            bpy.ops.plinthgen.create_v3_4,
            expect_result="FINISHED",
            expect_runtime_error_fragment=expect_runtime_error_fragment,
        )

    def _run_create_expect_cancelled(self, expect_runtime_error_fragment=None):
        return self._invoke_operator(
            bpy.ops.plinthgen.create_v3_4,
            expect_result="CANCELLED",
            expect_runtime_error_fragment=expect_runtime_error_fragment,
        )

    def _run_rebuild_expect_finished(self, expect_runtime_error_fragment=None):
        return self._invoke_operator(
            bpy.ops.plinthgen.rebuild_v3_4,
            expect_result="FINISHED",
            expect_runtime_error_fragment=expect_runtime_error_fragment,
        )

    @staticmethod
    def _obj(name: str):
        return bpy.data.objects.get(name)

    def _require_obj(self, name: str):
        obj = self._obj(name)
        self._assert_true(obj is not None, f"Expected object '{name}' to exist.")
        return obj

    @staticmethod
    def _mesh_world_coords(obj):
        return [obj.matrix_world @ v.co for v in obj.data.vertices]

    def _mesh_dimensions(self, obj):
        coords = self._mesh_world_coords(obj)
        self._assert_true(bool(coords), f"Object '{obj.name}' has no vertices.")
        xs = [c.x for c in coords]
        ys = [c.y for c in coords]
        zs = [c.z for c in coords]
        return (max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs))

    def _mesh_max_z(self, obj):
        coords = self._mesh_world_coords(obj)
        self._assert_true(bool(coords), f"Object '{obj.name}' has no vertices.")
        return max(c.z for c in coords)

    def _side_top_thickness(self, outer_obj, inner_obj, axis: str, positive: bool):
        return self._side_peak_z(outer_obj, axis, positive) - self._side_peak_z(inner_obj, axis, positive)

    def _mesh_xy_center(self, obj):
        coords = self._mesh_world_coords(obj)
        self._assert_true(bool(coords), f"Object '{obj.name}' has no vertices.")
        xs = [c.x for c in coords]
        ys = [c.y for c in coords]
        return ((max(xs) + min(xs)) * 0.5, (max(ys) + min(ys)) * 0.5)

    def _side_peak_z(self, obj, axis: str, positive: bool):
        coords = self._mesh_world_coords(obj)
        if axis == "X":
            selected = [c.z for c in coords if (c.x > 0.0 if positive else c.x < 0.0)]
        else:
            selected = [c.z for c in coords if (c.y > 0.0 if positive else c.y < 0.0)]
        self._assert_true(bool(selected), f"No vertices found on {axis} {'+' if positive else '-'} side.")
        return max(selected)

    def _active_obj(self):
        return bpy.context.view_layer.objects.active

    # ---- T01..T26 ---------------------------------------------------------
    def case_t01(self):
        self._assert_no_preflight_errors()
        self._run_create_expect_finished()
        preview = self._require_obj(self.module.OBJ_PREVIEW)
        main = self._require_obj(self.module.OBJ_MAIN)
        self._assert_true(main.hide_get(), "Main object should be hidden after successful preview build.")
        self._assert_true(not preview.hide_get(), "Preview object should be visible.")
        self._assert_true(self.props.health_last_ran, "Health report should run when preview duplicate is enabled.")
        self._assert_true(self._active_obj() == preview, "Preview should be active object.")

    def case_t02(self):
        p = self.props
        p.shape = "CYL"
        self._assert_no_preflight_errors()
        self._run_create_expect_finished()
        preview = self._require_obj(self.module.OBJ_PREVIEW)
        self._assert_true(self.props.health_last_ran, "Health report should run for CYL smoke test.")
        self._assert_true(self._active_obj() == preview, "Preview should be active object.")

    def case_t03(self):
        p = self.props
        p.slope_enabled = True
        p.slope_delta_mm = 5.0
        p.slope_axis = "X"
        p.slope_high_side = "POS"
        self._assert_no_preflight_errors()
        self._run_create_expect_finished()
        preview = self._require_obj(self.module.OBJ_PREVIEW)
        pos_peak = self._side_peak_z(preview, "X", positive=True)
        neg_peak = self._side_peak_z(preview, "X", positive=False)
        self._assert_true(pos_peak > (neg_peak + EPS), "Expected +X side to be higher for POS high side.")

        p.slope_high_side = "NEG"
        self._run_rebuild_expect_finished()
        preview = self._require_obj(self.module.OBJ_PREVIEW)
        pos_peak_2 = self._side_peak_z(preview, "X", positive=True)
        neg_peak_2 = self._side_peak_z(preview, "X", positive=False)
        self._assert_true(neg_peak_2 > (pos_peak_2 + EPS), "Expected -X side to be higher for NEG high side.")

    def case_t04(self):
        p = self.props
        p.hollow_enabled = True
        p.sealed_bottom = False
        p.drain_enabled = True
        p.drain_count = 2
        self._assert_no_preflight_errors()
        self._run_create_expect_finished()
        main = self._require_obj(self.module.OBJ_MAIN)

        mod_names = {m.name for m in main.modifiers}
        self._assert_true("HollowCut" in mod_names, "Expected HollowCut modifier on main object.")
        self._assert_true("DrainCut" in mod_names, "Expected DrainCut modifier on main object.")

    def case_t05(self):
        p = self.props
        p.hollow_enabled = True
        p.sealed_bottom = True
        p.bottom_thickness_mm = 1.0
        p.magnets_count = 4
        p.magnet_hole_depth_mm = 2.0
        p.depth_tol_mm = 0.3
        self._assert_preflight_warning_contains("Magnet hole depth will clamp to 0.50mm due to sealed bottom.")
        self._run_create_expect_finished()
        cutters_obj = self._require_obj(self.module.OBJ_CUTTERS)
        top_z = self._mesh_max_z(cutters_obj)
        self._assert_close(top_z, 0.5, 0.05, "Clamped magnet cutter top Z")

    def case_t06(self):
        p = self.props
        p.hollow_enabled = True
        p.sealed_bottom = True
        # Use 0.3 mm (not 0.4) so max_safe = 0.3 - 0.5 = -0.2, well below zero.
        # 0.4 was too close to the 0.5 mm clamp margin; float storage could produce
        # 0.40000001 making max_safe marginally positive and creating cutters.
        p.bottom_thickness_mm = 0.3
        p.magnets_count = 4
        self._assert_preflight_warning_contains("Magnet holes are disabled because sealed bottom is at/below clamp margin.")
        self._run_create_expect_finished()
        self._assert_true(self._obj(self.module.OBJ_CUTTERS) is None, "Magnet cutter object should not be generated.")
        main = self._require_obj(self.module.OBJ_MAIN)
        mod_names = {m.name for m in main.modifiers}
        self._assert_true("MagnetCut" not in mod_names, "MagnetCut modifier should not exist when magnets are disabled.")

    def case_t07(self):
        p = self.props
        p.hollow_enabled = True
        p.sealed_bottom = True
        p.magnets_count = 4
        p.drain_enabled = True
        p.drain_count = 0
        p.drain_at_magnet_centers = True
        self._assert_no_preflight_errors()
        self._run_create_expect_finished()
        # drain_count=0 means no regular drain cutters should exist.
        self._assert_true(
            self._obj(self.module.OBJ_DRAINS) is None,
            "Regular drain cutter object should not be created when drain_count=0.",
        )
        center_drains = self._require_obj(self.module.OBJ_DRAINS_MAGNET_CENTER)
        self._assert_true(len(center_drains.data.vertices) > 0, "Expected center-drain cutter mesh data.")

    def case_t08(self):
        p = self.props
        p.hollow_enabled = True
        p.sealed_bottom = False
        p.magnets_count = 4
        p.drain_enabled = True
        p.drain_count = 0
        p.drain_at_magnet_centers = True
        self._assert_preflight_warning_contains("Drain at Magnet Centers requires Sealed Bottom.")
        self._run_create_expect_finished()
        self._assert_true(
            self._obj(self.module.OBJ_DRAINS_MAGNET_CENTER) is None,
            "Center-drain cutters should not be created without sealed bottom.",
        )

    def case_t09(self):
        p = self.props
        p.hollow_enabled = True
        p.sealed_bottom = True
        p.magnets_count = 0
        p.drain_enabled = True
        p.drain_count = 0
        p.drain_at_magnet_centers = True
        self._assert_preflight_warning_contains("Drain at Magnet Centers requires at least one magnet.")
        self._run_create_expect_finished()
        self._assert_true(
            self._obj(self.module.OBJ_DRAINS_MAGNET_CENTER) is None,
            "Center-drain cutters should not be created without magnets.",
        )

    def case_t10(self):
        p = self.props
        p.hollow_enabled = True
        p.sealed_bottom = True
        p.magnets_count = 4
        p.drain_enabled = True
        p.drain_count = 0
        p.drain_at_magnet_centers = True
        p.magnet_dia_mm = 5.0
        p.dia_tol_mm = 0.2
        # Stay slightly above the computed cutter diameter to avoid equality-edge
        # float noise hiding the warning.
        p.magnet_center_drain_dia_mm = 5.25
        self._assert_preflight_warning_contains("Magnet center drain diameter should be smaller than magnet hole diameter.")
        self._run_create_expect_finished()

    def case_t11(self):
        p = self.props
        p.shape = "BOX"
        p.base_trim_enabled = True
        p.base_trim_radius_mm = 2.5
        self._assert_no_preflight_errors()
        self._run_create_expect_finished()
        self._require_obj(self.module.OBJ_BASE_TRIM)
        main = self._require_obj(self.module.OBJ_MAIN)
        mod_names = {m.name for m in main.modifiers}
        self._assert_true("BaseTrimUnion" in mod_names, "Expected BaseTrimUnion modifier for BOX trim.")

    def case_t12(self):
        p = self.props
        p.shape = "CYL"
        p.base_trim_enabled = True
        p.base_trim_radius_mm = 2.5
        self._assert_no_preflight_errors()
        self._run_create_expect_finished()
        self._require_obj(self.module.OBJ_BASE_TRIM)
        main = self._require_obj(self.module.OBJ_MAIN)
        mod_names = {m.name for m in main.modifiers}
        self._assert_true("BaseTrimUnion" in mod_names, "Expected BaseTrimUnion modifier for CYL trim.")

    def case_t13(self):
        p = self.props
        p.shape = "CYL"
        p.diameter_mm = 20.0
        p.base_trim_enabled = True
        p.base_trim_radius_mm = 15.0
        self._assert_preflight_warning_contains("Cylinder trim radius will clamp to 9.90mm.")
        self._assert_no_preflight_errors()
        self._run_create_expect_finished()

    def case_t14(self):
        p = self.props
        p.shape = "BOX"
        p.width_mm = 20.0
        p.length_mm = 20.0
        p.hollow_enabled = True
        p.wall_thickness_mm = 11.0
        self._assert_preflight_error_contains("Wall thickness is too large for selected box dimensions.")
        self._run_create_expect_cancelled(expect_runtime_error_fragment="Preflight failed")

    def case_t15(self):
        p = self.props
        p.hollow_enabled = True
        p.height_mm = 10.0
        p.top_thickness_mm = 10.0
        self._assert_preflight_error_contains("Top thickness must be less than total height when Hollow is enabled.")
        self._run_create_expect_cancelled(expect_runtime_error_fragment="Preflight failed")

    def case_t16(self):
        p = self.props
        p.hollow_enabled = True
        p.sealed_bottom = True
        p.height_mm = 20.0
        p.top_thickness_mm = 5.0
        p.bottom_thickness_mm = 15.0
        self._assert_preflight_error_contains("Bottom thickness must be less than (height - top thickness).")
        self._run_create_expect_cancelled(expect_runtime_error_fragment="Preflight failed")

    def case_t17(self):
        p = self.props
        p.shape = "BOX"
        p.hollow_enabled = True
        p.width_mm = 20.0
        p.length_mm = 20.0
        p.drain_enabled = True
        p.drain_count = 2
        p.drain_dia_mm = 40.0
        self._assert_preflight_error_contains("Drain diameter is too large for selected box dimensions.")
        self._run_create_expect_cancelled(expect_runtime_error_fragment="Preflight failed")

    def case_t18(self):
        p = self.props
        # Create a sentinel mesh object that should remain when preflight cancels.
        sentinel_name = "Harness_SentinelCube"
        cube_mesh = self.module.make_box_mesh(10.0, 10.0, 10.0, "Harness_SentinelCubeMesh")
        cube_obj = bpy.data.objects.new(sentinel_name, cube_mesh)
        bpy.context.scene.collection.objects.link(cube_obj)

        p.shape = "BOX"
        p.width_mm = 20.0
        p.length_mm = 20.0
        p.hollow_enabled = True
        p.wall_thickness_mm = 11.0
        self._assert_preflight_error_contains("Wall thickness is too large for selected box dimensions.")
        self._run_create_expect_cancelled(expect_runtime_error_fragment="Preflight failed")
        self._assert_true(bpy.data.objects.get(sentinel_name) is not None, "Sentinel cube should remain after cancel.")

    def case_t19(self):
        p = self.props
        p.preview_cuts_duplicate = False
        p.health_check_enabled = True
        self._assert_preflight_warning_contains("Post-build health check requires Preview Cuts (Duplicate).")
        self._run_create_expect_finished()
        self._assert_true(not p.health_last_ran, "Health check should not run without preview duplicate.")
        # Exact-string match: must stay in sync with reset_health_report() call in
        # the build_plinth else-branch of plinth_generator_v3_4.py.
        self._assert_true(
            p.health_last_summary == "Health check requires Preview Cuts (Duplicate).",
            f"Unexpected health summary: {p.health_last_summary}",
        )

    def case_t20(self):
        p = self.props
        p.shape = "BOX"
        p.width_mm = 1.0
        p.length_mm = 1.0
        p.height_mm = 1.0
        p.health_check_enabled = True
        p.health_block_preview_on_fail = True
        # Use 1.1 mm² (not 1.0) so the threshold is strictly above the exact face area
        # of a 1mm×1mm face (1.0 mm²), protecting against floating-point drift in
        # calc_area() that could return 1.0000000001 and flip the health result.
        p.health_degenerate_area_mm2 = 1.1
        p.preview_cuts_duplicate = True
        p.magnets_count = 0
        p.drain_enabled = False
        self._assert_no_preflight_errors()
        self._run_create_expect_finished(expect_runtime_error_fragment="Preview blocked by health check")

        preview = self._require_obj(self.module.OBJ_PREVIEW)
        main = self._require_obj(self.module.OBJ_MAIN)
        self._assert_true(p.health_last_ran, "Health check should run.")
        self._assert_true(not p.health_last_pass, "Health check should fail in forced-fail setup.")
        self._assert_true(preview.hide_get(), "Preview should be hidden when block-on-fail is enabled.")
        self._assert_true(not main.hide_get(), "Main should be shown when preview is blocked.")
        self._assert_true(self._active_obj() == main, "Main should be active when preview is blocked.")

    def case_t21(self):
        p = self.props
        p.hollow_enabled = True
        p.sealed_bottom = False
        p.drain_enabled = True
        p.drain_count = 2
        p.preview_cuts_duplicate = True
        p.manifold_guarantee = True
        p.health_check_enabled = True
        self._assert_no_preflight_errors()
        self._run_create_expect_finished()
        self._assert_true(p.health_last_ran, "Health report should run in manifold+health integration case.")
        self._assert_true(bool(p.health_last_summary), "Expected non-empty health summary.")

    def case_t22(self):
        p = self.props
        p.shape = "BOX"
        p.width_mm = 76.2
        p.length_mm = 88.9
        p.height_mm = 57.15
        p.unit_input = "IN"
        self._assert_close(p.width_in, 3.0, 1e-4, "Width inches")
        self._assert_close(p.length_in, 3.5, 1e-4, "Length inches")
        self._assert_close(p.height_in, 2.25, 1e-4, "Height inches")

    def case_t23(self):
        p = self.props
        p.shape = "BOX"
        p.unit_input = "IN"
        p.width_in = 4.0
        p.length_in = 6.0
        p.height_in = 2.0
        self._assert_close(p.width_mm, 101.6, 1e-4, "Width mm")
        self._assert_close(p.length_mm, 152.4, 1e-4, "Length mm")
        self._assert_close(p.height_mm, 50.8, 1e-4, "Height mm")
        self._run_create_expect_finished()
        preview = self._require_obj(self.module.OBJ_PREVIEW)
        dx, dy, dz = self._mesh_dimensions(preview)
        self._assert_close(dx, 101.6, 0.2, "Preview X dimension")
        self._assert_close(dy, 152.4, 0.2, "Preview Y dimension")
        self._assert_close(dz, 50.8, 0.2, "Preview Z dimension")

    def case_t24(self):
        p = self.props
        p.shape = "CYL"
        p.unit_input = "IN"
        p.diameter_in = 5.0
        p.cyl_height_in = 2.5
        self._assert_close(p.diameter_mm, 127.0, 1e-4, "Diameter mm")
        self._assert_close(p.cyl_height_mm, 63.5, 1e-4, "Cylinder height mm")
        self._run_create_expect_finished()
        preview = self._require_obj(self.module.OBJ_PREVIEW)
        dx, dy, dz = self._mesh_dimensions(preview)
        self._assert_close(dx, 127.0, 0.3, "Preview X dimension")
        self._assert_close(dy, 127.0, 0.3, "Preview Y dimension")
        self._assert_close(dz, 63.5, 0.2, "Preview Z dimension")

    def case_t25(self):
        p = self.props
        p.unit_input = "MM"
        p.width_mm = 50.8
        p.length_mm = 76.2
        p.unit_input = "IN"
        self._assert_close(p.width_in, 2.0, 1e-4, "Width inches back-sync")
        self._assert_close(p.length_in, 3.0, 1e-4, "Length inches back-sync")

    def case_t26(self):
        p = self.props
        p.shape = "BOX"
        p.unit_input = "IN"
        p.width_in = 4.0
        p.length_in = 3.0
        p.height_in = 2.0
        p.preview_cuts_duplicate = True
        p.manifold_guarantee = True
        p.health_check_enabled = True
        self._assert_no_preflight_errors()
        self._run_create_expect_finished()
        self._assert_true(p.health_last_ran, "Health report should run for inch-input manifold/health case.")

    def case_t27(self):
        p = self.props
        p.shape = "BOX"
        p.width_mm = 100.0
        p.length_mm = 80.0
        p.height_mm = 50.0
        p.hollow_enabled = True
        p.sealed_bottom = True
        p.wall_thickness_mm = 5.0
        p.top_thickness_mm = 10.0
        p.bottom_thickness_mm = 3.0
        p.slope_enabled = True
        p.slope_delta_mm = 5.0
        p.slope_axis = "X"
        p.slope_high_side = "POS"
        self._assert_no_preflight_errors()
        self._run_create_expect_finished()
        main = self._require_obj(self.module.OBJ_MAIN)
        hollow = self._require_obj(self.module.OBJ_HOLLOW)
        self._assert_close(self._side_top_thickness(main, hollow, "X", positive=True), 10.0, 0.05, "BOX roof thickness +X")
        self._assert_close(self._side_top_thickness(main, hollow, "X", positive=False), 10.0, 0.05, "BOX roof thickness -X")

    def case_t28(self):
        p = self.props
        p.shape = "CYL"
        p.diameter_mm = 100.0
        p.cyl_height_mm = 50.0
        p.hollow_enabled = True
        p.sealed_bottom = True
        p.wall_thickness_mm = 5.0
        p.top_thickness_mm = 10.0
        p.bottom_thickness_mm = 3.0
        p.slope_enabled = True
        p.slope_delta_mm = 5.0
        p.slope_axis = "X"
        p.slope_high_side = "POS"
        self._assert_no_preflight_errors()
        self._run_create_expect_finished()
        main = self._require_obj(self.module.OBJ_MAIN)
        hollow = self._require_obj(self.module.OBJ_HOLLOW)
        self._assert_close(self._side_top_thickness(main, hollow, "X", positive=True), 10.0, 0.05, "CYL roof thickness +X")
        self._assert_close(self._side_top_thickness(main, hollow, "X", positive=False), 10.0, 0.05, "CYL roof thickness -X")

    def case_t29(self):
        p = self.props
        p.shape = "BOX"
        p.width_mm = 1.0
        p.length_mm = 1.0
        p.height_mm = 1.0
        p.health_check_enabled = True
        p.health_block_preview_on_fail = True
        p.health_degenerate_area_mm2 = 1.1
        p.preview_cuts_duplicate = True
        p.magnets_count = 0
        p.drain_enabled = False
        self._assert_no_preflight_errors()
        self._run_create_expect_finished(expect_runtime_error_fragment="Preview blocked by health check")
        preview = self._require_obj(self.module.OBJ_PREVIEW)
        self._assert_true(preview.hide_get(), "Preview should stay hidden after a blocked build.")
        self._assert_true(not bpy.ops.plinthgen.export_stl_v3_4.poll(), "Export operator should be unavailable while preview is blocked.")
        out_path = "/tmp/plinth_export_blocked_harness.stl"
        if os.path.exists(out_path):
            os.remove(out_path)
        result = self._invoke_operator(
            lambda: bpy.ops.plinthgen.export_stl_v3_4(filepath=out_path),
            expect_runtime_error_fragment="poll() failed",
        )
        self._assert_true(result["runtime_error"] is not None, "Expected export invocation to fail poll when preview is blocked.")
        self._assert_true(not os.path.exists(out_path), "Blocked export should not write an STL file.")

    def case_t30(self):
        p = self.props
        p.shape = "BOX"
        p.panels_enabled = True
        p.magnets_count = 0
        p.drain_enabled = False
        self._assert_no_preflight_errors()
        self._run_create_expect_finished()
        self._assert_true(p.health_last_pass, f"Expected recessed panels build to pass health, got: {p.health_last_summary}")

    def case_t31(self):
        p = self.props
        p.shape = "BOX"
        p.nameplate_enabled = True
        p.magnets_count = 0
        p.drain_enabled = False
        self._assert_no_preflight_errors()
        self._run_create_expect_finished()
        self._assert_true(p.health_last_pass, f"Expected nameplate build to pass health, got: {p.health_last_summary}")

    def case_t32(self):
        p = self.props
        p.shape = "BOX"
        p.dentil_enabled = True
        p.magnets_count = 0
        p.drain_enabled = False
        self._assert_no_preflight_errors()
        self._run_create_expect_finished()
        self._assert_true(p.health_last_pass, f"Expected dentil build to pass health, got: {p.health_last_summary}")

    def case_t33(self):
        mesh = self.module.make_dentil_course_mesh(
            shape="BOX",
            width_mm=100.0,
            length_mm=80.0,
            diameter_mm=100.0,
            height_mm=50.0,
            dentil_w_mm=2.0,
            dentil_d_mm=10.0,
            dentil_h_mm=4.0,
            dentil_spacing_mm=200.0,
            at_top=True,
            mesh_name="Harness_DentilDepthMesh",
        )
        try:
            ys = [v.co.y for v in mesh.vertices]
            self._assert_true(bool(ys), "Expected dentil mesh to contain vertices.")
            self._assert_close(max(ys) - 40.0, 10.0, 0.2, "BOX dentil +Y depth")
            self._assert_close((-40.0) - min(ys), 10.0, 0.2, "BOX dentil -Y depth")
        finally:
            bpy.data.meshes.remove(mesh)

    def case_t34(self):
        p = self.props
        p.shape = "BOX"
        p.rope_enabled = True
        p.magnets_count = 0
        p.drain_enabled = False
        self._assert_no_preflight_errors()
        self._run_create_expect_finished()
        self._assert_true(p.health_last_pass, f"Expected BOX rope build to pass health, got: {p.health_last_summary}")

    def case_t35(self):
        p = self.props
        p.shape = "CYL"
        p.rope_enabled = True
        p.magnets_count = 0
        p.drain_enabled = False
        self._assert_no_preflight_errors()
        self._run_create_expect_finished()
        self._assert_true(p.health_last_pass, f"Expected CYL rope build to pass health, got: {p.health_last_summary}")

    def case_t36(self):
        p = self.props
        p.shape = "CYL"
        p.beads_enabled = True
        p.magnets_count = 0
        p.drain_enabled = False
        self._assert_no_preflight_errors()
        self._run_create_expect_finished()
        self._assert_true(p.health_last_pass, f"Expected CYL bead build to pass health, got: {p.health_last_summary}")

    def case_t37(self):
        """CR-#1: when apply_all_modifiers reports failures, the operator
        must report ERROR, return CANCELLED, and clean up partial plinth objects."""
        p = self.props
        p.preview_cuts_duplicate = True
        p.health_check_enabled = False  # health needs a valid mesh; skip
        p.hollow_enabled = True          # guarantees at least one modifier exists
        p.manifold_guarantee = False     # keep the path short

        original = self.module.apply_all_modifiers

        def fake_apply_all_modifiers(obj):
            # Mirror the real cleanup: drop modifiers so the test isn't left
            # with a half-modified preview, but report a fake failure.
            for m in list(obj.modifiers):
                try:
                    obj.modifiers.remove(m)
                except Exception:
                    pass
            return ["FakeFailedModifier"]

        try:
            self.module.apply_all_modifiers = fake_apply_all_modifiers
            self._run_create_expect_cancelled(
                expect_runtime_error_fragment="Modifier apply failed",
            )
        finally:
            self.module.apply_all_modifiers = original

        self._assert_true(
            self._obj(self.module.OBJ_MAIN) is None,
            "Main plinth must be cleaned up after a modifier-apply failure.",
        )
        self._assert_true(
            self._obj(self.module.OBJ_PREVIEW) is None,
            "Preview must be cleaned up after a modifier-apply failure.",
        )

    def case_t38(self):
        """CR-#4: a successful Create must not delete non-plinth scene meshes."""
        sentinel_name = "Harness_SuccessSentinel"
        cube_mesh = self.module.make_box_mesh(
            10.0, 10.0, 10.0, "Harness_SuccessSentinelMesh"
        )
        cube_obj = bpy.data.objects.new(sentinel_name, cube_mesh)
        bpy.context.scene.collection.objects.link(cube_obj)

        self._assert_no_preflight_errors()
        self._run_create_expect_finished()

        self._assert_true(
            bpy.data.objects.get(sentinel_name) is not None,
            "Sentinel cube must survive a successful Create.",
        )
        # Sanity: a plinth was actually built (otherwise the test proves nothing).
        self._require_obj(self.module.OBJ_PREVIEW)

    def case_t39(self):
        """CR-#3: STL export writes a non-empty file when health passes."""
        import tempfile

        p = self.props
        p.preview_cuts_duplicate = True
        p.health_check_enabled = True

        self._assert_no_preflight_errors()
        self._run_create_expect_finished()
        self._assert_true(
            p.health_last_pass,
            f"Default plinth should pass health; got: {p.health_last_summary}",
        )
        self._assert_true(
            bpy.ops.plinthgen.export_stl_v3_4.poll(),
            "Export operator should be available when health passes.",
        )

        out_path = os.path.join(tempfile.gettempdir(), "plinth_export_harness_t39.stl")
        if os.path.exists(out_path):
            os.remove(out_path)
        try:
            self._invoke_operator(
                lambda: bpy.ops.plinthgen.export_stl_v3_4(filepath=out_path),
                expect_result="FINISHED",
            )
            self._assert_true(os.path.exists(out_path), "Export must write the STL file.")
            # Binary STL = 80-byte header + 4-byte triangle count + 50 bytes/triangle.
            # Any non-trivial plinth has >>1 triangle, so well above 84 bytes.
            self._assert_true(
                os.path.getsize(out_path) >= 84,
                f"Exported STL is suspiciously small: {os.path.getsize(out_path)} bytes",
            )
        finally:
            if os.path.exists(out_path):
                os.remove(out_path)

    def case_t40(self):
        """CR-#9: Create is disabled while a plinth exists; Force Rebuild
        is disabled when none exists."""
        # Fresh state: no plinth.
        self._assert_true(
            bpy.ops.plinthgen.create_v3_4.poll(),
            "Create should be available when no plinth exists.",
        )
        self._assert_true(
            not bpy.ops.plinthgen.rebuild_v3_4.poll(),
            "Force Rebuild should be disabled when no plinth exists.",
        )

        self._run_create_expect_finished()

        # After Create succeeds, polarity flips.
        self._assert_true(
            not bpy.ops.plinthgen.create_v3_4.poll(),
            "Create should be disabled while a plinth exists.",
        )
        self._assert_true(
            bpy.ops.plinthgen.rebuild_v3_4.poll(),
            "Force Rebuild should be available once a plinth exists.",
        )

        # Force Rebuild should succeed and leave a plinth in place.
        self._run_rebuild_expect_finished()
        self._require_obj(self.module.OBJ_MAIN)

    def _assert_single_magnet_centered(self):
        cutters_obj = self._require_obj(self.module.OBJ_CUTTERS)
        cx, cy = self._mesh_xy_center(cutters_obj)
        self._assert_close(cx, 0.0, 0.05, "Single magnet X center")
        self._assert_close(cy, 0.0, 0.05, "Single magnet Y center")

    def case_r01(self):
        p = self.props
        p.shape = "BOX"
        p.magnets_count = 1
        p.magnet_layout_box = "PERIMETER"
        self._assert_no_preflight_errors()
        self._run_create_expect_finished()
        self._assert_single_magnet_centered()

    def case_r02(self):
        p = self.props
        p.shape = "BOX"
        p.magnets_count = 1
        p.magnet_layout_box = "CORNERS"
        self._assert_no_preflight_errors()
        self._run_create_expect_finished()
        self._assert_single_magnet_centered()

    def case_r03(self):
        p = self.props
        p.shape = "CYL"
        p.magnets_count = 1
        self._assert_no_preflight_errors()
        self._run_create_expect_finished()
        self._assert_single_magnet_centered()

    # ---- Runner -----------------------------------------------------------
    def run(self, selected_case_ids=None, stop_on_fail=False):
        selected = set(selected_case_ids or [])
        results = []

        for case_id, title in self.CASES:
            if selected and case_id not in selected:
                continue

            self.reset_state()
            fn_name = f"case_{case_id.lower()}"
            fn = getattr(self, fn_name, None)
            if fn is None:
                results.append(
                    {
                        "id": case_id,
                        "title": title,
                        "status": "ERROR",
                        "detail": f"Missing handler function: {fn_name}",
                    }
                )
                if stop_on_fail:
                    break
                continue

            try:
                fn()
                results.append({"id": case_id, "title": title, "status": "PASS", "detail": ""})
                print(f"[PASS] {case_id} {title}")
            except AssertionError as exc:
                results.append({"id": case_id, "title": title, "status": "FAIL", "detail": str(exc)})
                print(f"[FAIL] {case_id} {title}: {exc}")
                if stop_on_fail:
                    break
            except Exception as exc:
                tb = traceback.format_exc()
                results.append({"id": case_id, "title": title, "status": "ERROR", "detail": tb})
                print(f"[ERROR] {case_id} {title}: {exc}")
                if stop_on_fail:
                    break

        return results


def _normalize_case_ids(raw_case_args):
    if not raw_case_args:
        return []
    normalized = []
    for raw in raw_case_args:
        token = raw.strip().upper()
        if not token:
            continue
        if not token.startswith(("T", "R")):
            token = f"T{token}"
        normalized.append(token)
    return normalized


def main():
    args = _parse_cli_args(sys.argv)
    selected = _normalize_case_ids(args.case)

    if args.list:
        Harness.list_cases()
        return 0

    known = set(Harness.case_ids())
    unknown = [case_id for case_id in selected if case_id not in known]
    if unknown:
        print(f"Unknown case ID(s): {', '.join(unknown)}")
        return 2

    harness = Harness(args.addon)
    try:
        results = harness.run(selected_case_ids=selected, stop_on_fail=args.stop_on_fail)
    finally:
        harness.cleanup()

    passed = sum(1 for r in results if r["status"] == "PASS")
    failed = sum(1 for r in results if r["status"] == "FAIL")
    errors = sum(1 for r in results if r["status"] == "ERROR")
    total = len(results)
    print(f"Ran {total} case(s): {passed} PASS, {failed} FAIL, {errors} ERROR")

    if args.json_out:
        report = {
            "addon": os.path.abspath(args.addon),
            "total": total,
            "passed": passed,
            "failed": failed,
            "errors": errors,
            "results": results,
        }
        out_path = os.path.abspath(args.json_out)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
        print(f"Wrote JSON report: {out_path}")

    return 0 if (failed == 0 and errors == 0) else 1


if __name__ == "__main__":
    raise SystemExit(main())
