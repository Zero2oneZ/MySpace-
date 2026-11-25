#!/usr/bin/env python3
# ============================================================================
# AGENT CARD
# ----------------------------------------------------------------------------
# name:        mocap_rig_anchor
# role:        SUBSTRATE - MOCAP_RIG_ANCHOR_ALIGNMENT_VERIFIER
# tier:        L0
# substrate:   the alignment crystal that joins one captured MocapFrame to a
#              bind-pose rig skeleton AND to the XR spatial anchors that root
#              the scene in physical space. The third leg of the avatar tripod
#              (frame -> rig -> world).
# engine:      deterministic stdlib (math + hashlib + json + dataclasses)
# storage:     none directly - the AlignmentResult.alignment_crystal lands on
#              whatever chain the caller appends to.
# ----------------------------------------------------------------------------
# WHY THIS MODULE
# ----------------------------------------------------------------------------
# A MocapFrame by itself is just a bag of joints. Before any avatar can be
# driven from it we need three properties to all hold simultaneously:
#
#   1. JOINT TOPOLOGY MATCH - the frame's joints are drawn from the canonical
#      Meta Body vocabulary (META_BODY_JOINTS). If a frame contains alien
#      joint names we cannot fit it to any rig.
#
#   2. RIG FIT - the joints that the frame mentions must also exist in the
#      target rig's bind pose AT ROUGHLY THE SAME POSITIONS. A frame that
#      thinks the hips are 10m to the left of where the rig's hips rest
#      cannot drive that rig sanely; some other transform is wrong.
#
#   3. ANCHOR PROXIMITY - the frame must declare which XR_FB_spatial_entity
#      anchors it considers itself parented to (the "particles we placed
#      long ago" in spatial_anchor.py vocabulary). The hips world-space
#      position must lie within tolerance of at least one of those anchors.
#      That is what binds the captured motion to the physical room.
#
# All three must hold; failing any one leaves the avatar floating, wrong, or
# unparented. The verify_alignment() chain returns an AlignmentResult whose
# .ok bit is true only when all three pass, and whose .alignment_crystal is
# a deterministic blake2b-256 hash of the joined (rig | anchors | frame
# joints) tuple - same inputs always produce the same crystal, which means
# the result can be re-anchored in the broader chain alongside the other
# dimension_pack crystals.
#
# ----------------------------------------------------------------------------
# JOINS THE EXISTING SIGNATURE CHAIN
# ----------------------------------------------------------------------------
# alignment_crystal sits alongside the 5-tuple pattern in dimension_pack:
#   - vector_hex_64     -> the frame's hash already feeds the vector axis
#   - circle_motif_id   -> "alignment" closes a tiny 3-step cycle:
#                          frame -> rig -> anchor -> frame
#   - crystal_hex       -> THIS module emits its own crystal; same shape
#   - rgba              -> tier="alignment" cost="deterministic" sub="INFERENCE"
#   - frame_pack         -> the caller stamps the FPS pack
# ============================================================================
"""mocap_rig_anchor.py - the frame/rig/anchor alignment verifier.

Pure stdlib. Pure math. No numpy, no scipy. Same inputs -> same crystal.

Public API:
    verify_alignment(frame, rig_skeleton, spatial_anchors, tolerance_m=0.5)
        -> AlignmentResult
    align_pose_to_rig(frame, rig_skeleton)
        -> dict[joint_name, JointPose]   (hips snapped to rig origin)
    compute_skeleton_signature(rig_skeleton)
        -> str  (deterministic ID of the rig's joint name set)

CLI:
    verify <frame.json> <rig.json> [--anchors anchors.json] [--tolerance 0.5]
    smoke  - run a synthetic Mixamo-ish rig + synthetic anchors end-to-end
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Substrate imports - mocap_frame is the joint vocabulary; spatial_anchor is
# read for type compatibility only (we receive (x,y,z) tuples directly to keep
# this module stdlib-pure and decoupled from the sensor classes).
_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

from mocap_frame import (  # type: ignore
    META_BODY_JOINTS,
    MocapFrame,
    JointPose,
)


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class AlignmentResult:
    """The verdict of a frame/rig/anchor alignment check.

    Fields:
      ok:                            all three legs of the tripod passed
      alignment_crystal:             blake2b-256 over (rig | anchors | joints)
      reasons:                       human-readable failures (empty on ok)
      hip_to_anchor_distance:        meters to nearest referenced anchor
                                       (inf if no overlap, 0 if no anchors)
      joint_topology_match_pct:      % of canonical META_BODY_JOINTS present
      rig_fit_pct:                   % of overlapping joints that fit within
                                       tolerance of the rig's bind pose
      skeleton_signature:            deterministic ID for the rig's joint set
      verified_anchor_count:         how many of frame.anchor_uuids were
                                       resolved against spatial_anchors
    """
    ok: bool
    alignment_crystal: str
    reasons: List[str] = field(default_factory=list)
    hip_to_anchor_distance: float = float("inf")
    joint_topology_match_pct: float = 0.0
    rig_fit_pct: float = 0.0
    skeleton_signature: str = ""
    verified_anchor_count: int = 0

    def to_dict(self) -> Dict:
        d = asdict(self)
        # JSON cannot serialize math.inf; we map it to the string "Infinity"
        # which round-trips correctly via json.loads with parse_constant.
        if math.isinf(d["hip_to_anchor_distance"]):
            d["hip_to_anchor_distance"] = "Infinity"
        return d


# ---------------------------------------------------------------------------
# Math helpers (stdlib only)
# ---------------------------------------------------------------------------

def _euclid(a: Tuple[float, float, float],
             b: Tuple[float, float, float]) -> float:
    """3D Euclidean distance in meters."""
    return math.sqrt((a[0] - b[0]) ** 2 +
                      (a[1] - b[1]) ** 2 +
                      (a[2] - b[2]) ** 2)


def _xyz(pose) -> Tuple[float, float, float]:
    """Strip a JointPose 7-tuple or a 3-tuple down to position only."""
    return (float(pose[0]), float(pose[1]), float(pose[2]))


# ---------------------------------------------------------------------------
# Skeleton signature - a deterministic ID for "which rig is this"
# ---------------------------------------------------------------------------

def compute_skeleton_signature(rig_skeleton: Dict[str, Tuple[float, float, float]]
                                  ) -> str:
    """Return a 32-char blake2b digest of the rig's joint NAME SET.

    Two rigs with the same set of joint names produce the same signature even
    if their bind-pose positions differ slightly - this is intentional, because
    "this is a Meta Body 22-joint rig" is a structural fact independent of
    centimeter offsets. Use the alignment_crystal (which DOES fold in the
    positions) when you want full identity.
    """
    names = sorted(rig_skeleton.keys())
    canonical = json.dumps(names, separators=(",", ":"), ensure_ascii=True)
    return hashlib.blake2b(canonical.encode("utf-8"),
                              digest_size=16).hexdigest()


# ---------------------------------------------------------------------------
# align_pose_to_rig - translate the frame so Hips meet the rig's bind Hips
# ---------------------------------------------------------------------------

def align_pose_to_rig(frame: MocapFrame,
                       rig_skeleton: Dict[str, Tuple[float, float, float]]
                       ) -> Dict[str, JointPose]:
    """Translate every joint in `frame` so the frame's Hips land on the rig's
    bind-pose Hips. Pure translation; rotations are not changed.

    Why this matters: a captured frame's Hips may sit at (1.4, 0.97, 2.1)
    because that is where the user was physically standing. To drive an
    avatar the joint positions must be expressed in rig-LOCAL coordinates
    where Hips sit at the rig's bind origin (often (0, 0, 0)).

    If either side lacks a Hips joint the function returns the frame's joints
    unchanged - upstream verify_alignment() will flag the topology failure.
    """
    if "Hips" not in frame.joints or "Hips" not in rig_skeleton:
        return dict(frame.joints)
    fhx, fhy, fhz = _xyz(frame.joints["Hips"])
    rhx, rhy, rhz = rig_skeleton["Hips"][0], rig_skeleton["Hips"][1], rig_skeleton["Hips"][2]
    dx, dy, dz = rhx - fhx, rhy - fhy, rhz - fhz
    aligned: Dict[str, JointPose] = {}
    for name, pose in frame.joints.items():
        if len(pose) == 7:
            aligned[name] = (
                pose[0] + dx, pose[1] + dy, pose[2] + dz,
                pose[3], pose[4], pose[5], pose[6],
            )
        else:  # length-3 fallback (shouldn't normally hit; mocap_frame pads)
            x, y, z = _xyz(pose)
            aligned[name] = (x + dx, y + dy, z + dz, 0.0, 0.0, 0.0, 1.0)
    return aligned


# ---------------------------------------------------------------------------
# verify_alignment - the three-leg check
# ---------------------------------------------------------------------------

def verify_alignment(frame: MocapFrame,
                       rig_skeleton: Dict[str, Tuple[float, float, float]],
                       spatial_anchors: Dict[str, Tuple[float, float, float]],
                       tolerance_m: float = 0.5
                       ) -> AlignmentResult:
    """The check.

    Tolerance defaults to 0.5 m - this is the Meta XR body-tracking SDK's
    documented absolute drift bound under good lighting. Tighten for
    seated-pose work, loosen for whole-room walking.
    """
    reasons: List[str] = []

    # ---- Leg 1: joint topology match -------------------------------------
    # Every joint name in frame.joints must be canonical (drawn from
    # META_BODY_JOINTS). Sources are supposed to have already been remapped
    # by mocap_frame.remap_joints() before we see them.
    canonical_set = set(META_BODY_JOINTS)
    frame_joint_names = set(frame.joints.keys())
    non_canonical = frame_joint_names - canonical_set
    if non_canonical:
        reasons.append(
            f"non-canonical joints in frame: {sorted(non_canonical)[:5]} "
            f"(total {len(non_canonical)})"
        )
    canonical_present = frame_joint_names & canonical_set
    topology_pct = (100.0 * len(canonical_present) / len(canonical_set)
                      if canonical_set else 0.0)
    if topology_pct < 50.0:
        reasons.append(
            f"joint topology coverage {topology_pct:.1f}% < 50% "
            f"({len(canonical_present)}/{len(canonical_set)} canonical joints)"
        )

    # ---- Leg 2: rig fit ---------------------------------------------------
    # For joints present in BOTH the frame AND the rig skeleton, the
    # distance between frame.joint and rig.joint should be < tolerance_m.
    # The frame is captured in WORLD coordinates while the rig sits in its
    # own LOCAL bind-pose frame, so we run align_pose_to_rig() first to
    # translate the frame's joints into rig-local space (snapping the frame's
    # Hips onto the rig's Hips). Rig fit is then a meaningful per-joint
    # offset comparison. If the rig lacks a joint the frame mentions, that
    # joint is excluded from the overlap set.
    rig_joint_names = set(rig_skeleton.keys())
    overlap = canonical_present & rig_joint_names
    aligned_joints = align_pose_to_rig(frame, rig_skeleton)
    fits = 0
    misfits: List[Tuple[str, float]] = []
    if overlap:
        for name in overlap:
            d = _euclid(_xyz(aligned_joints[name]),
                         (rig_skeleton[name][0], rig_skeleton[name][1],
                          rig_skeleton[name][2]))
            if d < tolerance_m:
                fits += 1
            else:
                misfits.append((name, d))
        rig_fit_pct = 100.0 * fits / len(overlap)
    else:
        rig_fit_pct = 0.0
        reasons.append("no joint name overlap between frame and rig skeleton")

    if overlap and rig_fit_pct < 80.0:
        # Report the worst offenders to make the failure debuggable
        misfits.sort(key=lambda kv: -kv[1])
        worst = ", ".join(f"{n} ({d:.2f}m)" for n, d in misfits[:3])
        reasons.append(
            f"rig fit {rig_fit_pct:.1f}% < 80% "
            f"({fits}/{len(overlap)} within {tolerance_m}m); worst: {worst}"
        )

    # ---- Leg 3: anchor proximity ------------------------------------------
    # frame.anchor_uuids must reference at least one anchor whose position
    # is registered in spatial_anchors. The Hips world-space position must
    # then sit within tolerance_m of at least one of those.
    verified_anchors: List[Tuple[str, Tuple[float, float, float]]] = []
    for u in frame.anchor_uuids:
        key = u.strip().lower()
        if key in spatial_anchors:
            verified_anchors.append((key, spatial_anchors[key]))
        elif u in spatial_anchors:  # case-sensitive fallback
            verified_anchors.append((u, spatial_anchors[u]))

    if not frame.anchor_uuids:
        reasons.append("frame has no anchor_uuids - cannot bind to space")
        hip_dist = float("inf")
    elif not verified_anchors:
        reasons.append(
            f"none of frame's {len(frame.anchor_uuids)} anchor_uuids "
            f"resolve in spatial_anchors map"
        )
        hip_dist = float("inf")
    elif "Hips" not in frame.joints:
        reasons.append("frame lacks Hips joint - cannot anchor in world space")
        hip_dist = float("inf")
    else:
        hips_xyz = _xyz(frame.joints["Hips"])
        # Closest referenced anchor
        hip_dist = min(_euclid(hips_xyz, pos) for _, pos in verified_anchors)
        if hip_dist > tolerance_m:
            reasons.append(
                f"hip-to-anchor distance {hip_dist:.2f}m > tolerance "
                f"{tolerance_m}m (nearest of {len(verified_anchors)} "
                f"referenced anchors)"
            )

    # ---- Crystal: deterministic over rig joint set + anchor positions +
    # ---- frame joint set. Note we use SORTED canonical JSON of each piece,
    # ---- so floats are rounded to 4 dp for stability across machines.
    crystal = _alignment_crystal(rig_skeleton, spatial_anchors, frame.joints)

    return AlignmentResult(
        ok=not reasons,
        alignment_crystal=crystal,
        reasons=reasons,
        hip_to_anchor_distance=hip_dist,
        joint_topology_match_pct=round(topology_pct, 2),
        rig_fit_pct=round(rig_fit_pct, 2),
        skeleton_signature=compute_skeleton_signature(rig_skeleton),
        verified_anchor_count=len(verified_anchors),
    )


# ---------------------------------------------------------------------------
# Alignment crystal - same inputs always produce the same hash
# ---------------------------------------------------------------------------

def _alignment_crystal(rig_skeleton: Dict[str, Tuple[float, float, float]],
                          spatial_anchors: Dict[str, Tuple[float, float, float]],
                          frame_joints: Dict[str, JointPose]) -> str:
    """blake2b-256 over the canonical (rig | anchors | frame_joints) tuple.

    Floats are rounded to 4 dp (0.1 mm) - finer would be noise; coarser would
    let micrometre drift pollute the chain. The same field order and rounding
    is used everywhere so this hash is reproducible bytes-exact.
    """
    rig_canon = {
        name: [round(v[0], 4), round(v[1], 4), round(v[2], 4)]
        for name, v in sorted(rig_skeleton.items())
    }
    anchor_canon = {
        uuid.strip().lower(): [round(p[0], 4), round(p[1], 4), round(p[2], 4)]
        for uuid, p in sorted(spatial_anchors.items())
    }
    joint_canon = {
        name: [round(p[0], 4), round(p[1], 4), round(p[2], 4),
                round(p[3] if len(p) > 3 else 0.0, 4),
                round(p[4] if len(p) > 4 else 0.0, 4),
                round(p[5] if len(p) > 5 else 0.0, 4),
                round(p[6] if len(p) > 6 else 1.0, 4)]
        for name, p in sorted(frame_joints.items())
    }
    payload = {
        "rig": rig_canon,
        "anchors": anchor_canon,
        "joints": joint_canon,
        "schema": "mocap_rig_anchor_v1",
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=True).encode("utf-8")
    return hashlib.blake2b(blob, digest_size=32).hexdigest()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_synthetic_rig() -> Dict[str, Tuple[float, float, float]]:
    """A bind-pose rig in the Meta Body vocabulary, Mixamo-ish proportions.
    Y-up, meters, hips at the origin so the rig's local frame == world frame
    for the smoke test."""
    return {
        "Root":             (0.0, 0.0,  0.0),
        "Hips":             (0.0, 0.95, 0.0),
        "SpineLower":       (0.0, 1.05, 0.0),
        "SpineMiddle":      (0.0, 1.20, 0.0),
        "SpineUpper":       (0.0, 1.35, 0.0),
        "Chest":            (0.0, 1.42, 0.0),
        "Neck":             (0.0, 1.55, 0.0),
        "Head":             (0.0, 1.70, 0.0),
        "LeftShoulder":     (-0.18, 1.50, 0.0),
        "LeftArmUpper":     (-0.28, 1.50, 0.0),
        "LeftArmLower":     (-0.55, 1.50, 0.0),
        "LeftHandWrist":    (-0.78, 1.50, 0.0),
        "RightShoulder":    (0.18, 1.50, 0.0),
        "RightArmUpper":    (0.28, 1.50, 0.0),
        "RightArmLower":    (0.55, 1.50, 0.0),
        "RightHandWrist":   (0.78, 1.50, 0.0),
        "LeftUpperLeg":     (-0.12, 0.95, 0.0),
        "LeftLowerLeg":     (-0.12, 0.50, 0.0),
        "LeftFootAnkle":    (-0.12, 0.08, 0.0),
        "LeftFootBall":     (-0.12, 0.02, 0.10),
        "RightUpperLeg":    (0.12, 0.95, 0.0),
        "RightLowerLeg":    (0.12, 0.50, 0.0),
        "RightFootAnkle":   (0.12, 0.08, 0.0),
        "RightFootBall":    (0.12, 0.02, 0.10),
    }


def _build_synthetic_frame() -> MocapFrame:
    """A captured frame that LOOKS like the bind pose plus a 0.1m wobble.
    Hips set to anchor-A's position so the proximity check passes."""
    rig = _build_synthetic_rig()
    joints: Dict[str, JointPose] = {}
    # Tiny deterministic per-joint jitter so this isn't trivially equal to rig
    jitter = [0.03, -0.02, 0.01, -0.04, 0.02, -0.03, 0.04, -0.01]
    for i, (name, p) in enumerate(rig.items()):
        j = jitter[i % len(jitter)]
        # Offset by anchor-A's world position so the hips land on the anchor
        joints[name] = (p[0] + j + 1.5, p[1] + j + 0.0, p[2] + j + 2.0,
                        0.0, 0.0, 0.0, 1.0)
    # Pin hips closer to anchor-A so leg 3 passes cleanly
    joints["Hips"] = (1.50, 0.95, 2.00, 0.0, 0.0, 0.0, 1.0)
    return MocapFrame(
        ts=1700000000.0,  # deterministic timestamp for the smoke crystal
        source_id="smoke_test",
        capture_method="meta_xr_body",
        joints=joints,
        anchor_uuids=["aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"],
    )


