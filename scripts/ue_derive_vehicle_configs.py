"""Derive per-vehicle 24-pt keypoint configs for all City Sample vehicles (run inside UE editor).

Run via MCP python console: import ue_derive_vehicle_configs; ue_derive_vehicle_configs.derive_all()
Or chunked: derive_all(limit=10, start=0)

Outputs: configs/vehicles/citysample_<type>.json for each discovered vehicle type.
Skips citysample_vehCar_vehicle13.json (hand-tuned reference).
"""

# mypy: ignore-errors
from __future__ import annotations

import json
import os
import re
from typing import Any

import unreal  # editor-only, not resolvable outside the editor

CONFIGS_DIR = "D:/Projects/GitHub/ue5-vehicle-synth/configs/vehicles"
SKIP_TYPE = "vehCar_vehicle13"

# Keypoint schema order (must match EXTENDED_KEYPOINT_NAMES in schema.py)
SCHEMA_ORDER = [
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
]

# Sanity bounds (actor-local cm)
_SANITY_Y_MAX = 200.0
_SANITY_Z_MIN = 0.0
_SANITY_Z_MAX = 300.0


def _scan_vehicle_meshes() -> list[tuple[str, Any]]:
    """Return [(type_id, asset_data), ...] for main SKM_veh* meshes under /Game/Vehicle."""
    ar = unreal.AssetRegistryHelpers.get_asset_registry()
    filter_obj = unreal.ARFilter(
        class_paths=[unreal.TopLevelAssetPath("/Script/Engine", "SkeletalMesh")],
        package_paths=["/Game/Vehicle"],
        recursive_paths=True,
    )
    assets = ar.get_assets(filter_obj)
    results = []
    skip_pattern = re.compile(r"Proxy|Collision|Skinning|Destructible|Exterior", re.IGNORECASE)
    for ad in assets:
        name = str(ad.asset_name)
        if not name.startswith("SKM_veh"):
            continue
        if skip_pattern.search(name):
            continue
        # type_id = parent directory name, e.g. vehCar_vehicle13
        pkg = str(ad.package_path)  # e.g. /Game/Vehicle/vehCar_vehicle13/Mesh
        parts = pkg.strip("/").split("/")
        # Find the part right after "Vehicle"
        try:
            vi = parts.index("Vehicle")
            type_id = parts[vi + 1]
        except (ValueError, IndexError):
            continue
        results.append((type_id, ad))
    # Deduplicate: one mesh per type (first encountered)
    seen: dict[str, Any] = {}
    for type_id, ad in results:
        if type_id not in seen:
            seen[type_id] = ad
    return list(seen.items())


def _get_bones(comp: Any) -> dict[str, list[float]]:
    """Return {bone_name: [x, y, z]} in actor-local cm."""
    n = comp.get_num_bones()
    bones: dict[str, list[float]] = {}
    for i in range(n):
        bname = str(comp.get_bone_name(i))
        t = comp.get_socket_transform(bname, unreal.RelativeTransformSpace.RTS_ACTOR).translation
        bones[bname] = [t.x, t.y, t.z]
    return bones


def _find_bone(bones: dict[str, list[float]], *candidates: str) -> list[float] | None:
    """Return first matching bone position, case-insensitive partial match."""
    for c in candidates:
        cl = c.lower()
        for k, v in bones.items():
            if cl in k.lower():
                return v
    return None


def _clip_warn(
    name: str, pt: list[float], x_min: float, x_max: float, warnings: list[str]
) -> list[float]:
    """Clamp point into sanity bounds, append a warning if clamped."""
    x, y, z = pt
    changed = False
    if abs(y) > _SANITY_Y_MAX:
        y = _SANITY_Y_MAX * (1 if y >= 0 else -1)
        changed = True
    if z < _SANITY_Z_MIN:
        z = _SANITY_Z_MIN
        changed = True
    if z > _SANITY_Z_MAX:
        z = _SANITY_Z_MAX
        changed = True
    if x < x_min - 50:
        x = x_min - 50
        changed = True
    if x > x_max + 50:
        x = x_max + 50
        changed = True
    if changed:
        warnings.append(f"{name}: clamped to sanity bounds -> [{x:.1f}, {y:.1f}, {z:.1f}]")
    return [round(x, 1), round(y, 1), round(z, 1)]


