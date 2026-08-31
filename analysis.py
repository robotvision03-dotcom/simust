import json
import math
import pandas as pd
from datetime import datetime, timedelta
from typing import List, Tuple, Optional, Dict
from collections import Counter

# ------------------- SCALED FOR 1280x360 -------------------
SCALE = 1.0

# All pixel thresholds adjusted for 1280x360
CORRECT_THRESHOLD = 40
LATE_SEARCH_DURATION = 2.5          # Used only for PASS, TARGET, PRESS
MIN_MOVEMENT_THRESHOLD = 33
MOVEMENT_RADIUS = 120
LEAVE_THRESHOLD = 200
SEARCH_FRAMES = 15
MIN_NEAR_FRAMES = 3
PRE_FRAMES = 6
ENTRY_MARGIN = 1.0

FINISH_DIST = 100
PIXEL_TO_METER_SCALE = 0.0259

# Screen-specific thresholds (PASS, TARGET, GOAL)
SCREEN_CORRECT_THRESHOLDS = {
    '2': 22,  '3': 30,  '4': 10,   '5': 10,   '6': 13,  '7': 22,
    '9': 22,  '10': 13, '11': 10,  '12': 10,  '13': 30, '14': 40,
    '1': 13,  '8': 13,
    '9L': 40,   '6L': 40,
}

PRESS_SCREEN_THRESHOLDS = {
    '2': 120,   '7': 120,   '9': 120,   '14': 120,
}

GOAL_SCREEN_THRESHOLDS = {
    '8': 73,   '1': 33,
}

# ---------- NEW: reject GOAL if proj_t is too close to the ends (corners) ----------
PROJ_T_LOWER_THRESHOLD = 0.008   # reject if proj_t < 0.008
PROJ_T_UPPER_THRESHOLD = 0.96    # reject if proj_t > 0.96

# ============================================================================
# HELPERS
# ============================================================================

def get_threshold_for_screen(screen: str, action_type: str) -> float:
    if action_type == 'PRESS':
        if screen in PRESS_SCREEN_THRESHOLDS:
            return PRESS_SCREEN_THRESHOLDS[screen]
        base = screen.rstrip('LR')
        return PRESS_SCREEN_THRESHOLDS.get(base, 100)
    if action_type == 'GOAL':
        if screen in GOAL_SCREEN_THRESHOLDS:
            return GOAL_SCREEN_THRESHOLDS[screen]
        if screen in SCREEN_CORRECT_THRESHOLDS:
            return SCREEN_CORRECT_THRESHOLDS[screen]
        base = screen.rstrip('LR')
        return SCREEN_CORRECT_THRESHOLDS.get(base, CORRECT_THRESHOLD)
    # PASS, TARGET
    if screen in SCREEN_CORRECT_THRESHOLDS:
        return SCREEN_CORRECT_THRESHOLDS[screen]
    base = screen.rstrip('LR')
    return SCREEN_CORRECT_THRESHOLDS.get(base, CORRECT_THRESHOLD)

def load_recognition_file(file_path: str) -> List[dict]:
    with open(file_path, 'r') as f:
        return json.load(f)

def parse_time(time_str: str) -> datetime:
    return datetime.strptime(time_str, "%H:%M:%S.%f")

def get_positions_from_data(data: List[dict], key: str, scale: float = SCALE) -> List[Tuple[float, int, int]]:
    positions = []
    for entry in data:
        t = entry.get('t', 0.0)
        if key in entry and entry[key]:
            for pos in entry[key]:
                if isinstance(pos, list) and len(pos) >= 2:
                    try:
                        x = int(float(pos[0]) * scale)
                        y = int(float(pos[1]) * scale)
                        positions.append((t, x, y))
                    except (ValueError, TypeError):
                        continue
    return positions

def get_unique_trajectory(positions: List[Tuple[float, int, int]]) -> List[Tuple[float, int, int]]:
    seen = set()
    unique = []
    for t, x, y in positions:
        key = (x, y)
        if key not in seen:
            seen.add(key)
            unique.append((t, x, y))
    return unique

def compute_projection(point: Tuple[float, float], p0: Tuple[float, float], p1: Tuple[float, float]):
    x0, y0 = point
    x1, y1 = p0
    x2, y2 = p1
    vx, vy = x2 - x1, y2 - y1
    len2 = vx*vx + vy*vy
    if len2 < 1e-6:
        return float('inf'), 0.0, float('inf'), float('inf')
    proj_t = ((x0 - x1)*vx + (y0 - y1)*vy) / len2
    px = x1 + proj_t * vx
    py = y1 + proj_t * vy
    dist = math.hypot(x0 - px, y0 - py)
    dist_left = math.hypot(x0 - x1, y0 - y1)
    dist_right = math.hypot(x0 - x2, y0 - y2)
    return dist, proj_t, dist_left, dist_right

def get_effective_distance(point: Tuple[float, float], p0: Tuple[float, float], p1: Tuple[float, float]):
    dist_seg, proj_t, d_left, d_right = compute_projection(point, p0, p1)
    if proj_t < 0:
        eff_dist = d_left
    elif proj_t > 1:
        eff_dist = d_right
    else:
        eff_dist = dist_seg
    return eff_dist, proj_t