def _build_synthetic_anchors() -> Dict[str, Tuple[float, float, float]]:
    """Two anchors; the frame references only the first."""
    return {
        "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa": (1.5, 0.95, 2.0),
        "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb": (5.0, 0.95, 5.0),
    }


def _cmd_verify(args: argparse.Namespace) -> int:
    frame_d = json.loads(Path(args.frame).read_text(encoding="utf-8"))
    # Rebuild MocapFrame from its dict form
    frame = MocapFrame(
        ts=float(frame_d.get("ts", time.time())),
        source_id=str(frame_d.get("source_id", "cli")),
        capture_method=str(frame_d.get("capture_method", "unknown")),
        joints={k: tuple(v) for k, v in (frame_d.get("joints") or {}).items()},
        face_blendshapes=dict(frame_d.get("face_blendshapes") or {}),
        anchor_uuids=list(frame_d.get("anchor_uuids") or []),
        confidence=dict(frame_d.get("confidence") or {}),
        crystal_anchor=str(frame_d.get("crystal_anchor", "")),
    )
    rig = json.loads(Path(args.rig).read_text(encoding="utf-8"))
    rig = {k: tuple(v) for k, v in rig.items()}
    if args.anchors:
        anchors = json.loads(Path(args.anchors).read_text(encoding="utf-8"))
        anchors = {k: tuple(v) for k, v in anchors.items()}
    else:
        anchors = {}
    result = verify_alignment(frame, rig, anchors, tolerance_m=args.tolerance)
    print(json.dumps(result.to_dict(), indent=2, sort_keys=True))
    return 0 if result.ok else 1


