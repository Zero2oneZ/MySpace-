#include "ik_solver.h"
#include <godot_cpp/core/class_db.hpp>
#include <godot_cpp/variant/utility_functions.hpp>
#include <cmath>

using namespace godot;

void IKSolver::_bind_methods() {
    ClassDB::bind_method(D_METHOD("solve_two_bone", "root", "mid", "end", "target", "bone_len_a", "bone_len_b"), &IKSolver::solve_two_bone);
    ClassDB::bind_method(D_METHOD("solve_ccd", "chain", "target", "iterations"), &IKSolver::solve_ccd);
    ClassDB::bind_method(D_METHOD("ik_delta", "controller_goal", "solver_result"), &IKSolver::ik_delta);
}

IKSolver::IKSolver() {}
IKSolver::~IKSolver() {}

Dictionary IKSolver::solve_two_bone(Vector3 p_root, Vector3 p_mid, Vector3 p_end, Vector3 p_target, float p_bone_len_a, float p_bone_len_b) {
    Vector3 to_target = p_target - p_root;
    float dist = to_target.length();
    float max_reach = p_bone_len_a + p_bone_len_b;
    float min_reach = Math::abs(p_bone_len_a - p_bone_len_b);

    if (dist > max_reach) {
        to_target = to_target.normalized() * max_reach;
        dist = max_reach;
    } else if (dist < min_reach) {
        to_target = to_target.normalized() * min_reach;
        dist = min_reach;
    }

    // Law of cosines
    float a = p_bone_len_a;
    float b = p_bone_len_b;
    float c = dist;
    float angle_a = Math::acos(Math::clamp((b * b + c * c - a * a) / (2.0f * b * c), -1.0f, 1.0f));
    float angle_b = Math::acos(Math::clamp((a * a + c * c - b * b) / (2.0f * a * c), -1.0f, 1.0f));

    // Build basis
    Vector3 forward = to_target.normalized();
    Vector3 up = Vector3(0, 1, 0);
    if (Math::abs(forward.dot(up)) > 0.99f) up = Vector3(0, 0, 1);
    Vector3 right = forward.cross(up).normalized();
    up = right.cross(forward).normalized();

    float plane_angle = 0.0f; // Could be exposed as parameter
    Vector3 mid_local = Vector3(
        Math::sin(plane_angle) * Math::sin(angle_b) * a,
        Math::cos(plane_angle) * Math::sin(angle_b) * a,
        Math::cos(angle_b) * a
    );
    Vector3 new_mid = p_root + right * mid_local.x + up * mid_local.y + forward * mid_local.z;
    Vector3 new_end = p_root + forward * c;

    Dictionary out;
    out["mid"] = new_mid;
    out["end"] = new_end;
    out["angle_a"] = angle_a;
    out["angle_b"] = angle_b;
    return out;
}

TypedArray<Vector3> IKSolver::solve_ccd(TypedArray<Vector3> p_chain, Vector3 p_target, int p_iterations) {
    TypedArray<Vector3> chain = p_chain.duplicate();
    int n = chain.size();
    if (n < 2) return chain;

    for (int iter = 0; iter < p_iterations; ++iter) {
        for (int i = n - 2; i >= 0; --i) {
            Vector3 joint = chain[i];
            Vector3 end = chain[n - 1];
            Vector3 to_end = end - joint;
            Vector3 to_target = p_target - joint;
            if (to_end.length_squared() < 0.0001f || to_target.length_squared() < 0.0001f) continue;

            Quaternion q;
            q.set_from_to_rotation(to_end.normalized(), to_target.normalized());
            Basis rot(q);

            for (int j = i + 1; j < n; ++j) {
                chain[j] = joint + rot.xform(chain[j] - joint);
            }
        }
    }
    return chain;
}

float IKSolver::ik_delta(Vector3 p_controller_goal, Vector3 p_solver_result) {
    return (p_controller_goal - p_solver_result).length();
}
