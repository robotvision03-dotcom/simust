"""Foundation cognitive challenge layouts (numbers, color rules, memory, etc.).

Used by smart_simust_player for Foundation extra playlists. Math sum/sub/multiply/divide
live in the player; this module covers the other cognitive approaches.
"""

from __future__ import annotations

import hashlib
import logging
import os
import random
import re
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Directory names under L00-Foundation-Challenge (skip sum/sub/multiply/divide — already exist)
FOUNDATION_COGNITIVE_MODES = (
    "sequence",       # pattern / missing number
    "compound",       # multi-step arithmetic
    "color_rule",     # color + number rule switching
    "go_nogo",        # PASS / STOP inhibition
    "stroop",         # word vs background color conflict
    "spatial",        # relative position / shapes
    "memory",         # remember where a target appeared
    "move_memory",    # symbols rearrange; find original
    "tracking",       # track then locate
    "tactical",       # teammate / defender / space
    "flex",           # sudden rule change (green↔red safe)
    "dual_rule",      # AND / OR multi-attribute
    "peripheral",     # peripheral flash targets
    "emotion",        # face / emotion match
    "symbols",        # symbol → action mapping
)

COG_CACHE_DIR = "C:/Users/siama/Documents/simust_player/cog_tile_cache"
COG_CORRECT_PER_FIELD = 1
COG_ENCODE_MS = 1200
COG_BLANK_MS = 400

COG_COLORS = {
    "red": (200, 40, 40),
    "blue": (40, 100, 220),
    "green": (40, 170, 80),
    "yellow": (220, 190, 40),
    "orange": (230, 120, 30),
    "purple": (140, 60, 180),
    "white": (230, 230, 235),
    "black": (10, 12, 18),
    "gray": (70, 75, 85),
    "cyan": (40, 190, 200),
}

FIELD_SCREENS_A = [2, 3, 4, 12, 13, 14]  # screen 1 does not exist
FIELD_SCREENS_B = [5, 6, 7, 9, 10, 11]   # screen 8 does not exist

SHAPE_CHARS = {
    "triangle": "▲",
    "circle": "●",
    "square": "■",
    "star": "★",
    "diamond": "◆",
    "arrow_r": "→",
    "arrow_l": "←",
    "arrow_u": "↑",
    "arrow_d": "↓",
    "arrow_ur": "↗",
}


def field_screens(fid: str) -> List[int]:
    return list(FIELD_SCREENS_A if str(fid).upper() == "A" else FIELD_SCREENS_B)


def _safe_name(*parts) -> str:
    raw = "_".join(str(p) for p in parts)
    digest = hashlib.md5(raw.encode("utf-8")).hexdigest()[:10]
    safe = re.sub(r"[^\w.\-]+", "_", raw)[:80]
    return f"{safe}_{digest}.png"