def get_screen_info(screen: str, goal_lines: Dict) -> Tuple[Tuple[int, int], Tuple[int, int]]:
    screen_str = str(screen)
    base_screen = screen_str.rstrip('LR')
    if screen_str in goal_lines:
        line = goal_lines[screen_str]
    elif base_screen in goal_lines:
        line = goal_lines[base_screen]
    else:
        return None, None
    return line['p0'], line['p1']

def remove_static_positions(positions: List[Tuple[float, int, int]]) -> List[Tuple[float, int, int]]:
    if not positions or len(positions) < 5:
        return positions
    rounded = [(round(x/5)*5, round(y/5)*5) for _, x, y in positions]
    counter = Counter(rounded)
    total_frames = len(positions)
    static_threshold = 0.10 * total_frames
    static_cells = {cell for cell, count in counter.items() if count > static_threshold}
    if not static_cells:
        return positions
    filtered = []
    for t, x, y in positions:
        cell = (round(x/5)*5, round(y/5)*5)
        if cell not in static_cells:
            filtered.append((t, x, y))
    return filtered

def is_ball_moving(positions: List[Tuple[float, int, int]], min_movement: int = MIN_MOVEMENT_THRESHOLD) -> bool:
    if not positions or len(positions) < 2:
        return False
    unique_positions = get_unique_trajectory(positions)
    if len(unique_positions) < 2:
        return False
    max_x = max(p[1] for p in unique_positions)
    min_x = min(p[1] for p in unique_positions)
    max_y = max(p[2] for p in unique_positions)
    min_y = min(p[2] for p in unique_positions)
    total_movement = math.hypot(max_x - min_x, max_y - min_y)
    return total_movement > min_movement

def filter_static_ball_positions(positions: List[Tuple[float, int, int]]) -> List[Tuple[float, int, int]]:
    if not positions or len(positions) < 3:
        return positions
    filtered = remove_static_positions(positions)
    if not filtered or len(filtered) < 3:
        if is_ball_moving(positions):
            return positions
        else:
            return []
    if not is_ball_moving(filtered):
        if is_ball_moving(positions):
            return positions
        else:
            return []
    return filtered

def filter_positions_near_goal_lines(positions: List[Tuple[float, int, int]],
                                      screens: List[str],
                                      goal_lines: Dict,
                                      radius: int = MOVEMENT_RADIUS) -> List[Tuple[float, int, int]]:
    if not positions:
        return []
    near_positions = []
    for screen in screens:
        p0, p1 = get_screen_info(screen, goal_lines)
        if p0 is None:
            continue
        for t, x, y in positions:
            dist, _, _, _ = compute_projection((x, y), p0, p1)
            if dist <= radius:
                near_positions.append((t, x, y))
    if not near_positions:
        return []
    seen = set()
    unique_near = []
    for t, x, y in near_positions:
        key = (x, y)
        if key not in seen:
            seen.add(key)
            unique_near.append((t, x, y))
    return unique_near

def find_min_distance_to_screens(positions: List[Tuple[float, int, int]],
                                  screens: List[str],
                                  goal_lines: Dict,
                                  require_movement: bool = True,
                                  use_near_filter: bool = False) -> Tuple[Optional[str], float, Optional[float], Optional[float]]:
    if not positions:
        return None, float('inf'), None, None
    filtered = filter_static_ball_positions(positions)
    if not filtered:
        return None, float('inf'), None, None

    if require_movement:
        if use_near_filter:
            near_positions = filter_positions_near_goal_lines(filtered, screens, goal_lines)
        else:
            near_positions = filtered
        if not is_ball_moving(near_positions):
            return None, float('inf'), None, None

    unique_positions = get_unique_trajectory(filtered)
    best_screen = None
    best_dist = float('inf')
    best_time = None
    best_proj_t = None

    for screen in screens:
        p0, p1 = get_screen_info(screen, goal_lines)
        if p0 is None:
            continue
        min_dist = float('inf')
        min_time = None
        min_proj = None
        for t, x, y in unique_positions:
            eff_dist, proj_t = get_effective_distance((x, y), p0, p1)
            if eff_dist < min_dist:
                min_dist = eff_dist
                min_time = t
                min_proj = proj_t
        if min_dist < best_dist:
            best_dist = min_dist
            best_screen = screen
            best_time = min_time
            best_proj_t = min_proj

    return best_screen, best_dist, best_time, best_proj_t

