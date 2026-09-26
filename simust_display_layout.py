"""Shared ring layout for waiting overlays and coach results videos.

Waiting and results use the same center and size so the 14-slice strip
does not jump up or down when processing finishes.
Rings are 30% smaller than the previous 90px / 22px results charts.
"""

import ast
import os

CHART_CENTER_Y = 140
RING_RADIUS = 63
RING_THICKNESS = 15

# Screen 2 is 3840×512. Fourteen frames fill that width.
# Each field is named 1–6. A is the left half, B the right half.
# Empty places stay between 3 and 4 on both fields.
# A1 was cabinet 12, A2=13, A3=14, A4=2, A5=3, A6=4.
# B1 was cabinet 5, B2=6, B3=7, B4=9, B5=10, B6=11.
CABINET_WIDTH = 254
CABINET_HEIGHT = 512
DISPLAY_SLICE_ORDER = [
    "A1", "A2", "A3", None, "A4", "A5", "A6",
    "B1", "B2", "B3", None, "B4", "B5", "B6",
]
EMPTY_DISPLAY_SLICES = set()
SLICE_COUNT = len(DISPLAY_SLICE_ORDER)
COACH_BAND_WIDTH = 3840
COACH_BAND_HEIGHT = CABINET_HEIGHT

# Width of the rectangle drawn in screen_offset_gui.py. Display content uses this
# so pictures stay inside the cabinet the calibrator already checked.
CONTENT_WIDTH_RATIO = 0.92

# Extra nudge after the 254px grid. Negative x moves left. Negative y moves up.
# BEGIN GENERATED OFFSETS
SCREEN_CONTENT_OFFSET = {
    "A1": -10,
    "A2": -27,
    "A3": -40,
    "A5": -34,
    "A6": -52,
    "B1": -72,
    "B2": -90,
    "B3": -108,
    "B4": -84,
    "B5": -100,
    "B6": -117,
}
SCREEN_CONTENT_OFFSET_Y = {
}
# END GENERATED OFFSETS


def slice_x_span(index, width=None, count=None):
    """Pixel x0, x1 of one frame. Fourteen frames split the projection exactly in half."""
    width = COACH_BAND_WIDTH if width is None else int(width)
    count = SLICE_COUNT if count is None else max(1, int(count))
    index = int(index)
    x0 = (index * width) // count
    x1 = ((index + 1) * width) // count
    return x0, max(x0 + 1, x1)


def slice_span_for_ids(slice_ids, order=None, width=None):
    """Inclusive pixel span covering the given screen ids, including an empty frame between them."""
    order = list(DISPLAY_SLICE_ORDER if order is None else order)
    width = COACH_BAND_WIDTH if width is None else int(width)
    count = max(1, len(order))
    indexes = []
    for sid in slice_ids:
        try:
            indexes.append(order.index(int(sid)))
        except (TypeError, ValueError):
            continue
    if not indexes:
        return slice_x_span(0, width, count)
    x0, _x1 = slice_x_span(min(indexes), width, count)
    _x0, x1 = slice_x_span(max(indexes), width, count)
    return x0, x1


def content_width(tile_w) -> int:
    """Pixel width of the calibrator rectangle for one frame."""
    return max(8, int(int(tile_w) * CONTENT_WIDTH_RATIO))


def content_x_box(index, screen_id, width=None, count=None):
    """Left, right, and width of that rectangle after the saved offset."""
    width = COACH_BAND_WIDTH if width is None else int(width)
    count = SLICE_COUNT if count is None else max(1, int(count))
    x0, x1 = slice_x_span(index, width, count)
    rect_w = content_width(x1 - x0)
    center = (x0 + x1) // 2 + screen_content_offset(screen_id)
    left = center - rect_w // 2
    return left, left + rect_w, rect_w


_OFFSETS_MTIME = None


def _reload_offsets_if_changed():
    """Pick up a new screen_offset_gui.py save without restarting the player."""
    global SCREEN_CONTENT_OFFSET, SCREEN_CONTENT_OFFSET_Y, _OFFSETS_MTIME
    try:
        mtime = os.path.getmtime(__file__)
    except OSError:
        return
    if _OFFSETS_MTIME == mtime:
        return
    try:
        with open(__file__, encoding="utf-8") as handle:
            text = handle.read()
        start = text.find("# BEGIN GENERATED OFFSETS")
        end = text.find("# END GENERATED OFFSETS")
        block = text[start:end]
        dx_text = block.split("SCREEN_CONTENT_OFFSET = ", 1)[1].split("SCREEN_CONTENT_OFFSET_Y", 1)[0].strip()
        dy_text = block.split("SCREEN_CONTENT_OFFSET_Y = ", 1)[1].strip()
        dx = ast.literal_eval(dx_text)
        dy = ast.literal_eval(dy_text)
        SCREEN_CONTENT_OFFSET = {int(k): int(v) for k, v in dx.items()}
        SCREEN_CONTENT_OFFSET_Y = {int(k): int(v) for k, v in dy.items()}
    except Exception:
        pass
    _OFFSETS_MTIME = mtime


def screen_content_offset(screen_id) -> int:
    """Pixels to shift content left or right. Unknown screens stay centered."""
    _reload_offsets_if_changed()
    try:
        return int(SCREEN_CONTENT_OFFSET.get(str(screen_id), 0))
    except (TypeError, ValueError):
        return 0


def screen_content_offset_y(screen_id) -> int:
    """Pixels to shift content up or down. Unknown screens stay centered."""
    _reload_offsets_if_changed()
    try:
        return int(SCREEN_CONTENT_OFFSET_Y.get(str(screen_id), 0))
    except (TypeError, ValueError):
        return 0


def screen_number(screen_id) -> str:
    """The 1–6 name shown on that field. A3 and B3 both display as 3."""
    text = str(screen_id or "")
    if len(text) >= 2 and text[0] in ("A", "B") and text[1:].isdigit():
        return text[1:]
    return text
