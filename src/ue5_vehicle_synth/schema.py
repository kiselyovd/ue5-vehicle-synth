"""24-pt extended vehicle keypoint schema.

The first 14 indices are the CarFusion canonical schema (verified against
Occlusion-Net source); indices 14-23 are the extension defined in the spec.
"""

from __future__ import annotations

EXTENDED_KEYPOINT_NAMES: tuple[str, ...] = (
    "Right_Front_wheel",
    "Left_Front_wheel",
    "Right_Back_wheel",
    "Left_Back_wheel",
    "Right_Front_HeadLight",
    "Left_Front_HeadLight",
    "Right_Back_HeadLight",
    "Left_Back_HeadLight",
    "Exhaust",
    "Right_Front_Top",
    "Left_Front_Top",
    "Right_Back_Top",
    "Left_Back_Top",
    "Center",
    "Left_Side_Mirror",
    "Right_Side_Mirror",
    "Front_Left_Bumper_Corner",
    "Front_Right_Bumper_Corner",
    "Rear_Left_Bumper_Corner",
    "Rear_Right_Bumper_Corner",
    "Windshield_Bottom_Left",
    "Windshield_Bottom_Right",
    "Rear_Window_Bottom_Left",
    "Rear_Window_Bottom_Right",
)

assert len(EXTENDED_KEYPOINT_NAMES) == 24

EXTENDED_SKELETON_EDGES: tuple[tuple[int, int], ...] = (
    # CarFusion canonical 18 edges
    (0, 2), (1, 3), (0, 1), (2, 3),
    (9, 11), (10, 12), (9, 10), (11, 12),
    (4, 0), (5, 1), (6, 2), (7, 3),
    (4, 9), (5, 10), (6, 11), (7, 12),
    (4, 5), (6, 7),
    # Extension 11 edges
    (14, 15),
    (14, 5), (15, 4),
    (16, 17), (18, 19),
    (16, 4), (17, 5), (18, 6), (19, 7),
    (20, 21), (22, 23),
)

assert len(EXTENDED_SKELETON_EDGES) == 29

OKS_SIGMAS_24: tuple[float, ...] = (
    # CarFusion canonical 14 - all 0.05 per CarFusion default
    0.05, 0.05, 0.05, 0.05, 0.05, 0.05, 0.05, 0.05, 0.05, 0.05, 0.05, 0.05, 0.05, 0.05,
    # Extension 10 - 0.06 (slightly less precise semantically)
    0.06, 0.06, 0.06, 0.06, 0.06, 0.06, 0.06, 0.06, 0.06, 0.06,
)

assert len(OKS_SIGMAS_24) == 24