# ------------------------------------------------------------------
# Special late search for GOAL – bypasses filtering and time limit
# ------------------------------------------------------------------
def search_goal_late(current_index: int, all_data: List[dict],
                     screens: List[str], goal_lines: Dict,
                     key: str, action_end_time: datetime) -> Tuple[bool, Optional[str], Optional[float], float, Optional[float]]:
    """
    Searches all blocks after current_index for any ball position that:
    - Has valid projection (0 <= proj_t <= 1)
    - Distance to goal line <= threshold for that screen
    Returns (found, screen, time_offset_from_action_end, distance, proj_t)
    """
    if current_index + 1 >= len(all_data):
        return False, None, None, float('inf'), None

    best_screen = None
    best_dist = float('inf')
    best_time_offset = None  # seconds from action_end_time to the ball position
    best_proj_t = None

    def get_goal_threshold(screen: str) -> float:
        return get_threshold_for_screen(screen, 'GOAL')

    for idx in range(current_index + 1, len(all_data)):
        block = all_data[idx]
        block_start_str = block.get('start_time')
        if not block_start_str:
            continue
        try:
            block_start = datetime.strptime(block_start_str, "%H:%M:%S.%f")
        except:
            continue

        block_data = block.get('data', [])
        if not block_data:
            continue

        # Get raw ball positions (no filtering)
        positions = get_positions_from_data(block_data, key, SCALE)
        if not positions:
            continue

        # For each position, compute distance to each screen
        for t, x, y in positions:
            for screen in screens:
                p0, p1 = get_screen_info(screen, goal_lines)
                if p0 is None:
                    continue
                eff_dist, proj_t = get_effective_distance((x, y), p0, p1)
                if not (0 <= proj_t <= 1):
                    continue  # projection outside segment -> not a valid entry
                threshold = get_goal_threshold(screen)
                if eff_dist <= threshold:
                    # Compute absolute time of this position relative to action_end_time
                    pos_abs_time = block_start + timedelta(seconds=t)
                    offset = (pos_abs_time - action_end_time).total_seconds()
                    # We want the earliest (or best) occurrence; we take the one with smallest distance
                    if eff_dist < best_dist:
                        best_dist = eff_dist
                        best_screen = screen
                        best_time_offset = offset
                        best_proj_t = proj_t

    if best_screen is not None:
        return True, best_screen, best_time_offset, best_dist, best_proj_t
    else:
        return False, None, None, float('inf'), None

# ------------------------------------------------------------------
# Standard late search for PASS/TARGET/PRESS (respects time limit)
# ------------------------------------------------------------------
def search_late_across_blocks(current_index: int, all_data: List[dict],
                               screens: List[str], goal_lines: Dict,
                               key: str, action_end_time: datetime,
                               action_type: str,
                               require_movement: bool = True,
                               filter_positions: bool = True) -> Tuple[bool, Optional[str], Optional[float], float, Optional[float]]:
    """
    Returns: (found, screen, time_offset, distance, proj_t)
    Used for non-GOAL actions.

    Parameters
    ----------
    require_movement : bool
        If True, the ball must be moving in the block to consider it.
    filter_positions : bool
        If True, static positions are filtered out.
    """
    if current_index + 1 >= len(all_data):
        return False, None, None, float('inf'), None

    best_screen = None
    best_dist = float('inf')
    best_time = None
    best_proj_t = None

    def get_threshold(screen: str) -> float:
        return get_threshold_for_screen(screen, action_type)

    for idx in range(current_index + 1, len(all_data)):
        block = all_data[idx]
        block_start_str = block.get('start_time')
        if not block_start_str:
            continue
        try:
            block_start = datetime.strptime(block_start_str, "%H:%M:%S.%f")
        except:
            continue

        offset = (block_start - action_end_time).total_seconds()
        if offset > LATE_SEARCH_DURATION:
            break

        block_data = block.get('data', [])
        if not block_data:
            continue

        # Get raw positions
        positions = get_positions_from_data(block_data, key, SCALE)
        if not positions:
            continue

        # Optionally filter static positions
        if filter_positions:
            filtered = filter_static_ball_positions(positions)
            if not filtered:
                continue
        else:
            filtered = positions

        # For PASS, we don't require movement; for others, we do
        if require_movement:
            if not is_ball_moving(filtered):
                continue

        # Find the best distance to any screen in this block
        best_screen_block, best_dist_block, best_time_block, best_proj_block = find_min_distance_to_screens(
            filtered, screens, goal_lines, require_movement=False   # we already handled movement above
        )

        if best_screen_block is not None:
            threshold = get_threshold(best_screen_block)
            if best_dist_block <= threshold:
                absolute_time = offset + (best_time_block if best_time_block is not None else 0)
                if absolute_time <= LATE_SEARCH_DURATION and best_dist_block < best_dist:
                    best_dist = best_dist_block
                    best_screen = best_screen_block
                    best_time = absolute_time
                    best_proj_t = best_proj_block

    if best_screen is not None:
        return True, best_screen, best_time, best_dist, best_proj_t
    else:
        return False, None, None, float('inf'), None

# ------------------------------------------------------------------
# NEW: check_ball_exited – checks if the ball leaves the goal area
# ------------------------------------------------------------------
def check_ball_exited(positions: List[Tuple[float, int, int]],
                      screen: str,
                      goal_lines: Dict,
                      min_time: float,
                      threshold: float,
                      session_duration: float,
                      exit_multiplier: float = 2.0,
                      search_frames: int = SEARCH_FRAMES) -> bool:
    """
    Returns True if the ball ever moves farther than threshold * exit_multiplier
    from the goal line after the minimum time (min_time) and within the session.
    """
    p0, p1 = get_screen_info(screen, goal_lines)
    if p0 is None:
        return True
    exit_dist = threshold * exit_multiplier
    count = 0
    for t, x, y in positions:
        if t > min_time and t <= session_duration:
            d, _, _, _ = compute_projection((x, y), p0, p1)
            if d > exit_dist:
                return True
            count += 1
            if count >= search_frames:
                break
    return False

