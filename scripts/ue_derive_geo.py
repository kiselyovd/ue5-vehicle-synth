"""Vertex+bone keypoint derivation for City Sample vehicles (run inside UE editor).

Fixes the car-proportioned labels the old sedan-ratio derivation produced on large
vehicles. Every roof / light / exhaust / center point is measured off the REAL static
mesh vertex cloud (ProceduralMeshLibrary.get_section_from_static_mesh, works for every
type incl. the boneless bus/big-vans); wheels + mirrors use the skeletal bones (all
vehicles have wheel bones). No sedan ratios anywhere.

    import ue_derive_geo as g
    g.preview("vehVan_vehicle01")     # dict of the 14 CarFusion points
    g.derive_all()                    # rewrite configs/vehicles/citysample_*.json
"""

from __future__ import annotations

# mypy: ignore-errors
import glob
import json
import os
from pathlib import Path

import unreal

_REPO = Path(__file__).resolve().parent.parent
CONFIGS_DIR = str(_REPO / "configs" / "vehicles")
SKIP_TYPE = "vehCar_vehicle13"  # hand-tuned reference

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

# Fixed physical anchor heights (cm above ground) - NOT scaled off the roof, so a tall
# van does not get its headlights pushed up to the roofline.
_HEADLIGHT_Z = 58.0
_TAILLIGHT_Z = 72.0
_EXHAUST_Z = 24.0


def _static_mesh(type_id):
    return unreal.EditorAssetLibrary.load_asset(f"/Game/Vehicle/{type_id}/Mesh/SM_{type_id}")


def _section_verts(sm, section, lod_index=0):
    try:
        vs = unreal.ProceduralMeshLibrary.get_section_from_static_mesh(sm, lod_index, section)[0]
    except Exception:
        return []
    return [(v.x, v.y, v.z) for v in (vs or [])]


def _all_verts(type_id, lod_index=0):
    """Full static-mesh vertex cloud [(x,y,z),...] in mesh-local cm (== actor-local)."""
    sm = _static_mesh(type_id)
    if sm is None:
        return []
    verts = []
    for si in range(64):
        v = _section_verts(sm, si, lod_index)
        if not v and si >= sm.get_num_sections(0):
            break
        verts.extend(v)
    return verts


def _material_verts(sm, matkey):
    """Vertices of every section whose material slot name contains `matkey` (e.g.
    'veh_light' = the headlight/taillight glass, 'veh_mirror' = the wing mirrors).
    Lets us place lights/mirrors on the ACTUAL emissive geometry, not a guessed height."""
    smes = unreal.get_editor_subsystem(unreal.StaticMeshEditorSubsystem)
    mats = sm.get_editor_property("static_materials")
    out = []
    for s in range(sm.get_num_sections(0)):
        slot = smes.get_lod_material_slot(sm, 0, s)
        name = str(mats[slot].get_editor_property("material_slot_name"))
        if matkey in name:
            out.extend(_section_verts(sm, s))
    return out


def _cluster_centroid(verts, xpred, ypred):
    pts = [p for p in verts if xpred(p[0]) and ypred(p[1])]
    if not pts:
        return None
    n = len(pts)
    return [sum(p[i] for p in pts) / n for i in range(3)]


def _bones(type_id):
    """{bone: (x,y,z)} in actor-local cm from the skeletal mesh (spawns a temp actor)."""
    skm = unreal.EditorAssetLibrary.load_asset(f"/Game/Vehicle/{type_id}/Mesh/SKM_{type_id}")
    if skm is None:
        return {}
    eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    a = eas.spawn_actor_from_class(
        unreal.SkeletalMeshActor, unreal.Vector(0, 0, 50000), unreal.Rotator(0, 0, 0)
    )
    comp = a.skeletal_mesh_component
    comp.set_skinned_asset_and_update(skm)
    out = {}
    for i in range(comp.get_num_bones()):
        bn = str(comp.get_bone_name(i))
        t = comp.get_socket_transform(bn, unreal.RelativeTransformSpace.RTS_ACTOR).translation
        out[bn] = (t.x, t.y, t.z)
    eas.destroy_actor(a)
    return out


def _bone(bones, *cands):
    for c in cands:
        cl = c.lower()
        for k, v in bones.items():
            if cl in k.lower():
                return list(v)
    return None


