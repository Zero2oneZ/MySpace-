// GENERATED from workflow_card: photo_to_avatar_rigged
// card_crystal: 04c7865e2553a0eed117aa75dd95ec7e45eec7ef8ee024d7a61612aa3891e673daa68368ec54a7fcdbac34ec605c746c076c0d90cddc5cc2dab7361b0074fb6b
// target: godot_cpp
// schema: workflow_card_v0
// DO NOT EDIT BY HAND — regenerate via: cc workflow generate photo_to_avatar_rigged
#include <godot_cpp/classes/node3d.hpp>
#include <godot_cpp/core/class_db.hpp>
#include <godot_cpp/variant/utility_functions.hpp>

namespace godot {

class PhotoToAvatarRigged : public Node3D {
    GDCLASS(PhotoToAvatarRigged, Node3D);
protected:
    static void _bind_methods() {
        ClassDB::bind_method(D_METHOD("run_pipeline"), &PhotoToAvatarRigged::run_pipeline);
        ClassDB::bind_method(D_METHOD("get_card_crystal"), &PhotoToAvatarRigged::get_card_crystal);
    }
public:
    String get_card_crystal() const { return "04c7865e2553a0eed117aa75dd95ec7e45eec7ef8ee024d7a61612aa3891e673daa68368ec54a7fcdbac34ec605c746c076c0d90cddc5cc2dab7361b0074fb6b"; }
    void run_pipeline() {
        UtilityFunctions::print("[photo_to_avatar_rigged] native pipeline run — crystal=", get_card_crystal().substr(0, 16));
        // each pass dispatches via the CC bridge (see GDScript controller)
    }
};

} // namespace godot