def _cmd_smoke(_args: argparse.Namespace) -> int:
    rig = _build_synthetic_rig()
    frame = _build_synthetic_frame()
    anchors = _build_synthetic_anchors()

    aligned = align_pose_to_rig(frame, rig)
    sig = compute_skeleton_signature(rig)
    result = verify_alignment(frame, rig, anchors, tolerance_m=0.5)

    out = {
        "skeleton_signature":      sig,
        "aligned_hips":             list(aligned["Hips"]),
        "alignment_result":         result.to_dict(),
        "determinism_recheck":      verify_alignment(
                                       frame, rig, anchors, tolerance_m=0.5
                                   ).alignment_crystal,
    }
    out["crystal_stable"] = (
        out["determinism_recheck"] == result.alignment_crystal
    )
    print(json.dumps(out, indent=2, sort_keys=True))
    return 0 if result.ok else 1


def _main() -> int:
    ap = argparse.ArgumentParser(
        prog="mocap_rig_anchor",
        description="frame/rig/anchor alignment verifier",
    )
    sub = ap.add_subparsers(dest="cmd")

    p_v = sub.add_parser("verify", help="verify a frame against a rig + anchors")
    p_v.add_argument("frame", help="path to MocapFrame JSON")
    p_v.add_argument("rig",   help="path to rig_skeleton JSON ({joint:[x,y,z]})")
    p_v.add_argument("--anchors", default=None,
                       help="path to anchors JSON ({uuid:[x,y,z]})")
    p_v.add_argument("--tolerance", type=float, default=0.5,
                       help="tolerance in metres (default 0.5)")
    p_v.set_defaults(func=_cmd_verify)

    p_s = sub.add_parser("smoke", help="synthetic end-to-end smoke test")
    p_s.set_defaults(func=_cmd_smoke)

    args = ap.parse_args()
    if not args.cmd:
        ap.print_help()
        return 2
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(_main())