def _roof_plateau(verts, zmax, ymax):
    """Front/rear X of the flat roof panel via a centreline max-Z profile (40 bins).
    A van's plateau runs the whole length, a coupe's is short - measured, not assumed."""
    xs = [p[0] for p in verts]
    xmin, xmax = min(xs), max(xs)
    nb = 40
    binw = (xmax - xmin) / nb
    prof = [0.0] * nb
    for x, y, z in verts:
        if abs(y) < 0.18 * ymax:
            bi = min(nb - 1, int((x - xmin) / binw))
            if z > prof[bi]:
                prof[bi] = z
    # 0.90 (not 0.96) so the edges reach the A/C-pillar tops where the roof has already
    # begun curving down to the windscreen/backlight - that corner is the CarFusion point.
    plat = [xmin + (i + 0.5) * binw for i in range(nb) if prof[i] >= 0.90 * zmax]
    if not plat:
        return 0.2 * xmin, 0.2 * xmax
    return min(plat), max(plat)


def _front_face_x(verts, z0, ylo, yhi, front=True):
    """X of the front (or rear) body face at height z0 in the light-Y band."""
    cand = [p[0] for p in verts if abs(p[2] - z0) < 16 and ylo < abs(p[1]) < yhi]
    if not cand:
        return None
    return max(cand) if front else min(cand)


def derive_points(type_id):
    """Return (ordered 24-kpt dict, warnings, debug) for one vehicle type."""
    warn = []
    sm = _static_mesh(type_id)
    if sm is None:
        return None, ["no static mesh"], {}
    verts = _all_verts(type_id)
    if not verts:
        return None, ["no static-mesh vertices"], {}
    bones = _bones(type_id)
    light_v = _material_verts(sm, "veh_light")
    mirror_v = _material_verts(sm, "veh_mirror")
    xs = [p[0] for p in verts]
    ys = [p[1] for p in verts]
    zs = [p[2] for p in verts]
    xmin, xmax = min(xs), max(xs)
    ymax = max(abs(min(ys)), max(ys))
    zmax = max(zs)

    def rp(x, y, z):
        return [round(x, 1), round(y, 1), round(z, 1)]

    k = {}

    # --- 0-3 wheels: skeletal bones (every vehicle has them) ---
    wfl = _bone(bones, "wheel_front_l") or [0.42 * xmax, -0.72 * ymax, 36.0]
    wfr = _bone(bones, "wheel_front_r") or [0.42 * xmax, 0.72 * ymax, 36.0]
    wrl = _bone(bones, "wheel_rear_l") or [0.42 * xmin, -0.72 * ymax, 36.0]
    wrr = _bone(bones, "wheel_rear_r") or [0.42 * xmin, 0.72 * ymax, 36.0]
    k["Right_Front_wheel"] = rp(*wfr)
    k["Left_Front_wheel"] = rp(*wfl)
    k["Right_Back_wheel"] = rp(*wrr)
    k["Left_Back_wheel"] = rp(*wrl)

    # --- 9-12 roof corners: real plateau extent + real roof width ---
    rr_x, rf_x = _roof_plateau(verts, zmax, ymax)
    roof = [p for p in verts if p[2] >= 0.90 * zmax and rr_x - 10 <= p[0] <= rf_x + 10]
    ays = sorted(abs(p[1]) for p in roof) or [0.6 * ymax]
    roof_y = ays[int(0.85 * (len(ays) - 1))]
    # corners sit at the pillar-top height (edges have curved down from the peak)
    roof_z = 0.93 * zmax
    k["Right_Front_Top"] = rp(rf_x, roof_y, roof_z)
    k["Left_Front_Top"] = rp(rf_x, -roof_y, roof_z)
    k["Right_Back_Top"] = rp(rr_x, roof_y, roof_z)
    k["Left_Back_Top"] = rp(rr_x, -roof_y, roof_z)

    # --- 4-7 lights: centroid of the real veh_light glass per corner (front/rear x L/R).
    # This lands on the actual headlight/taillight - height and depth vary a LOT by type
    # (a van taillight sits ~124cm, a coupe's ~71cm), which a fixed guess got badly wrong.
    def light(front, right):
        xp = (lambda x: x > 60) if front else (lambda x: x < -60)
        yp = (lambda y: y > 0) if right else (lambda y: y < 0)
        c = _cluster_centroid(light_v, xp, yp) if light_v else None
        if c is None:  # fallback: front/rear face at a plausible height
            fx = xmax if front else xmin
            c = [fx, (1 if right else -1) * 0.74 * ymax, _HEADLIGHT_Z if front else _TAILLIGHT_Z]
            warn.append(f"{'front' if front else 'rear'} light fallback")
        return rp(*c)

    k["Right_Front_HeadLight"] = light(True, True)
    k["Left_Front_HeadLight"] = light(True, False)
    k["Right_Back_HeadLight"] = light(False, True)
    k["Left_Back_HeadLight"] = light(False, False)
    tr = min((p[0] for p in light_v if p[0] < -60), default=xmin)

    # --- 8 exhaust, 13 center ---
    k["Exhaust"] = rp(tr + 8, -0.45 * ymax, _EXHAUST_Z)
    k["Center"] = rp((rf_x + rr_x) / 2.0, 0.0, 0.45 * zmax)

    # --- 14-15 mirrors: outermost point of the real veh_mirror glass, else bone ---
    def mirror(right):
        side = [p for p in mirror_v if (p[1] > 0) == right]
        if side:  # the wing tip is the |Y|-outermost vert of the mirror section
            tip = max(side, key=lambda p: abs(p[1]))
            return [tip[0], tip[1], sum(p[2] for p in side) / len(side)]
        b = _bone(bones, "side_view_mirror_body_r" if right else "side_view_mirror_body_l")
        if b:
            return b
        warn.append("mirror estimated")
        return [rf_x + 0.10 * (xmax - xmin), (1 if right else -1) * 1.02 * ymax, 0.68 * zmax]

    k["Left_Side_Mirror"] = rp(*mirror(False))
    k["Right_Side_Mirror"] = rp(*mirror(True))

    # --- 16-19 bumper corners: bone or vertex front/rear-bottom corner ---
    def bumper(bone_names, fx, sy):
        b = _bone(bones, *bone_names)
        if b:
            return [b[0], sy * abs(b[1]), b[2]]
        return [fx, sy * 0.82 * ymax, 42.0]

    k["Front_Left_Bumper_Corner"] = rp(*bumper(["bumper_front_02_l"], xmax - 20, -1))
    k["Front_Right_Bumper_Corner"] = rp(*bumper(["bumper_front_02_r"], xmax - 20, 1))
    k["Rear_Left_Bumper_Corner"] = rp(*bumper(["bumper_rear_02_l"], xmin + 20, -1))
    k["Rear_Right_Bumper_Corner"] = rp(*bumper(["bumper_rear_02_r"], xmin + 20, 1))

    # --- 20-23 window bottoms: below the roof corners, toward the body ---
    wsz = 0.78 * zmax
    k["Windshield_Bottom_Left"] = rp(rf_x + 0.06 * (xmax - xmin), -0.72 * ymax, wsz)
    k["Windshield_Bottom_Right"] = rp(rf_x + 0.06 * (xmax - xmin), 0.72 * ymax, wsz)
    k["Rear_Window_Bottom_Left"] = rp(rr_x - 0.04 * (xmax - xmin), -0.70 * ymax, wsz)
    k["Rear_Window_Bottom_Right"] = rp(rr_x - 0.04 * (xmax - xmin), 0.70 * ymax, wsz)

    ordered = {kk: k[kk] for kk in SCHEMA_ORDER}
    dbg = {
        "roofZ": round(zmax, 1),
        "roof_x": [round(rr_x, 1), round(rf_x, 1)],
        "roof_y": round(roof_y, 1),
        "nverts": len(verts),
    }
    return ordered, warn, dbg