# ------------------------------------------------------------------
# analyze_action_with_context - UPDATED PASS logic (using exit check)
# ------------------------------------------------------------------
def analyze_action_with_context(action_data: dict, goal_lines: Dict,
                                action_type: str, all_data: List[dict],
                                action_index: int) -> dict:
    action_id = action_data.get('id', '')
    screens = action_data['screens']
    data = action_data.get('data', [])
    key = 'p' if action_type == 'PRESS' else 'b'

    end_time_str = action_data.get('end_time')
    if end_time_str:
        try:
            action_end_time = datetime.strptime(end_time_str, "%H:%M:%S.%f")
        except:
            action_end_time = None
    else:
        action_end_time = None

    start_time_str = action_data.get('start_time')
    if start_time_str:
        try:
            session_start_time = datetime.strptime(start_time_str, "%H:%M:%S.%f")
        except:
            session_start_time = None
    else:
        session_start_time = None

    # ---- GOAL actions (UPDATED: corner rejection with new thresholds) ----
    if action_type == 'GOAL':
        positions = get_positions_from_data(data, key, SCALE)

        if not positions:
            return {
                'Action ID': action_id,
                'Action': action_type,
                'Screens': ', '.join(screens),
                'Result': 'Wrong',
                'Winning Screen': 'N/A',
                'Min Distance (px)': None,
                'Time of Min (s)': '-',
                'Session Duration (s)': '-',
                'Movement (px)': 0,
                'AEP': 'N/A',
                'proj_t': None
            }

        filtered_positions = filter_static_ball_positions(positions)
        if not filtered_positions:
            filtered_positions = positions

        best_screen, best_eff_dist, best_min_time, best_proj_t = find_min_distance_to_screens(
            filtered_positions, screens, goal_lines, require_movement=False
        )

        result = 'Wrong'
        winning_screen = 'N/A'
        display_time = '-'
        display_duration = '-'
        min_dist_display = best_eff_dist if best_eff_dist != float('inf') else None

        def get_goal_threshold(screen: str) -> float:
            return get_threshold_for_screen(screen, 'GOAL')

        valid_projection = False
        if best_proj_t is not None and 0 <= best_proj_t <= 1:
            valid_projection = True

        if best_screen is not None and valid_projection:
            # ---- NEW: reject if projection is near the ends (corners) ----
            if best_proj_t > PROJ_T_UPPER_THRESHOLD or best_proj_t < PROJ_T_LOWER_THRESHOLD:
                result = 'Wrong'
                winning_screen = 'N/A'
                display_time = '-'
                display_duration = '-'
                min_dist_display = None
            else:
                threshold = get_goal_threshold(best_screen)
                if best_eff_dist <= threshold:
                    result = 'Correct'
                    winning_screen = best_screen
                    display_time = f"{best_min_time:.3f}"
                    display_duration = f"{filtered_positions[-1][0]:.3f}"
                else:
                    if action_end_time is not None:
                        found_late, late_screen, late_time, late_dist, late_proj = search_goal_late(
                            action_index, all_data, screens, goal_lines, key, action_end_time
                        )
                        if found_late:
                            result = 'Late'
                            winning_screen = late_screen
                            display_time = f"{late_time:.3f}"
                            display_duration = f"{filtered_positions[-1][0]:.3f}"
                            min_dist_display = late_dist
        else:
            result = 'Wrong'
            winning_screen = 'N/A'
            display_time = '-'
            display_duration = '-'
            min_dist_display = None

        if result == 'Wrong':
            display_time = '-'
            display_duration = '-'
            winning_screen = 'N/A'

        aep = get_aep_orientation(screens, winning_screen)
        movement, _ = analyze_movement(filtered_positions)

        return {
            'Action ID': action_id,
            'Action': action_type,
            'Screens': ', '.join(screens),
            'Result': result,
            'Winning Screen': winning_screen,
            'Min Distance (px)': round(min_dist_display, 1) if min_dist_display is not None and min_dist_display != float('inf') else None,
            'Time of Min (s)': display_time,
            'Session Duration (s)': display_duration,
            'Movement (px)': movement,
            'AEP': aep,
            'proj_t': round(best_proj_t, 3) if best_proj_t is not None else None
        }

    # ---- PRESS and TARGET actions ----
    if action_type in ['PRESS', 'TARGET']:
        positions = get_positions_from_data(data, key, SCALE)
        filtered_positions = positions if action_type == 'PRESS' else filter_static_ball_positions(positions)
        if not filtered_positions:
            return {
                'Action ID': action_id,
                'Action': action_type,
                'Screens': ', '.join(screens),
                'Result': 'Wrong',
                'Winning Screen': 'N/A',
                'Min Distance (px)': None,
                'Time of Min (s)': '-',
                'Session Duration (s)': '-',
                'Movement (px)': 0,
                'AEP': 'N/A',
                'proj_t': None
            }
        if not is_ball_moving(filtered_positions):
            return {
                'Action ID': action_id,
                'Action': action_type,
                'Screens': ', '.join(screens),
                'Result': 'Wrong',
                'Winning Screen': 'N/A',
                'Min Distance (px)': None,
                'Time of Min (s)': '-',
                'Session Duration (s)': '-',
                'Movement (px)': 0,
                'AEP': 'N/A',
                'proj_t': None
            }
        unique_positions = get_unique_trajectory(filtered_positions)
        session_duration = unique_positions[-1][0] if unique_positions else 0
        movement, _ = analyze_movement(filtered_positions)

        best_screen, best_eff_dist, best_min_time, best_proj_t = find_min_distance_to_screens(
            filtered_positions, screens, goal_lines, require_movement=False
        )

        if best_screen is not None:
            action_threshold = get_threshold_for_screen(best_screen, action_type)
        else:
            action_threshold = 50 if action_type == 'PRESS' else CORRECT_THRESHOLD

        result = 'Wrong'
        winning_screen = 'N/A'
        display_time = '-'
        display_duration = '-'
        min_dist_display = best_eff_dist if best_eff_dist != float('inf') else None

        if best_screen is not None:
            if best_eff_dist <= action_threshold:
                result = 'Correct'
                winning_screen = best_screen
                display_time = f"{best_min_time:.3f}"
                display_duration = f"{session_duration:.3f}"
            else:
                if action_end_time is not None:
                    found_late, late_screen, late_time, late_dist, _ = search_late_across_blocks(
                        action_index, all_data, screens, goal_lines, key, action_end_time, action_type,
                        require_movement=True, filter_positions=True
                    )
                    if found_late:
                        result = 'Late'
                        winning_screen = late_screen
                        display_time = f"{late_time:.3f}"
                        display_duration = f"{session_duration:.3f}"
                        min_dist_display = late_dist

        if result == 'Wrong':
            display_time = '-'
            display_duration = '-'
            winning_screen = 'N/A'

        aep = get_aep_orientation(screens, winning_screen)

        return {
            'Action ID': action_id,
            'Action': action_type,
            'Screens': ', '.join(screens),
            'Result': result,
            'Winning Screen': winning_screen,
            'Min Distance (px)': round(min_dist_display, 1) if min_dist_display is not None and min_dist_display != float('inf') else None,
            'Time of Min (s)': display_time,
            'Session Duration (s)': display_duration,
            'Movement (px)': movement,
            'AEP': aep,
            'proj_t': round(best_proj_t, 3) if best_proj_t is not None else None
        }

    # ---- PASS actions (UPDATED with exit check) ----
    if action_type == 'PASS':
        positions = get_positions_from_data(data, key, SCALE)
        filtered_positions = filter_static_ball_positions(positions)
        if not filtered_positions:
            return {
                'Action ID': action_id,
                'Action': action_type,
                'Screens': ', '.join(screens),
                'Result': 'Wrong',
                'Winning Screen': 'N/A',
                'Min Distance (px)': None,
                'Time of Min (s)': '-',
                'Session Duration (s)': '-',
                'Movement (px)': 0,
                'AEP': 'N/A',
                'proj_t': None
            }

        session_duration = filtered_positions[-1][0] if filtered_positions else 0

        best_screen, best_eff_dist, best_min_time, best_proj_t = find_min_distance_to_screens(
            filtered_positions, screens, goal_lines, require_movement=False
        )

        result = 'Wrong'
        winning_screen = 'N/A'
        display_time = '-'
        display_duration = '-'
        min_dist_display = best_eff_dist if best_eff_dist != float('inf') else None

        def get_threshold(screen: str) -> float:
            return get_threshold_for_screen(screen, 'PASS')

        # --- Helper to check for exit in extended data ---
        def check_exit_extended(positions, screen, best_min_time, threshold, session_duration,
                                action_end_time, action_index, all_data, key, session_start_time):
            # First check within the action's own data
            is_exited = check_ball_exited(
                positions, screen, goal_lines,
                best_min_time, threshold, session_duration,
                exit_multiplier=2.0
            )
            if not is_exited and action_end_time is not None and session_start_time is not None:
                # Check in between-session blocks (up to 2.0s after session end)
                extra_positions = get_positions_from_blocks_after(
                    action_index, all_data, key, action_end_time, session_start_time,
                    time_window=2.0
                )
                if extra_positions:
                    all_positions = positions + extra_positions
                    all_positions.sort(key=lambda p: p[0])
                    extended_duration = all_positions[-1][0] if all_positions else session_duration
                    is_exited = check_ball_exited(
                        all_positions, screen, goal_lines,
                        best_min_time, threshold, extended_duration,
                        exit_multiplier=2.0
                    )
            return is_exited

        # --- If a screen was approached ---
        if best_screen is not None:
            threshold = get_threshold(best_screen)

            # --- Case 1: Ball entered the goal area during the session (distance <= threshold) ---
            if best_eff_dist <= threshold:
                # Check for exit (within session or shortly after)
                is_exited = check_exit_extended(
                    positions, best_screen, best_min_time, threshold, session_duration,
                    action_end_time, action_index, all_data, key, session_start_time
                )
                if is_exited:
                    result = 'Correct'
                    winning_screen = best_screen
                    display_time = f"{best_min_time:.3f}"
                    display_duration = f"{session_duration:.3f}"
                else:
                    result = 'Miss'
                    winning_screen = best_screen
                    display_time = '-'
                    display_duration = '-'
                    min_dist_display = None

            # --- Case 2: Near miss (within FINISH_DIST but not threshold) ---
            elif best_eff_dist <= FINISH_DIST:
                # Check for late entry (ball within threshold after session end)
                found_late = False
                if action_end_time is not None:
                    found_late, late_screen, late_time, late_dist, _ = search_late_across_blocks(
                        action_index, all_data, screens, goal_lines, key, action_end_time, action_type,
                        require_movement=False, filter_positions=False
                    )
                if found_late:
                    result = 'Late'
                    winning_screen = late_screen
                    display_time = f"{late_time:.3f}"
                    display_duration = f"{session_duration:.3f}"
                    min_dist_display = late_dist
                else:
                    result = 'Miss'
                    winning_screen = best_screen
                    display_time = '-'
                    display_duration = '-'
                    min_dist_display = None

            # --- Case 3: Too far (distance > FINISH_DIST) ---
            else:
                # Check for late entry
                found_late = False
                if action_end_time is not None:
                    found_late, late_screen, late_time, late_dist, _ = search_late_across_blocks(
                        action_index, all_data, screens, goal_lines, key, action_end_time, action_type,
                        require_movement=False, filter_positions=False
                    )
                if found_late:
                    result = 'Late'
                    winning_screen = late_screen
                    display_time = f"{late_time:.3f}"
                    display_duration = f"{session_duration:.3f}"
                    min_dist_display = late_dist
                else:
                    result = 'Wrong'
                    winning_screen = 'N/A'
                    display_time = '-'
                    display_duration = '-'
                    min_dist_display = None

        # --- No screen was approached at all ---
        else:
            # Check for late entry
            found_late = False
            if action_end_time is not None:
                found_late, late_screen, late_time, late_dist, _ = search_late_across_blocks(
                    action_index, all_data, screens, goal_lines, key, action_end_time, action_type,
                    require_movement=False, filter_positions=False
                )
            if found_late:
                result = 'Late'
                winning_screen = late_screen
                display_time = f"{late_time:.3f}"
                display_duration = f"{session_duration:.3f}"
                min_dist_display = late_dist
            else:
                result = 'Wrong'
                winning_screen = 'N/A'
                display_time = '-'
                display_duration = '-'
                min_dist_display = None

        # --- Finalise ---
        if result == 'Wrong':
            display_time = '-'
            display_duration = '-'
            winning_screen = 'N/A'

        movement, _ = analyze_movement(filtered_positions)
        aep = get_aep_orientation(screens, winning_screen)

        return {
            'Action ID': action_id,
            'Action': action_type,
            'Screens': ', '.join(screens),
            'Result': result,
            'Winning Screen': winning_screen,
            'Min Distance (px)': round(min_dist_display, 1) if min_dist_display is not None and min_dist_display != float('inf') else None,
            'Time of Min (s)': display_time,
            'Session Duration (s)': display_duration,
            'Movement (px)': movement,
            'AEP': aep,
            'proj_t': round(best_proj_t, 3) if best_proj_t is not None else None
        }

    # Fallback (should not reach here)
    return {
        'Action ID': action_id,
        'Action': action_type,
        'Screens': ', '.join(screens),
        'Result': 'Wrong',
        'Winning Screen': 'N/A',
        'Min Distance (px)': None,
        'Time of Min (s)': '-',
        'Session Duration (s)': '-',
        'Movement (px)': 0,
        'AEP': 'N/A',
        'proj_t': None
    }

