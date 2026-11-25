#ifndef MSPC_SPATIAL_BRIDGE_H
#define MSPC_SPATIAL_BRIDGE_H

#include <godot_cpp/classes/node.hpp>
#include <godot_cpp/classes/ref_counted.hpp>
#include <godot_cpp/variant/typed_array.hpp>
#include <godot_cpp/variant/vector3.hpp>

namespace godot {

class SpatialBridge : public Node {
    GDCLASS(SpatialBridge, Node)

protected:
    static void _bind_methods();

public:
    SpatialBridge();
    ~SpatialBridge();

    // PhysicsContext computation from joint positions
    TypedArray<float> compute_physics_context(TypedArray<Vector3> p_joints);

    // Crystal hash of a spatial payload
    String crystal_hash(Dictionary p_payload);

    // Fused depth from multiple signals
    TypedArray<float> fuse_depth(
        TypedArray<float> p_acoustic,
        TypedArray<float> p_visual,
        TypedArray<float> p_meta
    );

    // Mirror-pass drift score
    float mirror_drift(Dictionary p_forward, Dictionary p_inverse);
};

} // namespace godot

#endif // MSPC_SPATIAL_BRIDGE_H