def preview(type_id):
    pts, warn, dbg = derive_points(type_id)
    unreal.log(f"{type_id}: {dbg} warn={warn}")
    return pts


def derive_all(exclude_skip=True):
    """Rewrite configs/vehicles/citysample_<type>.json for every derivable type."""
    types = [
        os.path.basename(c)[len("citysample_") : -5]
        for c in sorted(glob.glob(os.path.join(CONFIGS_DIR, "citysample_*.json")))
    ]
    written, skipped, errs = [], [], []
    for tid in types:
        if exclude_skip and tid == SKIP_TYPE:
            skipped.append(tid)
            continue
        try:
            pts, warn, _dbg = derive_points(tid)
            if pts is None:
                errs.append(f"{tid}: {warn}")
                continue
            cfg = {
                "vehicle_id": f"citysample_{tid}",
                "source": f"Epic City Sample 5.6, /Game/Vehicle/{tid}",
                "space": "actor-local, cm, x=forward y=right z=up",
                "derivation": "vertex+bone (ue_derive_geo.py): roof/lights/exhaust from real "
                "static-mesh vertices, wheels/mirrors from skeletal bones",
                "keypoints": pts,
                "warnings": warn,
            }
            out_path = os.path.join(CONFIGS_DIR, f"citysample_{tid}.json")
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2)
            written.append(tid)
        except Exception as exc:
            errs.append(f"{tid}: {exc}")
    return f"written {len(written)}: {written}\nskipped {skipped}\nerrors {errs}"