# ------------------------------------------------------------------
# Helper functions (unchanged)
# ------------------------------------------------------------------
def analyze_movement(unique_positions: List[Tuple[float, int, int]]) -> Tuple[int, str]:
    if len(unique_positions) < 2:
        return 0, 'NONE'
    start_x = unique_positions[0][1]
    max_x = max(p[1] for p in unique_positions)
    min_x = min(p[1] for p in unique_positions)
    if max_x - start_x > 100:
        return max_x - start_x, 'RIGHT'
    elif start_x - min_x > 100:
        return start_x - min_x, 'LEFT'
    else:
        return 0, 'NONE'

def get_positions_from_blocks_after(current_index: int,
                                     all_data: List[dict],
                                     key: str,
                                     action_end_time: datetime,
                                     session_start_time: datetime,
                                     time_window: float = 2.0) -> List[Tuple[float, int, int]]:
    """
    Collect ball positions from blocks after the given action index,
    up to `time_window` seconds after the action end time.
    Default time_window is now 2.0 seconds.
    """
    extra_positions = []
    for idx in range(current_index + 1, len(all_data)):
        block = all_data[idx]
        block_start_str = block.get('start_time')
        if not block_start_str:
            continue
        try:
            block_start = datetime.strptime(block_start_str, "%H:%M:%S.%f")
        except:
            continue
        offset = (block_start - action_end_time).total_seconds()
        if offset > time_window:
            break
        block_data = block.get('data', [])
        if not block_data:
            continue
        positions = get_positions_from_data(block_data, key, SCALE)
        if not positions:
            continue
        time_offset = (block_start - session_start_time).total_seconds()
        for t, x, y in positions:
            extra_positions.append((t + time_offset, x, y))
    return extra_positions