def _derive_keypoints(
    bones: dict[str, list[float]],
    type_id: str,
    bounds_top_z: float | None = None,
    bounds_center_x: float = 0.0,
) -> tuple[dict[str, list[float]], list[str], list[str]]:
    """Derive all 24 keypoints from bone positions.

    bounds_top_z: mesh-bounds top in actor space - the roof anchor when the
    `roof` bone is missing (buses/trucks/vans are far taller than the sedan
    fallback constant, which poisons every roof-relative point).

    Returns (keypoints_dict, bones_used, warnings).
    """
    warnings: list[str] = []
    bones_used: list[str] = []

    def use(name: str, pos: list[float]) -> list[float]:
        bones_used.append(name)
        return [round(v, 1) for v in pos]

    # --- Wheel bones (exact) ---
    wfl = _find_bone(bones, "wheel_front_l", "WheelFrontLeft", "wheel_FL")
    wfr = _find_bone(bones, "wheel_front_r", "WheelFrontRight", "wheel_FR")
    wrl = _find_bone(bones, "wheel_rear_l", "WheelRearLeft", "wheel_RL")
    wrr = _find_bone(bones, "wheel_rear_r", "WheelRearRight", "wheel_RR")

    # Fallbacks: synthesize from available wheels
    if wfr is None and wfl is not None:
        wfr = [wfl[0], -wfl[1], wfl[2]]
        warnings.append("wheel_front_r: mirrored from wheel_front_l")
    if wfl is None and wfr is not None:
        wfl = [wfr[0], -wfr[1], wfr[2]]
        warnings.append("wheel_front_l: mirrored from wheel_front_r")
    if wrr is None and wrl is not None:
        wrr = [wrl[0], -wrl[1], wrl[2]]
        warnings.append("wheel_rear_r: mirrored from wheel_rear_l")
    if wrl is None and wrr is not None:
        wrl = [wrr[0], -wrr[1], wrr[2]]
        warnings.append("wheel_rear_l: mirrored from wheel_rear_r")
    if wfl is None:
        wfl = [152.0, -77.6, 33.6]
        warnings.append("wheel_front_l: using vehicle13 fallback")
    if wfr is None:
        wfr = [152.0, 77.6, 33.6]
        warnings.append("wheel_front_r: using vehicle13 fallback")
    if wrl is None:
        wrl = [-145.4, -84.1, 33.6]
        warnings.append("wheel_rear_l: using vehicle13 fallback")
    if wrr is None:
        wrr = [-145.4, 84.1, 33.6]
        warnings.append("wheel_rear_r: using vehicle13 fallback")

    # --- Bumper bones ---
    bf = _find_bone(bones, "bumper_front", "BumperFront")
    br = _find_bone(bones, "bumper_rear", "BumperRear")
    bf2l = _find_bone(bones, "bumper_front_02_l", "BumperFront02L", "bumper_front_l")
    bf2r = _find_bone(bones, "bumper_front_02_r", "BumperFront02R", "bumper_front_r")
    br2l = _find_bone(bones, "bumper_rear_02_l", "BumperRear02L", "bumper_rear_l")
    br2r = _find_bone(bones, "bumper_rear_02_r", "BumperRear02R", "bumper_rear_r")

    # Bumper fallbacks
    if bf is None:
        bf = [wfr[0] * 1.614, 0.0, wfr[2]]
        warnings.append("bumper_front: estimated from wheel_front_r")
    if br is None:
        br = [wrl[0] * 1.908, 0.0, wrl[2]]
        warnings.append("bumper_rear: estimated from wheel_rear_l")

    big_l = bf[0] - br[0]  # vehicle length proxy

    if bf2l is None:
        bf2l = [bf[0] - 0.056 * big_l, -abs(wfl[1]), bf[2]]
        warnings.append("bumper_front_02_l: derived fallback")
    if bf2r is None:
        bf2r = [bf[0] - 0.056 * big_l, abs(wfr[1]), bf[2]]
        warnings.append("bumper_front_02_r: derived fallback")
    if br2l is None:
        br2l = [br[0] + 0.096 * big_l, -abs(wrl[1]), br[2]]
        warnings.append("bumper_rear_02_l: derived fallback")
    if br2r is None:
        br2r = [br[0] + 0.096 * big_l, abs(wrr[1]), br[2]]
        warnings.append("bumper_rear_02_r: derived fallback")

    # --- Roof ---
    roof = _find_bone(bones, "roof", "Roof")
    if roof is None:
        if bounds_top_z is not None and bounds_top_z > 60.0:
            # anchor on the real mesh top: roof plane sits just under the bounds top
            roof = [bounds_center_x, 0.0, 0.97 * bounds_top_z]
            warnings.append("roof: derived from mesh bounds top")
        else:
            roof = [-52.7, 0.0, 148.5]
            warnings.append("roof: using vehicle13 fallback")

    # --- Mirror bones ---
    mir_l = _find_bone(bones, "side_view_mirror_body_l", "mirror_l", "Mirror_L")
    mir_r = _find_bone(bones, "side_view_mirror_body_r", "mirror_r", "Mirror_R")
    if mir_l is None:
        mir_l = [0.66 * wfl[0], -1.07 * abs(wfl[1]), 0.68 * roof[2]]
        warnings.append("side_view_mirror_body_l: derived fallback")
    if mir_r is None:
        mir_r = [0.66 * wfr[0], 1.07 * abs(wfr[1]), 0.68 * roof[2]]
        warnings.append("side_view_mirror_body_r: derived fallback")

    x_min = br[0]
    x_max = bf[0]

    # --- Derive all 24 keypoints (spec ratios) ---
    kpts: dict[str, list[float]] = {}

    # 0-3: wheels (exact bones)
    kpts["Right_Front_wheel"] = use("wheel_front_r", wfr)
    kpts["Left_Front_wheel"] = use("wheel_front_l", wfl)
    kpts["Right_Back_wheel"] = use("wheel_rear_r", wrr)
    kpts["Left_Back_wheel"] = use("wheel_rear_l", wrl)

    # 4-5: HeadLights
    hl_x = bf[0] - 0.034 * big_l
    hl_y = 0.84 * abs(bf2r[1])
    hl_z = 0.505 * roof[2]
    kpts["Right_Front_HeadLight"] = _clip_warn(
        "Right_Front_HeadLight", [hl_x, hl_y, hl_z], x_min, x_max, warnings
    )
    kpts["Left_Front_HeadLight"] = _clip_warn(
        "Left_Front_HeadLight", [hl_x, -hl_y, hl_z], x_min, x_max, warnings
    )

    # 6-7: TailLights
    tl_x = br[0] + 0.063 * big_l
    tl_y = 0.873 * abs(br2r[1])
    tl_z = 0.572 * roof[2]
    kpts["Right_Back_HeadLight"] = _clip_warn(
        "Right_Back_HeadLight", [tl_x, tl_y, tl_z], x_min, x_max, warnings
    )
    kpts["Left_Back_HeadLight"] = _clip_warn(
        "Left_Back_HeadLight", [tl_x, -tl_y, tl_z], x_min, x_max, warnings
    )

    # 8: Exhaust
    ex_x = br[0] + 0.038 * big_l
    ex_y = -0.524 * abs(br2r[1])
    ex_z = 0.80 * wrr[2]
    kpts["Exhaust"] = _clip_warn("Exhaust", [ex_x, ex_y, ex_z], x_min, x_max, warnings)

    # 9-12: Roof corners
    rx_front = roof[0] + 0.128 * big_l
    rx_rear = roof[0] - 0.138 * big_l
    ry = 0.66 * abs(bf2r[1])
    rz = 0.956 * roof[2]
    kpts["Right_Front_Top"] = _clip_warn(
        "Right_Front_Top", [rx_front, ry, rz], x_min, x_max, warnings
    )
    kpts["Left_Front_Top"] = _clip_warn(
        "Left_Front_Top", [rx_front, -ry, rz], x_min, x_max, warnings
    )
    kpts["Right_Back_Top"] = _clip_warn("Right_Back_Top", [rx_rear, ry, rz], x_min, x_max, warnings)
    kpts["Left_Back_Top"] = _clip_warn("Left_Back_Top", [rx_rear, -ry, rz], x_min, x_max, warnings)

    # 13: Center
    cx = (wfr[0] + wrr[0]) / 2.0
    cz = 0.43 * roof[2]
    kpts["Center"] = _clip_warn("Center", [cx, 0.0, cz], x_min, x_max, warnings)

    # 14-15: Mirrors (exact or fallback)
    kpts["Left_Side_Mirror"] = use("side_view_mirror_body_l", mir_l)
    kpts["Right_Side_Mirror"] = use("side_view_mirror_body_r", mir_r)

    # 16-19: Bumper corners (exact or fallback)
    kpts["Front_Left_Bumper_Corner"] = _clip_warn(
        "Front_Left_Bumper_Corner", [bf2l[0], -abs(bf2l[1]), bf2l[2]], x_min, x_max, warnings
    )
    kpts["Front_Right_Bumper_Corner"] = _clip_warn(
        "Front_Right_Bumper_Corner", [bf2r[0], abs(bf2r[1]), bf2r[2]], x_min, x_max, warnings
    )
    kpts["Rear_Left_Bumper_Corner"] = _clip_warn(
        "Rear_Left_Bumper_Corner", [br2l[0], -abs(br2l[1]), br2l[2]], x_min, x_max, warnings
    )
    kpts["Rear_Right_Bumper_Corner"] = _clip_warn(
        "Rear_Right_Bumper_Corner", [br2r[0], abs(br2r[1]), br2r[2]], x_min, x_max, warnings
    )

    # 20-21: Windshield bottoms
    ws_x = rx_front + 0.063 * big_l
    ws_y = 0.72 * abs(bf2r[1])
    ws_z = 0.727 * roof[2]
    kpts["Windshield_Bottom_Left"] = _clip_warn(
        "Windshield_Bottom_Left", [ws_x, -ws_y, ws_z], x_min, x_max, warnings
    )
    kpts["Windshield_Bottom_Right"] = _clip_warn(
        "Windshield_Bottom_Right", [ws_x, ws_y, ws_z], x_min, x_max, warnings
    )

    # 22-23: Rear window bottoms
    rw_x = rx_rear - 0.044 * big_l
    rw_y = 0.70 * abs(br2r[1])
    rw_z = 0.774 * roof[2]
    kpts["Rear_Window_Bottom_Left"] = _clip_warn(
        "Rear_Window_Bottom_Left", [rw_x, -rw_y, rw_z], x_min, x_max, warnings
    )
    kpts["Rear_Window_Bottom_Right"] = _clip_warn(
        "Rear_Window_Bottom_Right", [rw_x, rw_y, rw_z], x_min, x_max, warnings
    )

    # Emit in schema order
    ordered = {k: kpts[k] for k in SCHEMA_ORDER}
    return ordered, list(set(bones_used)), warnings


