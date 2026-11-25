// GENERATED from workflow_card: realestate_walkthrough_full
// card_crystal: 4b5b9c4a5d3b5600c71da2e80b4346997284960d3202f11cb32ed05db348219fca89e0b61a08a18550d9d8db72d2ea8297d367804789e33bf0c239f88b3ef835
// target: godot_cpp
// schema: workflow_card_v0
// DO NOT EDIT BY HAND — regenerate via: cc workflow generate realestate_walkthrough_full
#include <godot_cpp/classes/node3d.hpp>
#include <godot_cpp/core/class_db.hpp>
#include <godot_cpp/variant/utility_functions.hpp>

namespace godot {

class RealestateWalkthroughFull : public Node3D {
    GDCLASS(RealestateWalkthroughFull, Node3D);
protected:
    static void _bind_methods() {
        ClassDB::bind_method(D_METHOD("run_pipeline"), &RealestateWalkthroughFull::run_pipeline);
        ClassDB::bind_method(D_METHOD("get_card_crystal"), &RealestateWalkthroughFull::get_card_crystal);
    }
public:
    String get_card_crystal() const { return "4b5b9c4a5d3b5600c71da2e80b4346997284960d3202f11cb32ed05db348219fca89e0b61a08a18550d9d8db72d2ea8297d367804789e33bf0c239f88b3ef835"; }
    void run_pipeline() {
        UtilityFunctions::print("[realestate_walkthrough_full] native pipeline run — crystal=", get_card_crystal().substr(0, 16));
        // each pass dispatches via the CC bridge (see GDScript controller)
    }
};

} // namespace godot