def check_ball_return(positions: List[Tuple[float, int, int]],
                      screen: str,
                      goal_lines: Dict,
                      min_time: float,
                      threshold: float,
                      session_duration: float,
                      search_frames: int = SEARCH_FRAMES,
                      entry_threshold: Optional[float] = None) -> bool:
    p0, p1 = get_screen_info(screen, goal_lines)
    if p0 is None:
        return True
    check_dist = entry_threshold if entry_threshold is not None else threshold * 2
    count = 0
    for t, x, y in positions:
        if t > min_time and t <= session_duration:
            d, _, _, _ = compute_projection((x, y), p0, p1)
            if d <= check_dist:
                return True
            count += 1
            if count >= search_frames:
                break
    return False

def get_aep_orientation(screens: List[str], winning_screen: Optional[str]) -> str:
    if not screens or len(screens) != 2:
        return 'N/A'
    if winning_screen is None or winning_screen == 'N/A':
        return 'N/A'
    try:
        s1, s2 = [int(s) for s in screens]
        win = int(winning_screen)
    except (ValueError, TypeError):
        return 'N/A'
    right_screens = {2,3,4,9,10,11}
    left_screens = {5,6,7,12,13,14}
    special_pairs = [{2,4}, {12,14}, {9,11}, {5,7}]
    pair_set = {s1, s2}
    if pair_set in special_pairs:
        if win == min(s1, s2):
            return 'Left'
        elif win == max(s1, s2):
            return 'Right'
        else:
            return 'N/A'
    if win in right_screens:
        return 'Right'
    elif win in left_screens:
        return 'Left'
    else:
        return 'N/A'