def _process_type(
    type_id: str,
    asset_data: Any,
    actor: Any,
    world: Any,
) -> dict:
    """Load mesh onto actor, read bones, derive config. Return config dict."""
    # UE 5.6: AssetData.object_path is gone - load via package_name
    asset_path = str(asset_data.package_name)
    mesh = unreal.load_asset(asset_path)
    comp = actor.skeletal_mesh_component
    comp.set_skinned_asset_and_update(mesh)
    # bone transforms are valid right after set_skinned_asset_and_update on a
    # spawned (registered) actor - no extra force-update call exists/is needed
    bones = _get_bones(comp)
    # actor-space bounds top = roof anchor for roof-bone-less types (bus/truck/van)
    b_origin, b_extent = actor.get_actor_bounds(False)
    actor_z = actor.get_actor_location().z
    actor_x = actor.get_actor_location().x
    bounds_top_z = (b_origin.z + b_extent.z) - actor_z
    bounds_center_x = b_origin.x - actor_x
    kpts, bones_used, warnings = _derive_keypoints(
        bones, type_id, bounds_top_z=bounds_top_z, bounds_center_x=bounds_center_x
    )

    return {
        "vehicle_id": f"citysample_{type_id}",
        "source": f"Epic City Sample 5.6, /Game/Vehicle/{type_id}",
        "space": "actor-local, cm, x=forward y=right z=up",
        "derivation": "autogenerated by ue_derive_vehicle_configs.py using vehicle13 bone ratios",
        "keypoints": kpts,
        "bones_used": bones_used,
        "warnings": warnings,
    }


