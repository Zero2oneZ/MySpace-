#include "spatial_bridge.h"
#include <godot_cpp/core/class_db.hpp>
#include <godot_cpp/variant/utility_functions.hpp>
#include <cmath>

using namespace godot;

void SpatialBridge::_bind_methods() {
    ClassDB::bind_method(D_METHOD("compute_physics_context", "joints"), &SpatialBridge::compute_physics_context);
    ClassDB::bind_method(D_METHOD("crystal_hash", "payload"), &SpatialBridge::crystal_hash);
    ClassDB::bind_method(D_METHOD("fuse_depth", "acoustic", "visual", "meta"), &SpatialBridge::fuse_depth);
    ClassDB::bind_method(D_METHOD("mirror_drift", "forward", "inverse"), &SpatialBridge::mirror_drift);
}

SpatialBridge::SpatialBridge() {}
SpatialBridge::~SpatialBridge() {}

TypedArray<float> SpatialBridge::compute_physics_context(TypedArray<Vector3> p_joints) {
    // IK-delta: per joint, compute stretch ratio and strain
    // Expected 25 joints (skeletal_crystal standard)
    TypedArray<float> out;
    int n = p_joints.size();
    if (n == 0) return out;

    for (int i = 0; i < n; ++i) {
        Vector3 j = p_joints[i];
        // stretch ratio placeholder (needs parent + rest length)
        out.append(1.0f);
        // ik strain placeholder
        out.append(0.0f);
    }
    return out;
}

String SpatialBridge::crystal_hash(Dictionary p_payload) {
    // SHA-256 via Godot's HashingContext (call GDScript or use std::hash fallback)
    String json = JSON::stringify(p_payload);
    // Simplified: use built-in hash for now; replace with SHA256 when godot-cpp exposes it
    uint32_t h = json.hash();
    return String::num_int64(h, 16).pad_zeros(16);
}

TypedArray<float> SpatialBridge::fuse_depth(
    TypedArray<float> p_acoustic,
    TypedArray<float> p_visual,
    TypedArray<float> p_meta
) {
    TypedArray<float> fused;
    int n = p_visual.size();
    for (int i = 0; i < n; ++i) {
        float v = p_visual[i];
        float a = (i < p_acoustic.size()) ? p_acoustic[i] : v;
        float m = (i < p_meta.size()) ? p_meta[i] : v;
        // Weighted fusion: visual primary, meta secondary, acoustic tertiary
        fused.append(0.6f * v + 0.3f * m + 0.1f * a);
    }
    return fused;
}

float SpatialBridge::mirror_drift(Dictionary p_forward, Dictionary p_inverse) {
    // Hamming-style distance between forward and inverse crystal hashes
    String f = crystal_hash(p_forward);
    String inv = crystal_hash(p_inverse);
    float diff = 0.0f;
    int len = f.length();
    for (int i = 0; i < len; ++i) {
        if (i < inv.length() && f[i] != inv[i]) diff += 1.0f;
    }
    return diff / float(len);
}
