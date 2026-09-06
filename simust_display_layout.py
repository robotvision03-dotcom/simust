"""Shared ring layout for waiting overlays and coach results videos.

Waiting and results use the same center and size so the 14-slice strip
does not jump up or down when processing finishes.
Rings are 30% smaller than the previous 90px / 22px results charts.
"""

CHART_CENTER_Y = 140
RING_RADIUS = 63
RING_THICKNESS = 15