# ------------------------------------------------------------------
# compute_aep, compute_total_player_distance, main (unchanged)
# ------------------------------------------------------------------
def compute_aep(results_df: pd.DataFrame) -> Dict[str, float]:
    right_screens = {2,3,4,9,10,11}
    left_screens = {5,6,7,12,13,14}
    right_count = 0
    left_count = 0
    special_pairs = [{2,4}, {12,14}, {9,11}, {5,7}]
    for _, row in results_df.iterrows():
        if row['Result'] not in ['Correct', 'Late']:
            continue
        screens_str = row['Screens']
        if not screens_str:
            continue
        screens = [int(s.strip()) for s in screens_str.split(',') if s.strip().isdigit()]
        if len(screens) != 2:
            continue
        win = row['Winning Screen']
        if win == 'N/A' or win is None:
            continue
        try:
            win = int(win)
        except:
            continue
        s1, s2 = screens
        pair_set = {s1, s2}
        if pair_set in special_pairs:
            if win == min(s1, s2):
                left_count += 1
            elif win == max(s1, s2):
                right_count += 1
        else:
            if win in right_screens:
                right_count += 1
            elif win in left_screens:
                left_count += 1
    total = right_count + left_count
    if total == 0:
        return {'right': 0.0, 'left': 0.0}
    return {'right': (right_count / total) * 100, 'left': (left_count / total) * 100}

def compute_total_player_distance(all_data: List[dict], sample_step: int = 4) -> float:
    all_positions = []
    for block in all_data:
        block_data = block.get('data', [])
        if not block_data:
            continue
        start_time_str = block.get('start_time')
        if not start_time_str:
            continue
        try:
            block_start = datetime.strptime(start_time_str, "%H:%M:%S.%f")
        except:
            continue
        for idx, entry in enumerate(block_data):
            if idx % sample_step != 0:
                continue
            t = entry.get('t', 0.0)
            hp = entry.get('hp')
            if hp is not None and isinstance(hp, list) and len(hp) == 2:
                x, y = hp[0], hp[1]
                abs_time = block_start + timedelta(seconds=t)
                all_positions.append((abs_time, x, y))
    if len(all_positions) < 2:
        return 0.0
    all_positions.sort(key=lambda p: p[0])
    total_dist_px = 0.0
    for i in range(1, len(all_positions)):
        _, x1, y1 = all_positions[i-1]
        _, x2, y2 = all_positions[i]
        total_dist_px += math.hypot(x2 - x1, y2 - y1)
    total_dist_meters = total_dist_px * PIXEL_TO_METER_SCALE
    return total_dist_meters