def derive_all(limit: int | None = None, start: int = 0) -> str:
    """Derive configs for all City Sample vehicle types.

    Args:
        limit: max number of types to process (None = all)
        start: index offset (for chunked runs)

    Returns:
        Summary string suitable for printing in MCP python console.
    """
    ues = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
    world = ues.get_editor_world()
    eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)

    # Spawn a transient SkeletalMeshActor at a safe sky-high spot
    spawn_loc = unreal.Vector(0.0, 0.0, 100000.0)
    spawn_rot = unreal.Rotator(roll=0.0, pitch=0.0, yaw=0.0)
    actor = eas.spawn_actor_from_class(
        unreal.SkeletalMeshActor,
        spawn_loc,
        spawn_rot,
    )
    actor.set_actor_label("VKD_TempDerivationActor")

    os.makedirs(CONFIGS_DIR, exist_ok=True)
    mesh_list = _scan_vehicle_meshes()
    slice_ = mesh_list[start : (start + limit) if limit is not None else None]

    written = []
    skipped = []
    errors = []

    for type_id, asset_data in slice_:
        # vehicle13 is hand-tuned; trailers are not cars (no wheel bones, wrong
        # semantics for a CarFusion-style vehicle category)
        if type_id == SKIP_TYPE or "trailer" in type_id.lower():
            skipped.append(type_id)
            continue
        out_path = os.path.join(CONFIGS_DIR, f"citysample_{type_id}.json")
        try:
            cfg = _process_type(type_id, asset_data, actor, world)
            with open(out_path, "w", encoding="utf-8") as fh:
                json.dump(cfg, fh, indent=2)
            written.append(type_id)
        except Exception as exc:
            errors.append(f"{type_id}: {exc}")

    # Destroy temp actor
    actor.destroy_actor()

    lines = [
        f"derive_all: processed {len(slice_)} types (start={start}, limit={limit})",
        f"  written : {len(written)} - {written}",
        f"  skipped : {skipped}",
        f"  errors  : {errors}",
    ]
    return "\n".join(lines)
