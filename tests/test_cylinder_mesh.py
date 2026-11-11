"""Unit tests for editable finish-cylinder mesh (200 control points)."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import simust_cylinder_mesh as mesh  # noqa: E402


class CylinderMeshTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        mesh.MESH_FILE = os.path.join(self.tmp, "goal_cylinder_meshes.json")
        mesh.reload_store()

    def test_control_point_count_is_200(self):
        self.assertEqual(mesh.control_point_count(), 200)
        pts = mesh.make_cylinder_points(640, 180, 40, 31)
        self.assertEqual(len(pts), 200)
        faces = mesh.cylinder_faces()
        self.assertGreater(len(faces), 0)
        # Connectivity uses only indices in 0..199
        self.assertTrue(int(faces.max()) < 200)
        self.assertTrue(int(faces.min()) >= 0)

    def test_center_inside_undeformed(self):
        pts = mesh.make_cylinder_points(100, 200, 30, 31)
        # Base center and mid-shaft (image-up) stay inside the footprint.
        self.assertTrue(mesh.point_inside_mesh((100, 200), pts))
        self.assertTrue(mesh.point_inside_mesh((100, 200 - 15), pts))
        self.assertFalse(mesh.point_inside_mesh((100 + 50, 200), pts))

    def test_all_points_fit_classic_green_body(self):
        cx, cy, radius, height = 120.0, 210.0, 36.0, 31.0
        pts = mesh.make_cylinder_points(cx, cy, radius, height)
        for p in pts:
            self.assertTrue(
                mesh.point_on_classic_cylinder_xy(
                    float(p[0]), float(p[1]), cx, cy, radius, height
                ),
                msg=f"point ({p[0]}, {p[1]}) outside classic cylinder",
            )
        # Bottom ring lies on the base circle; top ring on the top ellipse.
        r = max(4.0, radius)
        ry = max(3.0, r * 0.35)
        top_cy = cy - height
        for t in range(mesh.N_THETA):
            bx, by = float(pts[t, 0]), float(pts[t, 1])
            self.assertAlmostEqual((bx - cx) ** 2 + (by - cy) ** 2, r * r, places=5)
            tx, ty = float(pts[(mesh.N_HEIGHT - 1) * mesh.N_THETA + t, 0]), float(
                pts[(mesh.N_HEIGHT - 1) * mesh.N_THETA + t, 1]
            )
            self.assertAlmostEqual(
                ((tx - cx) / r) ** 2 + ((ty - top_cy) / ry) ** 2, 1.0, places=5
            )

    def test_smooth_deform_preserves_count_and_moves_neighbors(self):
        pts = mesh.make_cylinder_points(0, 0, 20, 40)
        before = pts.copy()
        after = mesh.smooth_deform(pts, 0, (5.0, 0.0, 0.0), smooth=True, influence=12.0)
        self.assertEqual(len(after), 200)
        self.assertGreater(float(after[0, 0]), float(before[0, 0]))
        # Neighbor on same ring should move some.
        self.assertGreater(float(after[1, 0]), float(before[1, 0]))

    def test_deform_without_smooth_only_moves_selected(self):
        pts = mesh.make_cylinder_points(0, 0, 20, 40)
        before = pts.copy()
        after = mesh.smooth_deform(pts, 5, (0.0, 4.0, 0.0), smooth=False)
        self.assertAlmostEqual(float(after[5, 1] - before[5, 1]), 4.0, places=5)
        for i in range(len(after)):
            if i == 5:
                continue
            self.assertAlmostEqual(float(after[i, 0]), float(before[i, 0]), places=5)
            self.assertAlmostEqual(float(after[i, 1]), float(before[i, 1]), places=5)

    def test_save_and_hit_uses_deformed_geometry(self):
        preview = {"radius": 25.0, "height": 31.0, "cx": 50.0, "cy": 60.0}
        pts = mesh.make_cylinder_points(50, 60, 25, 31)
        # Push point 0 far outward in +X
        pts = mesh.smooth_deform(pts, 0, (40.0, 0.0, 0.0), smooth=False)
        mesh.save_screen_points("A3", preview, pts)
        saved = mesh.get_screen_mesh("A3")
        self.assertIsNotNone(saved)
        self.assertEqual(len(saved["points"]), 200)
        # Original outside point near the pushed vertex may now be inside.
        # Vertex 0 starts at (cx+r, cy) = (75, 60); after +40 → (115, 60).
        self.assertTrue(mesh.point_inside_mesh((50, 60), saved["points"]))

    def test_faces_for_pyvista_packing(self):
        faces = mesh.cylinder_faces()
        packed = mesh.faces_for_pyvista(faces)
        self.assertEqual(len(packed) % 4, 0)
        self.assertEqual(int(packed[0]), 3)


if __name__ == "__main__":
    unittest.main()
