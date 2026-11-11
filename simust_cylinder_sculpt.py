#!/usr/bin/env python3
"""Interactive finish-cylinder sculptor (PyVista + VTK).

Starts from the current Realtime cylinder size for one goal screen.
200 triangle-mesh vertices on the lateral surface. Left-click selects a
vertex; drag pushes/pulls it (optional smooth falloff on neighbors).
Connectivity is preserved — only vertex coordinates change.

Goal lines (p0/p1) are never edited here.

Run:
  python simust_cylinder_sculpt.py --screen A3
  python simust_cylinder_sculpt.py --screen A3 --fresh
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from typing import Optional

import numpy as np

import simust_cylinder_mesh as meshmod


def _try_preview(screen: str) -> dict:
    """Load live finish-cylinder size for this screen when realtime is available."""
    try:
        from simust_realtime import finish_cylinder_preview, reload_goal_line_calibration

        reload_goal_line_calibration()
        return finish_cylinder_preview(screen, action="PASS")
    except Exception:
        return {}


def _parse_args(argv=None):
    p = argparse.ArgumentParser(description="Sculpt a finish-cylinder triangle mesh")
    p.add_argument("--screen", default="A3", help="Goal screen id (A1…B6R)")
    p.add_argument("--radius", type=float, default=None)
    p.add_argument("--height", type=float, default=None)
    p.add_argument("--cx", type=float, default=None)
    p.add_argument("--cy", type=float, default=None)
    p.add_argument("--no-smooth", action="store_true", help="Move only the picked vertex")
    p.add_argument(
        "--influence",
        type=float,
        default=0.0,
        help="Smooth falloff radius in SIM px (0 = auto from neighbor spacing)",
    )
    p.add_argument(
        "--load-saved",
        action="store_true",
        default=True,
        help="Start from a previously saved sculpt for this screen if present (default)",
    )
    p.add_argument(
        "--fresh",
        action="store_true",
        help="Ignore any saved sculpt and start from the current analytic cylinder",
    )
    p.add_argument(
        "--pick-px",
        type=float,
        default=28.0,
        help="Max screen-pixel distance to select a vertex",
    )
    return p.parse_args(argv)


def _build_preview(args) -> dict:
    screen = str(args.screen or "A3").strip().upper()
    preview = _try_preview(screen) or {}
    if args.radius is not None:
        preview["radius"] = float(args.radius)
    if args.height is not None:
        preview["height"] = float(args.height)
    if args.cx is not None:
        preview["cx"] = float(args.cx)
    if args.cy is not None:
        preview["cy"] = float(args.cy)
    preview.setdefault("radius", 40.0)
    preview.setdefault("height", 31.0)
    preview.setdefault("cx", 640.0)
    preview.setdefault("cy", 180.0)
    preview["screen"] = screen
    return preview


def _make_drag_style(vtk_style_base, app: "CylinderSculptApp"):
    """VTK trackball style: override LMB so vertex drag is not stolen by the camera."""

        class VertexDragStyle(vtk_style_base):
            def OnLeftButtonDown(self):
                iren = self.GetInteractor()
                if iren is None:
                    return super().OnLeftButtonDown()
                # Vertex sculpt requires Ctrl (same as the Goal Area Calibration canvas).
                ctrl = bool(iren.GetControlKey())
                try:
                    ctrl = ctrl or bool(iren.GetCommandKey())
                except Exception:
                    pass
                if not ctrl:
                    return super().OnLeftButtonDown()
                x, y = iren.GetEventPosition()
                idx = app.pick_vertex_screen(x, y)
                if idx is None:
                    return super().OnLeftButtonDown()
                app.begin_drag(idx, x, y)
                # Skip super() — keep camera idle while a vertex is dragged.

            def OnMouseMove(self):
                if app.is_dragging:
                    iren = self.GetInteractor()
                    if iren is None:
                        return
                    x, y = iren.GetEventPosition()
                    app.drag_to(x, y)
                    return
                return super().OnMouseMove()

            def OnLeftButtonUp(self):
                if app.is_dragging:
                    app.end_drag()
                    return
                return super().OnLeftButtonUp()

    return VertexDragStyle()


class CylinderSculptApp:
    """PyVista plotter: triangle mesh + visible vertices, LMB pick/drag."""

    def __init__(
        self,
        screen: str,
        preview: dict,
        *,
        smooth: bool = True,
        influence: float = 0.0,
        load_saved: bool = True,
        pick_px: float = 28.0,
    ):
        try:
            import pyvista as pv
            from vtkmodules.vtkInteractionStyle import vtkInteractorStyleTrackballCamera
        except Exception as exc:  # pragma: no cover
            raise RuntimeError(
                "PyVista + VTK are required. Install with: pip install pyvista vtk"
            ) from exc

        self.pv = pv
        self._vtk_style_base = vtkInteractorStyleTrackballCamera
        self.screen = str(screen).strip().upper()
        self.preview = dict(preview or {})
        self.smooth = bool(smooth)
        self.influence = float(influence or 0.0)
        self.pick_px = float(pick_px)
        self.n_theta = meshmod.N_THETA
        self.n_height = meshmod.N_HEIGHT

        saved = meshmod.get_screen_mesh(self.screen) if load_saved else None
        if (
            saved
            and isinstance(saved.get("points"), list)
            and len(saved["points"]) == meshmod.N_CONTROL
        ):
            self.points = np.asarray(saved["points"], dtype=np.float64)
            self.preview["radius"] = float(saved.get("radius") or self.preview["radius"])
            self.preview["height"] = float(saved.get("height") or self.preview["height"])
            self.preview["cx"] = float(saved.get("cx") or self.preview["cx"])
            self.preview["cy"] = float(saved.get("cy") or self.preview["cy"])
            self.smooth = bool(saved.get("smooth", self.smooth))
        else:
            self.points = meshmod.make_cylinder_points(
                self.preview["cx"],
                self.preview["cy"],
                self.preview["radius"],
                self.preview["height"],
                self.n_theta,
                self.n_height,
            )

        self.faces = meshmod.cylinder_faces(self.n_theta, self.n_height)
        self._face_array = meshmod.faces_for_pyvista(self.faces)
        self.mesh = pv.PolyData(self.points.copy(), self._face_array.copy())

        self._dragging = False
        self._selected: Optional[int] = None
        self._last_display = None

        self.plotter = pv.Plotter(
            title=f"SIMUST cylinder sculpt — {self.screen} (TRIANGLES volume)"
        )
        # LearnWebGL-style volume: flat triangle faces + crisp edges + vertices.
        self.plotter.set_background("#1a1f2b")
        try:
            self.mesh.compute_normals(
                cell_normals=True, point_normals=False, inplace=True
            )
        except Exception:
            pass
        self.actor = self.plotter.add_mesh(
            self.mesh,
            color="#6ecf8e",
            opacity=0.95,
            style="surface",
            show_edges=True,
            edge_color="#111111",
            line_width=2,
            show_vertices=True,
            point_size=14,
            render_points_as_spheres=True,
            name="cylinder",
            pickable=True,
            lighting=True,
            smooth_shading=False,  # flat faces like LearnWebGL triangle meshes
            specular=0.15,
            ambient=0.35,
        )
        # Explicit wireframe overlay so every triangle edge reads clearly.
        self.plotter.add_mesh(
            self.mesh,
            style="wireframe",
            color="#f4f7f5",
            line_width=1,
            opacity=0.55,
            name="wire",
            pickable=False,
        )
        self._selected_actor = None
        self.plotter.add_axes(line_width=2)
        self.plotter.show_bounds(grid="back", location="outer", color="#8fa0b6")
        self._update_hud()

        self.plotter.add_key_event("s", self._toggle_smooth)
        self.plotter.add_key_event("S", self._toggle_smooth)
        self.plotter.add_key_event("r", self._reset_mesh)
        self.plotter.add_key_event("R", self._reset_mesh)
        self.plotter.add_key_event("Return", self._save)
        self.plotter.add_key_event("KP_Enter", self._save)

        cx = float(self.preview["cx"])
        cy = float(self.preview["cy"])
        h = float(self.preview["height"])
        r = float(self.preview["radius"])
        self.plotter.camera_position = [
            (cx + r * 3.5, cy - h * 0.5, r * 4.0),
            (cx, cy - h * 0.5, 0.0),
            (0, -1, 0),
        ]
        # Interactor exists before show() in current PyVista; install drag style now
        # and again on first render in case the style is replaced at show time.
        self._install_pending = True
        self._install_interactor()
        self.plotter.add_on_render_callback(self._once_install, render_event=False)

    @property
    def is_dragging(self) -> bool:
        return bool(self._dragging)

    def _update_hud(self, extra: str = ""):
        smooth = "ON" if self.smooth else "OFF"
        sel = f"v{self._selected}" if self._selected is not None else "none"
        text = (
            f"{self.screen}  |  triangle mesh  |  {meshmod.N_CONTROL} vertices  |  "
            f"r={self.preview['radius']:.1f} h={self.preview['height']:.1f}\n"
                f"Ctrl+LMB near a vertex = drag mesh  ·  smooth={smooth}  ·  selected={sel}\n"
            f"S smooth · R reset · Enter save mesh · Esc quit"
        )
        if extra:
            text = text + "\n" + extra
        try:
            self.plotter.remove_actor("hud", render=False)
        except Exception:
            pass
        self.plotter.add_text(text, font_size=10, color="white", name="hud")

    def pick_vertex_screen(self, x: float, y: float) -> Optional[int]:
        """Nearest triangle-mesh vertex in display pixels (reliable vs VTK PointPicker)."""
        ren = self.plotter.renderer
        best_i = None
        best_d = float(self.pick_px)
        for i, p in enumerate(self.points):
            ren.SetWorldPoint(float(p[0]), float(p[1]), float(p[2]), 1.0)
            ren.WorldToDisplay()
            dx, dy, _dz = ren.GetDisplayPoint()
            dist = math.hypot(float(dx) - float(x), float(dy) - float(y))
            if dist <= best_d:
                best_d = dist
                best_i = i
        return best_i

    def begin_drag(self, index: int, x: float, y: float) -> None:
        self._selected = int(index)
        self._dragging = True
        self._last_display = (float(x), float(y))
        self._highlight_selected()
        self._update_hud(f"Dragging vertex {self._selected}")
        self.plotter.render()

    def drag_to(self, x: float, y: float) -> None:
        if not self._dragging or self._selected is None or self._last_display is None:
            return
        x0, y0 = self._last_display
        anchor = self.points[self._selected]
        delta = self._display_to_world_delta(x0, y0, x, y, anchor)
        # Emphasize push/pull along the local radial direction in the XZ ellipse.
        cx = float(self.preview["cx"])
        radial = np.array([anchor[0] - cx, 0.0, float(anchor[2])], dtype=np.float64)
        norm = float(np.linalg.norm(radial))
        if norm > 1e-6:
            radial /= norm
            push = float(delta[0]) * 0.35 + float(delta[2]) * 0.35
            delta = delta + radial * push
        self.points = meshmod.smooth_deform(
            self.points,
            self._selected,
            delta,
            smooth=self.smooth,
            influence=self.influence,
        )
        self._last_display = (float(x), float(y))
        self._sync_mesh_geometry()
        self._highlight_selected()
        self.plotter.render()

    def end_drag(self) -> None:
        self._dragging = False
        self._last_display = None
        self._update_hud("Released — Enter saves mesh")
        self.plotter.render()

    def _display_to_world_delta(self, x0, y0, x1, y1, anchor):
        ren = self.plotter.renderer
        ren.SetWorldPoint(float(anchor[0]), float(anchor[1]), float(anchor[2]), 1.0)
        ren.WorldToDisplay()
        z = float(ren.GetDisplayPoint()[2])

        ren.SetDisplayPoint(float(x0), float(y0), z)
        ren.DisplayToWorld()
        w0 = np.asarray(ren.GetWorldPoint()[:3], dtype=np.float64)

        ren.SetDisplayPoint(float(x1), float(y1), z)
        ren.DisplayToWorld()
        w1 = np.asarray(ren.GetWorldPoint()[:3], dtype=np.float64)
        return w1 - w0

    def _sync_mesh_geometry(self) -> None:
        """Update triangle-mesh vertex coordinates in place (keep connectivity)."""
        self.mesh.points = np.ascontiguousarray(self.points, dtype=np.float64)
        try:
            self.mesh.compute_normals(
                cell_normals=True, point_normals=False, inplace=True
            )
        except Exception:
            pass
        try:
            self.mesh.Modified()
        except Exception:
            pass
        try:
            for name in ("cylinder", "wire"):
                prop = self.plotter.renderer.actors.get(name)
                if prop is None:
                    continue
                mapper = prop.GetMapper() if hasattr(prop, "GetMapper") else None
                if mapper is not None:
                    mapper.Update()
        except Exception:
            pass

    def _highlight_selected(self) -> None:
        try:
            self.plotter.remove_actor("selected", render=False)
        except Exception:
            pass
        self._selected_actor = None
        if self._selected is None or not (0 <= self._selected < len(self.points)):
            return
        pt = self.points[self._selected : self._selected + 1]
        self._selected_actor = self.plotter.add_points(
            pt,
            color="#ffcc00",
            point_size=28,
            render_points_as_spheres=True,
            name="selected",
            pickable=False,
        )

    def _toggle_smooth(self):
        self.smooth = not self.smooth
        self._update_hud()
        self.plotter.render()

    def _reset_mesh(self):
        self.points = meshmod.make_cylinder_points(
            self.preview["cx"],
            self.preview["cy"],
            self.preview["radius"],
            self.preview["height"],
            self.n_theta,
            self.n_height,
        )
        self._selected = None
        self._dragging = False
        self._last_display = None
        self._sync_mesh_geometry()
        self._highlight_selected()
        self._update_hud("Reset to current cylinder size")
        self.plotter.render()

    def _save(self):
        meshmod.save_screen_points(
            self.screen,
            self.preview,
            self.points,
            smooth=self.smooth,
        )
        out = {
            "screen": self.screen,
            "preview": self.preview,
            "n_points": int(len(self.points)),
            "n_faces": int(len(self.faces)),
            "path": os.path.abspath(meshmod.MESH_FILE),
        }
        print(json.dumps({"status": "saved", **out}))
        self._update_hud(f"Saved mesh → {os.path.basename(meshmod.MESH_FILE)}")
        self.plotter.render()

    def _install_interactor(self) -> None:
        iren = getattr(self.plotter, "iren", None)
        if iren is None:
            return
        interactor = getattr(iren, "interactor", None) or iren
        style = _make_drag_style(self._vtk_style_base, self)
        interactor.SetInteractorStyle(style)
        self._style = style
        # Keep a Python reference so the style is not GC'd while the window is open.
        try:
            iren.style = style
        except Exception:
            pass

    def run(self):
        self._install_interactor()
        self.plotter.show()

    def _once_install(self, *_args, **_kwargs):
        if getattr(self, "_install_pending", False):
            self._install_interactor()
            self._install_pending = False


def main(argv=None) -> int:
    args = _parse_args(argv)
    preview = _build_preview(args)
    screen = str(args.screen or preview.get("screen") or "A3").strip().upper()
    app = CylinderSculptApp(
        screen,
        preview,
        smooth=not args.no_smooth,
        influence=float(args.influence or 0.0),
        load_saved=not bool(args.fresh),
        pick_px=float(args.pick_px or 28.0),
    )
    print(
        f"Sculpt {screen}: triangle mesh, {meshmod.N_CONTROL} vertices, "
        f"{len(app.faces)} triangles, "
        f"r={preview['radius']:.2f}, h={preview['height']:.2f}, "
        f"smooth={'on' if app.smooth else 'off'}"
    )
    print("Left-click near a vertex, hold and drag to pull. Enter saves the mesh.")
    app.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
