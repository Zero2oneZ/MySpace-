"""mocap_frame.py — Canonical MocapFrame substrate for Tom's animation pipeline.

Everything downstream (animation_registry, mocap_rig_anchor, the Snap/Meta/
MediaPipe capture adapters, the avatar workflow card's mocap_verify pass)
speaks this dataclass.

Joint vocabulary: **Meta Body Tracking** (Quest 3 / Ray-Ban Meta / Quest Pro).
  - 22 joints covering upper body + lower body + root + hips
  - Same names Meta's Avatars SDK GLB rigs use
  - Subset (the upper-body 17) works on Ray-Ban Meta without lower-body
    tracking

Face vocabulary: **ARKit 52 blend shapes**. Meta Face Tracking SDK,
Snap Lens FaceTrack, and MediaPipe Face Mesh all normalize to these so the
same MocapFrame.face_blendshapes is portable.

Spatial anchors: `XR_FB_spatial_entity` UUIDs — the OpenXR Meta extension's
spatial-entity UUID format. The same UUIDs `meta_xr_bridge.gd` exposes.

This module is **stdlib only**. No numpy, no transforms3d, no quaternions
beyond a 4-tuple. Cheap to copy across processes.
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional, Tuple


# ============================================================================
# Meta Body Tracking joint vocabulary
# ============================================================================
# 22-joint full-body skeleton; reduce to first 17 for upper-body-only headsets.
# Order matters: same as Meta XR SDK's XR_FB_body_tracking joint indexing.

META_BODY_JOINTS: Tuple[str, ...] = (
    # Spine chain
    "Root",
    "Hips",
    "SpineLower",
    "SpineMiddle",
    "SpineUpper",
    "Chest",
    "Neck",
    "Head",
    # Left arm
    "LeftShoulder",
    "LeftArmUpper",
    "LeftArmLower",
    "LeftHandWrist",
    # Right arm
    "RightShoulder",
    "RightArmUpper",
    "RightArmLower",
    "RightHandWrist",
    # Left leg
    "LeftUpperLeg",
    "LeftLowerLeg",
    "LeftFootAnkle",
    "LeftFootBall",
    # Right leg
    "RightUpperLeg",
    "RightLowerLeg",
    "RightFootAnkle",
    "RightFootBall",
)

UPPER_BODY_JOINTS: Tuple[str, ...] = META_BODY_JOINTS[:16]


# ============================================================================
# ARKit blend shape vocabulary (Meta Face Tracking SDK normalizes to these)
# ============================================================================

ARKIT_BLENDSHAPES: Tuple[str, ...] = (
    # Brow (5)
    "browDownLeft", "browDownRight", "browInnerUp",
    "browOuterUpLeft", "browOuterUpRight",
    # Cheek (3)
    "cheekPuff", "cheekSquintLeft", "cheekSquintRight",
    # Eye (14)
    "eyeBlinkLeft", "eyeBlinkRight",
    "eyeLookDownLeft", "eyeLookDownRight",
    "eyeLookInLeft", "eyeLookInRight",
    "eyeLookOutLeft", "eyeLookOutRight",
    "eyeLookUpLeft", "eyeLookUpRight",
    "eyeSquintLeft", "eyeSquintRight",
    "eyeWideLeft", "eyeWideRight",
    # Jaw (4)
    "jawForward", "jawLeft", "jawOpen", "jawRight",
    # Mouth (23)
    "mouthClose", "mouthDimpleLeft", "mouthDimpleRight",
    "mouthFrownLeft", "mouthFrownRight",
    "mouthFunnel",
    "mouthLeft", "mouthLowerDownLeft", "mouthLowerDownRight",
    "mouthPressLeft", "mouthPressRight",
    "mouthPucker",
    "mouthRight", "mouthRollLower", "mouthRollUpper",
    "mouthShrugLower", "mouthShrugUpper",
    "mouthSmileLeft", "mouthSmileRight",
    "mouthStretchLeft", "mouthStretchRight",
    "mouthUpperUpLeft", "mouthUpperUpRight",
    # Nose (2)
    "noseSneerLeft", "noseSneerRight",
    # Tongue (1)
    "tongueOut",
)
assert len(ARKIT_BLENDSHAPES) == 52, len(ARKIT_BLENDSHAPES)


# ============================================================================
# Remap dicts — adapter inputs in non-canonical naming → Meta Body joint name
# ============================================================================

# Mixamo's mixamorig:Bone naming (the FBX armatures Tom has in studio/media/).
MIXAMO_TO_META_BODY: Dict[str, str] = {
    "mixamorig:Hips": "Hips",
    "mixamorig:Spine": "SpineLower",
    "mixamorig:Spine1": "SpineMiddle",
    "mixamorig:Spine2": "SpineUpper",
    "mixamorig:Neck": "Neck",
    "mixamorig:Head": "Head",
    "mixamorig:LeftShoulder": "LeftShoulder",
    "mixamorig:LeftArm": "LeftArmUpper",
    "mixamorig:LeftForeArm": "LeftArmLower",
    "mixamorig:LeftHand": "LeftHandWrist",
    "mixamorig:RightShoulder": "RightShoulder",
    "mixamorig:RightArm": "RightArmUpper",
    "mixamorig:RightForeArm": "RightArmLower",
    "mixamorig:RightHand": "RightHandWrist",
    "mixamorig:LeftUpLeg": "LeftUpperLeg",
    "mixamorig:LeftLeg": "LeftLowerLeg",
    "mixamorig:LeftFoot": "LeftFootAnkle",
    "mixamorig:LeftToeBase": "LeftFootBall",
    "mixamorig:RightUpLeg": "RightUpperLeg",
    "mixamorig:RightLeg": "RightLowerLeg",
    "mixamorig:RightFoot": "RightFootAnkle",
    "mixamorig:RightToeBase": "RightFootBall",
}

# Snap Camera Kit BodyTrack joint names (their Lens runtime exposes a
# simplified set; the rest of the joints will be missing on Snap-only frames).
SNAP_BODYTRACK_TO_META_BODY: Dict[str, str] = {
    "pelvis": "Hips",
    "spine": "SpineLower",
    "chest": "Chest",
    "neck": "Neck",
    "head": "Head",
    "leftShoulder": "LeftShoulder",
    "leftElbow": "LeftArmLower",
    "leftWrist": "LeftHandWrist",
    "rightShoulder": "RightShoulder",
    "rightElbow": "RightArmLower",
    "rightWrist": "RightHandWrist",
    "leftHip": "LeftUpperLeg",
    "leftKnee": "LeftLowerLeg",
    "leftAnkle": "LeftFootAnkle",
    "rightHip": "RightUpperLeg",
    "rightKnee": "RightLowerLeg",
    "rightAnkle": "RightFootAnkle",
}

# MediaPipe Holistic pose landmarks — 33 indexed positions; we map only the
# ones that have Meta Body equivalents.
MEDIAPIPE_POSE_TO_META_BODY: Dict[int, str] = {
    11: "LeftShoulder",
    12: "RightShoulder",
    13: "LeftArmLower",  # MediaPipe elbow → Meta body's lower-arm joint
    14: "RightArmLower",
    15: "LeftHandWrist",
    16: "RightHandWrist",
    23: "LeftUpperLeg",
    24: "RightUpperLeg",
    25: "LeftLowerLeg",
    26: "RightLowerLeg",
    27: "LeftFootAnkle",
    28: "RightFootAnkle",
    31: "LeftFootBall",
    32: "RightFootBall",
    # 0 (nose) maps to Head approximately
    0: "Head",
}

REMAPS: Dict[str, Dict] = {
    "mixamo": MIXAMO_TO_META_BODY,
    "snap_bodytrack": SNAP_BODYTRACK_TO_META_BODY,
    "mediapipe_pose": MEDIAPIPE_POSE_TO_META_BODY,
    # meta_xr_body: identity (the SDK already speaks Meta Body)
}


# ============================================================================
# Dataclasses
# ============================================================================

# A joint pose: position (m) + optional rotation as a quaternion (x,y,z,w).
JointPose = Tuple[float, float, float, float, float, float, float]


@dataclass
class MocapFrame:
    """One captured frame from any mocap source, normalized to Meta Body
    joints + ARKit blend shapes.

    Fields:
      ts:                wall-clock seconds (UTC)
      source_id:         registry source identifier (e.g., "snap_lens_default")
      capture_method:    "meta_xr_body" | "snap_lens_bodytrack" |
                          "mediapipe_holistic" | "mixamo_fbx_clip" | ...
      joints:            {meta_joint_name → (x, y, z, qx, qy, qz, qw)} —
                          translation in metres world-space; quaternion is
                          identity if the source doesn't provide rotation
      face_blendshapes:  {arkit_name → 0..1}
      anchor_uuids:      list of XR_FB_spatial_entity UUIDs the frame is
                          aligned against (the "particles we placed long ago")
      confidence:        per-joint 0..1 (sparse — only joints the source
                          tracked confidently are recorded; missing = unknown)
      crystal_anchor:    optional InferenceLogger crystal (set by the
                          animation_registry when the frame lands)
    """
    ts: float
    source_id: str
    capture_method: str
    joints: Dict[str, JointPose] = field(default_factory=dict)
    face_blendshapes: Dict[str, float] = field(default_factory=dict)
    anchor_uuids: List[str] = field(default_factory=list)
    confidence: Dict[str, float] = field(default_factory=dict)
    crystal_anchor: str = ""

    def to_dict(self) -> Dict:
        return asdict(self)

    def canonical_json(self) -> str:
        """Stable serialization for hashing (excludes crystal_anchor)."""
        d = self.to_dict()
        d.pop("crystal_anchor", None)
        return json.dumps(d, sort_keys=True, separators=(",", ":"),
                            ensure_ascii=True)

    def frame_hash(self) -> str:
        """Deterministic blake2b-256 of the canonical form. Same frame →
        same hash → same crystal."""
        return hashlib.blake2b(self.canonical_json().encode(),
                                 digest_size=32).hexdigest()


# ============================================================================
# Remap helpers
# ============================================================================

def remap_joints(raw: Dict, mapping_kind: str) -> Dict[str, JointPose]:
    """Convert source-specific joint names/indices into canonical Meta Body
    joint names. raw values may be (x,y,z), (x,y,z,qx,qy,qz,qw), or other; we
    pad with identity quat if needed.

    mapping_kind ∈ REMAPS keys, OR 'meta_xr_body' which means identity.
    Unknown source keys are silently dropped (sparse handling is the contract).
    """
    if mapping_kind == "meta_xr_body":
        return {k: _normalize_pose(v) for k, v in raw.items()
                if k in META_BODY_JOINTS}
    table = REMAPS.get(mapping_kind)
    if table is None:
        raise ValueError(f"unknown mapping_kind: {mapping_kind}; "
                         f"expected one of {list(REMAPS) + ['meta_xr_body']}")
    out: Dict[str, JointPose] = {}
    for src_key, pose in raw.items():
        # MediaPipe uses ints; Mixamo/Snap use strs
        meta_name = table.get(src_key)
        if meta_name is None:
            continue
        out[meta_name] = _normalize_pose(pose)
    return out


def _normalize_pose(v) -> JointPose:
    """Pad a position-only tuple to position+identity-quat. Accepts list or
    tuple of length 3 or 7."""
    if len(v) == 3:
        return (float(v[0]), float(v[1]), float(v[2]), 0.0, 0.0, 0.0, 1.0)
    if len(v) == 7:
        return tuple(float(x) for x in v)  # type: ignore
    raise ValueError(f"joint pose must be length 3 or 7, got {len(v)}")


# ============================================================================
# XR_FB_spatial_entity UUID helpers
# ============================================================================

def is_valid_xr_anchor_uuid(s: str) -> bool:
    """Meta's spatial-entity UUID is the standard RFC 4122 form: 8-4-4-4-12
    hex characters. Be lenient: accept any 32-hex-char form too (some Meta
    runtimes emit without dashes)."""
    if not isinstance(s, str):
        return False
    s = s.strip().lower()
    if len(s) == 36 and s[8] == s[13] == s[18] == s[23] == "-":
        body = s.replace("-", "")
    elif len(s) == 32:
        body = s
    else:
        return False
    return all(c in "0123456789abcdef" for c in body)


# ============================================================================
# Convenience constructors
# ============================================================================

def empty_frame(source_id: str, capture_method: str = "unknown",
                 ts: Optional[float] = None) -> MocapFrame:
    return MocapFrame(
        ts=ts if ts is not None else time.time(),
        source_id=source_id,
        capture_method=capture_method,
    )


def frame_from_raw(raw: Dict, *, source_id: str, capture_method: str,
                    mapping_kind: str = "meta_xr_body",
                    anchor_uuids: Optional[List[str]] = None,
                    face_blendshapes: Optional[Dict[str, float]] = None,
                    confidence: Optional[Dict[str, float]] = None,
                    ts: Optional[float] = None) -> MocapFrame:
    """Build a normalized MocapFrame from a raw source dict in one call.
    Convenience wrapper that handles joint remap + validates anchor UUIDs."""
    joints = remap_joints(raw, mapping_kind)
    anchors = []
    for u in (anchor_uuids or []):
        if is_valid_xr_anchor_uuid(u):
            anchors.append(u.strip().lower())
    fb = {}
    for k, v in (face_blendshapes or {}).items():
        if k in ARKIT_BLENDSHAPES:
            fb[k] = max(0.0, min(1.0, float(v)))
    return MocapFrame(
        ts=ts if ts is not None else time.time(),
        source_id=source_id,
        capture_method=capture_method,
        joints=joints,
        face_blendshapes=fb,
        anchor_uuids=anchors,
        confidence=dict(confidence or {}),
    )


# ============================================================================
# CLI sanity check
# ============================================================================

def _self_test() -> None:
    print(f"META_BODY_JOINTS = {len(META_BODY_JOINTS)} ({META_BODY_JOINTS[0]} .. {META_BODY_JOINTS[-1]})")
    print(f"ARKIT_BLENDSHAPES = {len(ARKIT_BLENDSHAPES)}")
    print(f"MIXAMO_TO_META_BODY entries = {len(MIXAMO_TO_META_BODY)}")
    print(f"SNAP_BODYTRACK_TO_META_BODY entries = {len(SNAP_BODYTRACK_TO_META_BODY)}")
    print(f"MEDIAPIPE_POSE_TO_META_BODY entries = {len(MEDIAPIPE_POSE_TO_META_BODY)}")
    # frame_from_raw smoke
    raw = {
        "mixamorig:Hips": (0.0, 1.0, 0.0),
        "mixamorig:Head": (0.0, 1.7, 0.0),
        "mixamorig:LeftHand": (-0.5, 1.2, 0.0),
    }
    f = frame_from_raw(raw, source_id="test", capture_method="mixamo_fbx_clip",
                        mapping_kind="mixamo",
                        anchor_uuids=["0123456789abcdef0123456789abcdef"],
                        face_blendshapes={"jawOpen": 0.4, "eyeBlinkLeft": 1.0})
    print(f"\nframe joints (Meta Body names): {sorted(f.joints)}")
    print(f"frame face: {f.face_blendshapes}")
    print(f"frame anchors: {f.anchor_uuids}")
    print(f"frame_hash:    {f.frame_hash()}")
    # Idempotency check
    f2 = frame_from_raw(raw, source_id="test", capture_method="mixamo_fbx_clip",
                         mapping_kind="mixamo",
                         anchor_uuids=["0123456789abcdef0123456789abcdef"],
                         face_blendshapes={"jawOpen": 0.4, "eyeBlinkLeft": 1.0},
                         ts=f.ts)
    assert f2.frame_hash() == f.frame_hash(), "frame_hash should be deterministic"
    print("OK — frame_hash is deterministic across rebuilds")
    # UUID validation
    assert is_valid_xr_anchor_uuid("01234567-89ab-cdef-0123-456789abcdef")
    assert is_valid_xr_anchor_uuid("0123456789abcdef0123456789abcdef")
    assert not is_valid_xr_anchor_uuid("not-a-uuid")
    print("OK — UUID validation")


if __name__ == "__main__":
    _self_test()