def render_cog_tile(
    text: str = "",
    bg: str = "black",
    fg: str = "white",
    shape: str = "",
    subtitle: str = "",
) -> Optional[str]:
    """Render a coach-band tile PNG (cached)."""
    try:
        os.makedirs(COG_CACHE_DIR, exist_ok=True)
    except Exception:
        return None
    key = _safe_name(text, bg, fg, shape, subtitle)
    path = os.path.join(COG_CACHE_DIR, key)
    if os.path.isfile(path):
        return path
    try:
        from PyQt5.QtGui import QImage, QPainter, QColor, QFont, QPen
    except Exception as exc:
        logger.warning("Cannot render cognitive tile: %s", exc)
        return None

    w, h = 512, 512
    rgb = COG_COLORS.get(str(bg).lower(), COG_COLORS["black"])
    frgb = COG_COLORS.get(str(fg).lower(), COG_COLORS["white"])
    img = QImage(w, h, QImage.Format_ARGB32)
    img.fill(QColor(*rgb))
    painter = QPainter(img)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setRenderHint(QPainter.TextAntialiasing)
    painter.setPen(QPen(QColor(255, 255, 255, 40), 3))
    painter.drawRoundedRect(10, 10, w - 20, h - 20, 22, 22)

    main = str(shape or text or "").strip()
    if shape and text:
        main = f"{SHAPE_CHARS.get(shape, shape)}\n{text}"
    elif shape:
        main = SHAPE_CHARS.get(shape, shape)

    painter.setPen(QColor(*frgb))
    lines = main.split("\n") if main else [""]
    font_size = 96 if len(lines) == 1 and len(lines[0]) <= 3 else 56
    font = QFont("Segoe UI", font_size, QFont.Bold)
    painter.setFont(font)
    metrics = painter.fontMetrics()
    total_h = sum(metrics.height() for _ in lines)
    y = (h - total_h) // 2 + metrics.ascent()
    for line in lines:
        while metrics.width(line) > w - 36 and font.pointSize() > 22:
            font.setPointSize(font.pointSize() - 4)
            painter.setFont(font)
            metrics = painter.fontMetrics()
        tw = metrics.width(line)
        painter.drawText((w - tw) // 2, y, line)
        y += metrics.height()

    if subtitle:
        font2 = QFont("Segoe UI", 22, QFont.Bold)
        painter.setFont(font2)
        painter.setPen(QColor(255, 255, 255, 200))
        m2 = painter.fontMetrics()
        painter.drawText((w - m2.width(subtitle)) // 2, h - 36, subtitle)

    painter.end()
    if not img.save(path, "PNG"):
        return None
    return path


def _layout_sequence(fid: str) -> Tuple[List[int], dict, Optional[dict], dict]:
    screens = field_screens(fid)
    patterns = [
        ([1, 2, 4], 8),
        ([3, 6, 9], 12),
        ([2, 5, 8], 11),
        ([1, 2, 3], 4),
        ([2, 4, 8], 16),
        ([5, 4, 3], 2),
        ([1, 3, 5], 7),
    ]
    seq, answer = random.choice(patterns)
    distractors = list({answer + d for d in (-3, -2, -1, 1, 2, 3, 4) if answer + d > 0})
    random.shuffle(distractors)
    values = [answer] + distractors[: max(0, len(screens) - 1)]
    while len(values) < len(screens):
        values.append(random.randint(1, 20))
    random.shuffle(values)
    if answer not in values:
        values[0] = answer
    correct_sid = None
    images = {}
    prompt = ",".join(str(x) for x in seq) + ",?"
    for i, sid in enumerate(screens):
        val = values[i % len(values)]
        path = render_cog_tile(text=str(val), bg="black", fg="yellow", subtitle=prompt if i == 0 else "")
        if path:
            images[int(sid)] = path
        if val == answer and correct_sid is None:
            correct_sid = int(sid)
    if correct_sid is None:
        correct_sid = int(screens[0])
        images[correct_sid] = render_cog_tile(text=str(answer), bg="black", fg="yellow")
    return [correct_sid], images, None, {"rule": f"complete {prompt} -> {answer}"}


def _layout_compound(fid: str) -> Tuple[List[int], dict, Optional[dict], dict]:
    screens = field_screens(fid)
    exprs = [
        (5, 2, 4, 5 + 2 - 4, "5+2-4"),
        (8, 3, 2, 8 - 3 - 2, "8-3-2"),
        (2, 3, 1, 2 + 3 - 1, "2+3-1"),
        (4, 2, 2, 4 * 2 // 2, "4x2/2"),
        (9, 3, 1, 9 // 3 + 1, "9/3+1"),
        (6, 2, 3, 6 + 2 - 3, "6+2-3"),
    ]
    _a, _b, _c, ans, label = random.choice(exprs)
    vals = [ans]
    while len(vals) < len(screens):
        noise = ans + random.choice([-4, -3, -2, -1, 1, 2, 3, 5])
        if noise > 0 and noise not in vals:
            vals.append(noise)
    random.shuffle(vals)
    if ans not in vals:
        vals[0] = ans
    correct_sid = None
    images = {}
    for i, sid in enumerate(screens):
        v = vals[i % len(vals)]
        path = render_cog_tile(text=str(v), bg="black", fg="cyan", subtitle=label if i == 0 else "")
        if path:
            images[int(sid)] = path
        if v == ans and correct_sid is None:
            correct_sid = int(sid)
    return [correct_sid or int(screens[0])], images, None, {"rule": label}


def _layout_color_rule(fid: str) -> Tuple[List[int], dict, Optional[dict], dict]:
    screens = field_screens(fid)
    rules = [
        ("red", "even", lambda c, n: c == "red" and n % 2 == 0),
        ("red", "odd", lambda c, n: c == "red" and n % 2 == 1),
        ("blue", "even", lambda c, n: c == "blue" and n % 2 == 0),
        ("green", "gt5", lambda c, n: c == "green" and n > 5),
        ("yellow", "lt4", lambda c, n: c == "yellow" and n < 4),
        ("blue", "odd", lambda c, n: c == "blue" and n % 2 == 1),
    ]
    color_need, kind, pred = random.choice(rules)
    palette = ["red", "blue", "green", "yellow"]
    images = {}
    correct = []
    if kind == "gt5":
        match_n = random.randint(6, 9)
    elif kind == "lt4":
        match_n = random.randint(1, 3)
    elif kind == "odd":
        match_n = random.choice([1, 3, 5, 7, 9])
    else:
        match_n = random.choice([2, 4, 6, 8])
    tiles = [(color_need, match_n, True)]
    while len(tiles) < len(screens):
        c = random.choice(palette)
        n = random.randint(1, 9)
        ok = bool(pred(c, n))
        if ok and random.random() < 0.7:
            n = n + 1 if n < 9 else n - 1
            ok = bool(pred(c, n))
        tiles.append((c, n, ok))
    random.shuffle(tiles)
    for sid, (c, n, ok) in zip(screens, tiles):
        path = render_cog_tile(text=str(n), bg=c, fg="white")
        if path:
            images[int(sid)] = path
        if ok:
            correct.append(int(sid))
    if not correct:
        correct = [int(screens[0])]
        images[correct[0]] = render_cog_tile(text=str(match_n), bg=color_need, fg="white")
    return correct[:COG_CORRECT_PER_FIELD], images, None, {"rule": f"{color_need}+{kind}"}


def _layout_go_nogo(fid: str) -> Tuple[List[int], dict, Optional[dict], dict]:
    screens = field_screens(fid)
    go = random.random() < 0.65
    images = {}
    if go:
        target = random.choice(screens)
        for sid in screens:
            if int(sid) == int(target):
                images[int(sid)] = render_cog_tile(text="PASS", bg="green", fg="white")
            else:
                images[int(sid)] = render_cog_tile(
                    text=random.choice(["STOP", "WAIT", "NO"]),
                    bg=random.choice(["red", "gray", "orange"]),
                    fg="white",
                )
        return [int(target)], images, None, {"rule": "GO", "go": True}
    for sid in screens:
        images[int(sid)] = render_cog_tile(
            text=random.choice(["STOP", "DONT", "NO"]),
            bg="red",
            fg="white",
        )
    return [], images, None, {"rule": "NOGO", "go": False}


def _layout_stroop(fid: str) -> Tuple[List[int], dict, Optional[dict], dict]:
    screens = field_screens(fid)
    colors = ["red", "blue", "green", "yellow"]
    target_bg = random.choice(colors)
    images = {}
    correct = []
    for sid in screens:
        bg = random.choice(colors)
        word = random.choice([c for c in colors if c != bg] or colors)
        images[int(sid)] = render_cog_tile(text=word.upper(), bg=bg, fg="white")
        if bg == target_bg:
            correct.append(int(sid))
    if not correct:
        sid = int(screens[0])
        wrong_word = random.choice([c for c in colors if c != target_bg] or ["blue"])
        images[sid] = render_cog_tile(text=wrong_word.upper(), bg=target_bg, fg="white")
        correct = [sid]
    return correct[:1], images, None, {"rule": f"bg={target_bg} (ignore word)"}


def _layout_spatial(fid: str) -> Tuple[List[int], dict, Optional[dict], dict]:
    screens = field_screens(fid)
    shapes = ["triangle", "circle", "square", "star"]
    placed = list(shapes)
    while len(placed) < len(screens):
        placed.append(random.choice(shapes))
    random.shuffle(placed)
    landmark_i = random.randrange(min(4, len(screens)))
    offset = random.choice([1, 2, -1])
    target_i = (landmark_i + offset) % len(screens)
    images = {}
    for i, sid in enumerate(screens):
        path = render_cog_tile(shape=placed[i], bg="black", fg="yellow")
        if path:
            images[int(sid)] = path
    return [int(screens[target_i])], images, None, {"rule": f"{offset:+d} from {placed[landmark_i]}"}


def _layout_memory(fid: str) -> Tuple[List[int], dict, Optional[dict], dict]:
    screens = field_screens(fid)
    colors = ["red", "blue", "green", "yellow", "orange", "purple", "cyan"]
    random.shuffle(colors)
    encode = {}
    target_sid = random.choice(screens)
    for i, sid in enumerate(screens):
        c = colors[i % len(colors)]
        if int(sid) == int(target_sid):
            c = "green"
        encode[int(sid)] = render_cog_tile(text="", bg=c, fg="white")
    probe = {int(sid): render_cog_tile(text="?", bg="gray", fg="white") for sid in screens}
    return [int(target_sid)], probe, encode, {"rule": "where was green?"}


def _layout_move_memory(fid: str) -> Tuple[List[int], dict, Optional[dict], dict]:
    screens = field_screens(fid)
    symbols = ["star", "circle", "triangle", "square", "diamond", "arrow_r", "arrow_l"]
    random.shuffle(symbols)
    encode = {}
    orig = {}
    for i, sid in enumerate(screens):
        sh = symbols[i % len(symbols)]
        encode[int(sid)] = render_cog_tile(shape=sh, bg="black", fg="yellow")
        orig[sh] = int(sid)
    target_shape = "star" if "star" in orig else symbols[0]
    target_sid = orig[target_shape]
    probe_shapes = symbols[:]
    random.shuffle(probe_shapes)
    probe = {}
    for i, sid in enumerate(screens):
        probe[int(sid)] = render_cog_tile(
            shape=probe_shapes[i % len(probe_shapes)], bg="black", fg="cyan",
            subtitle="orig?" if i == 0 else "",
        )
    return [int(target_sid)], probe, encode, {"rule": f"where was {target_shape} originally?"}


def _layout_tracking(fid: str) -> Tuple[List[int], dict, Optional[dict], dict]:
    screens = field_screens(fid)
    encode = {}
    target_sid = random.choice(screens)
    for sid in screens:
        if int(sid) == int(target_sid):
            encode[int(sid)] = render_cog_tile(text="P", bg="red", fg="white", subtitle="TRACK")
        else:
            encode[int(sid)] = render_cog_tile(
                text="P", bg=random.choice(["green", "blue", "cyan"]), fg="white"
            )
    probe = {}
    for sid in screens:
        if int(sid) == int(target_sid):
            probe[int(sid)] = render_cog_tile(text="P", bg="red", fg="white")
        else:
            probe[int(sid)] = render_cog_tile(
                text="P", bg=random.choice(["green", "blue", "gray"]), fg="white"
            )
    return [int(target_sid)], probe, encode, {"rule": "track RED player"}


def _layout_tactical(fid: str) -> Tuple[List[int], dict, Optional[dict], dict]:
    screens = field_screens(fid)
    roles = ["TEAM", "DEF", "SPACE", "OPP", "TEAM", "DEF", "SPACE"]
    random.shuffle(roles)
    images = {}
    team_ids = []
    space_ids = []
    for i, sid in enumerate(screens):
        role = roles[i % len(roles)]
        if role == "TEAM":
            images[int(sid)] = render_cog_tile(text="TEAM", bg="green", fg="white")
            team_ids.append(int(sid))
        elif role == "SPACE":
            images[int(sid)] = render_cog_tile(text="SPACE", bg="cyan", fg="black")
            space_ids.append(int(sid))
        elif role == "DEF":
            images[int(sid)] = render_cog_tile(text="DEF", bg="red", fg="white")
        else:
            images[int(sid)] = render_cog_tile(text="OPP", bg="orange", fg="white")
    pick = (team_ids or space_ids or [int(screens[0])])[:1]
    if pick and pick[0] not in images:
        images[pick[0]] = render_cog_tile(text="TEAM", bg="green", fg="white")
    return pick, images, None, {"rule": "safest pass (TEAM/SPACE)"}


def _layout_flex(fid: str, action_in_set: int = 1) -> Tuple[List[int], dict, Optional[dict], dict]:
    screens = field_screens(fid)
    green_safe = (int(action_in_set) % 2 == 1)
    safe_color = "green" if green_safe else "red"
    images = {}
    correct = []
    for sid in screens:
        c = random.choice(["green", "red", "blue", "yellow"])
        images[int(sid)] = render_cog_tile(text="GO", bg=c, fg="white")
        if c == safe_color:
            correct.append(int(sid))
    if not correct:
        sid = int(screens[0])
        images[sid] = render_cog_tile(text="GO", bg=safe_color, fg="white")
        correct = [sid]
    return correct[:1], images, None, {"rule": f"{safe_color} safe"}


def _layout_dual_rule(fid: str) -> Tuple[List[int], dict, Optional[dict], dict]:
    screens = field_screens(fid)
    images = {}
    correct = []
    forced = random.choice(screens)
    for sid in screens:
        if int(sid) == int(forced):
            n, c = random.choice([2, 4, 6, 8]), "blue"
        else:
            n = random.randint(1, 9)
            c = random.choice(["red", "blue", "green", "yellow"])
        images[int(sid)] = render_cog_tile(text=str(n), bg=c, fg="white")
        if c == "blue" and n % 2 == 0:
            correct.append(int(sid))
    if not correct:
        correct = [int(forced)]
    return correct[:1], images, None, {"rule": "blue AND even"}


def _layout_peripheral(fid: str) -> Tuple[List[int], dict, Optional[dict], dict]:
    screens = field_screens(fid)
    peri = list(dict.fromkeys([screens[0], screens[-1], screens[1], screens[-2]]))
    target = random.choice(peri)
    images = {}
    for sid in screens:
        if int(sid) == int(target):
            images[int(sid)] = render_cog_tile(text="!", bg="yellow", fg="black", subtitle="PERIPH")
        elif int(sid) in peri:
            images[int(sid)] = render_cog_tile(text="", bg="gray", fg="white")
        else:
            images[int(sid)] = render_cog_tile(text="+", bg="black", fg="gray", subtitle="LOOK")
    return [int(target)], images, None, {"rule": "peripheral flash"}


def _layout_emotion(fid: str) -> Tuple[List[int], dict, Optional[dict], dict]:
    screens = field_screens(fid)
    faces = [
        ("HAPPY", ":)", "yellow"),
        ("ANGRY", ">:(", "red"),
        ("SAD", ":(", "blue"),
        ("NEUTRAL", ":|", "gray"),
    ]
    random.shuffle(faces)
    images = {}
    correct = []
    for i, sid in enumerate(screens):
        label, glyph, bg = faces[i % len(faces)]
        images[int(sid)] = render_cog_tile(text=glyph, bg=bg, fg="white", subtitle=label)
        if label == "HAPPY":
            correct.append(int(sid))
    if not correct:
        sid = int(screens[0])
        images[sid] = render_cog_tile(text=":)", bg="yellow", fg="white", subtitle="HAPPY")
        correct = [sid]
    return correct[:1], images, None, {"rule": "pass to HAPPY"}


def _layout_symbols(fid: str, action_in_set: int = 1) -> Tuple[List[int], dict, Optional[dict], dict]:
    screens = field_screens(fid)
    pass_shape = "triangle" if int(action_in_set) % 2 == 1 else "star"
    decoys = ["circle", "square", "diamond", "arrow_r"]
    images = {}
    correct = []
    shapes = [pass_shape] + decoys
    while len(shapes) < len(screens):
        shapes.append(random.choice(decoys))
    random.shuffle(shapes)
    for sid, sh in zip(screens, shapes):
        images[int(sid)] = render_cog_tile(shape=sh, bg="black", fg="yellow")
        if sh == pass_shape:
            correct.append(int(sid))
    if not correct:
        sid = int(screens[0])
        images[sid] = render_cog_tile(shape=pass_shape, bg="black", fg="yellow")
        correct = [sid]
    return correct[:1], images, None, {"rule": f"{pass_shape}=PASS"}


_LAYOUTS = {
    "sequence": lambda fid, a: _layout_sequence(fid),
    "compound": lambda fid, a: _layout_compound(fid),
    "color_rule": lambda fid, a: _layout_color_rule(fid),
    "go_nogo": lambda fid, a: _layout_go_nogo(fid),
    "stroop": lambda fid, a: _layout_stroop(fid),
    "spatial": lambda fid, a: _layout_spatial(fid),
    "memory": lambda fid, a: _layout_memory(fid),
    "move_memory": lambda fid, a: _layout_move_memory(fid),
    "tracking": lambda fid, a: _layout_tracking(fid),
    "tactical": lambda fid, a: _layout_tactical(fid),
    "flex": lambda fid, a: _layout_flex(fid, a),
    "dual_rule": lambda fid, a: _layout_dual_rule(fid),
    "peripheral": lambda fid, a: _layout_peripheral(fid),
    "emotion": lambda fid, a: _layout_emotion(fid),
    "symbols": lambda fid, a: _layout_symbols(fid, a),
}

COG_ENCODE_MODES = frozenset({"memory", "move_memory", "tracking"})


def build_cognitive_layout(
    mode: str, fid: str, action_in_set: int = 1
) -> Tuple[List[int], dict, Optional[dict], dict]:
    mode = str(mode or "").lower()
    fn = _LAYOUTS.get(mode)
    if not fn:
        return [], {}, None, {}
    return fn(fid, action_in_set)


def build_cognitive_playlist(
    mode: str,
    active_fields,
    gaps: dict = None,
    test_count: int = 5,
    actions_per_test: int = 10,
    timing_decay: float = 0.90,
) -> List[dict]:
    """5x10 cognitive challenge playlist entries for the smart player."""
    mode = str(mode or "").lower()
    if mode not in FOUNDATION_COGNITIVE_MODES:
        return []
    active = [f for f in ("A", "B") if f in set(active_fields or [])]
    if not active:
        return []
    gaps = gaps or {}
    needs_encode = mode in COG_ENCODE_MODES
    playlist = []
    for test_num in range(1, int(test_count) + 1):
        scale = float(timing_decay) ** (test_num - 1)
        for action_in_set in range(1, int(actions_per_test) + 1):
            field_screens_map: Dict[str, List[int]] = {}
            screen_images: Dict[int, str] = {}
            encode_images: Dict[int, str] = {}
            rules = []
            for fid in active:
                correct, probe, encode, meta = build_cognitive_layout(mode, fid, action_in_set)
                if not probe:
                    continue
                field_screens_map[fid] = list(correct or [])
                screen_images.update({int(k): v for k, v in probe.items() if v})
                if encode:
                    encode_images.update({int(k): v for k, v in encode.items() if v})
                if meta.get("rule"):
                    rules.append(f"{fid}:{meta['rule']}")
            if not screen_images:
                continue
            lit = "_".join(
                str(s) for sids in field_screens_map.values() for s in sids
            ) or "none"
            entry = {
                "kind": "labeled_action",
                "index": len(playlist) + 1,
                "test_num": test_num,
                "action_in_set": action_in_set,
                "actions_in_set": actions_per_test,
                "is_last_in_set": action_in_set == actions_per_test,
                "timing_scale": scale,
                "action_num": action_in_set,
                "action": "PASS",
                "cognitive": mode,
                "no_fillers": True,
                "field_screens": field_screens_map,
                "screen_images": screen_images,
                "parts": [{
                    "screens": list(next(iter(field_screens_map.values()), [])),
                    "path": next(iter(screen_images.values())),
                    "field": next(iter(field_screens_map), "A"),
                }],
                "gap_path": (
                    gaps.get(action_in_set)
                    if gaps.get(action_in_set) and os.path.isfile(gaps[action_in_set])
                    else None
                ),
                "label": (
                    f"{mode} T{test_num}/{test_count} "
                    f"a{action_in_set}/{actions_per_test} "
                    f"ok_{lit} x{scale:.2f}"
                ),
                "path": f"image://{mode}/test{test_num}/{action_in_set}",
                "foundation_sf": mode,
                "rule": " | ".join(rules),
            }
            if needs_encode and encode_images:
                entry["encode_images"] = encode_images
                entry["cognitive_encode"] = True
            if mode == "go_nogo" and not any(field_screens_map.values()):
                entry["nogo"] = True
            playlist.append(entry)
    return playlist