def main():
    # Goal lines for 1280x360
    GOAL_LINES = {
        "1": {"p0": (629, 293), "p1":  (12, 285)},
        "2": {"p0": (2, 298), "p1": (3, 253)},
        "3": {"p0": (22, 194), "p1": (44, 174)},
        "4": {"p0": (101, 140), "p1": (128, 129)},
        "5": {"p0": (1154, 112), "p1": (1180, 122)},
        "6": {"p0": (1239, 161), "p1": (1260, 180)},
        "7": {"p0":  (1275, 243), "p1": (1272, 287)},
        "8": {"p0": (1269, 276), "p1":  (652, 274)},
        "9": {"p0": (642, 286), "p1": (642, 242)},
        "10": {"p0":  (662, 178), "p1": (682, 158)},
        "11": {"p0":  (741, 121), "p1": (767, 111)},
        "12": {"p0": (513, 133), "p1": (541, 142)},
        "13": {"p0":  (599, 180), "p1":  (620, 198)},
        "14": {"p0": (637, 262), "p1": (636, 303)},
        "9L": {"p0": (642, 241), "p1": (647, 191)},
        "6L": {"p0": (1262, 181), "p1": (1273, 222)},
    }

    try:
        data = load_recognition_file('recognition.json')
    except FileNotFoundError:
        print("Please save the recognition data to 'recognition.json' file")
        return

    actions = [item for item in data if item.get('action') in ['PASS', 'TARGET', 'PRESS', 'GOAL']]
    if not actions:
        print("No PASS, TARGET, PRESS, or GOAL actions found.")
        return

    print("\n" + "="*140)
    print(f"ANALYZING {len(actions)} ACTIONS (GOAL: valid projection required; no late for invalid)")
    print("="*140)
    print(f"MIN_MOVEMENT_THRESHOLD = {MIN_MOVEMENT_THRESHOLD} px")
    print(f"MOVEMENT_RADIUS = {MOVEMENT_RADIUS} px")
    print(f"LATE_SEARCH_DURATION = {LATE_SEARCH_DURATION}s (only for PASS/TARGET/PRESS)")
    print(f"LEAVE_THRESHOLD = {LEAVE_THRESHOLD} px")
    print(f"FINISH_DIST = {FINISH_DIST} px")
    print(f"SEARCH_FRAMES = {SEARCH_FRAMES}")
    print(f"MIN_NEAR_FRAMES = {MIN_NEAR_FRAMES} (not used)")
    print(f"PRE_FRAMES = {PRE_FRAMES} (not used)")
    print(f"ENTRY_MARGIN = {ENTRY_MARGIN} (not used)")
    print(f"SCALE = {SCALE}")
    print(f"PIXEL_TO_METER_SCALE = {PIXEL_TO_METER_SCALE} m/pixel")
    print(f"Screen-specific thresholds (PASS/TARGET/GOAL): {SCREEN_CORRECT_THRESHOLDS}")
    print(f"GOAL-specific overrides: {GOAL_SCREEN_THRESHOLDS}")
    print(f"Screen-specific thresholds (PRESS): {PRESS_SCREEN_THRESHOLDS}")
    print("="*140)

    results = []
    for idx, action in enumerate(data):
        if action.get('action') not in ['PASS', 'TARGET', 'PRESS', 'GOAL']:
            continue
        action_type = action['action']
        result = analyze_action_with_context(action, GOAL_LINES, action_type, data, idx)
        results.append(result)

    df = pd.DataFrame(results)
    cols = ['Action ID', 'Action', 'Screens', 'Result', 'Winning Screen',
            'Min Distance (px)', 'Time of Min (s)', 'Session Duration (s)',
            'Movement (px)', 'AEP', 'proj_t']
    df = df[cols]
    print(df.to_string(index=False))

    df.to_csv('all_actions_results_updated.csv', index=False)
    print("\nResults saved to 'all_actions_results_updated.csv'")

    miss_count = len(df[df['Result'] == 'Miss'])
    correct_count = len(df[df['Result'] == 'Correct'])
    late_count = len(df[df['Result'] == 'Late'])
    wrong_count = len(df[df['Result'] == 'Wrong'])
    total = len(df)

    accuracy = ((correct_count + late_count) / total) * 100 if total > 0 else 0
    action_economy = ((correct_count + late_count + miss_count) / total) * 100 if total > 0 else 0

    correct_times = []
    for _, row in df[df['Result'] == 'Correct'].iterrows():
        time_str = row['Time of Min (s)']
        if time_str != '-':
            try:
                correct_times.append(float(time_str))
            except ValueError:
                pass
    aet = sum(correct_times) / len(correct_times) if correct_times else 0.0

    aep = compute_aep(df)

    total_distance = compute_total_player_distance(data)
    avg_distance = total_distance / total if total > 0 else 0

    print("\n" + "="*140)
    print("SUMMARY METRICS")
    print("="*140)
    print(f"Correct: {correct_count} | Late: {late_count} | Wrong: {wrong_count} | Miss: {miss_count} | Total: {total}")
    print(f"On‑time Accuracy (Correct+Late / Total): {accuracy:.1f}%")
    print(f"Goal Area Completion (Correct+Late+Miss / Total): {action_economy:.1f}%")
    print(f"AET (avg finish time for Correct): {aet:.3f}s")
    print(f"AEP - Right:        {aep['right']:.1f}%")
    print(f"AEP - Left:         {aep['left']:.1f}%")
    print(f"Economy of Play (Total distance): {total_distance:.2f} m")
    print(f"Average distance per action: {avg_distance:.2f} m")
    print("="*140)

if __name__ == "__main__":
    main()