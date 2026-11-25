#ifndef MSPC_IK_SOLVER_H
#define MSPC_IK_SOLVER_H

#include <godot_cpp/classes/node.hpp>
#include <godot_cpp/variant/vector3.hpp>
#include <godot_cpp/variant/typed_array.hpp>

namespace godot {

class IKSolver : public Node {
    GDCLASS(IKSolver, Node)

protected:
    static void _bind_methods();

public:
    IKSolver();
    ~IKSolver();

    // Analytic 2-bone IK (arm / leg)
    // p_root: shoulder/hip, p_mid: elbow/knee, p_end: wrist/ankle
    // p_target: goal position
    // Returns new positions for mid + end
    Dictionary solve_two_bone(Vector3 p_root, Vector3 p_mid, Vector3 p_end, Vector3 p_target, float p_bone_len_a, float p_bone_len_b);

    // CCD IK for spine / chain
    TypedArray<Vector3> solve_ccd(TypedArray<Vector3> p_chain, Vector3 p_target, int p_iterations);

    // Compute IK-delta: distance between controller goal and solver result
    float ik_delta(Vector3 p_controller_goal, Vector3 p_solver_result);
};

} // namespace godot

#endif // MSPC_IK_SOLVER_H
