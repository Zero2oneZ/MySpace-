// GENERATED from workflow_card: pump_surf_pipeline
// card_crystal: 0dbb685dc6f60af4ac9c1026124cb36d2ceddf16ca55fb6f34301cbd8199177c31a77cdb7bad5e9a5f30551866ddf1cf7869112f262e75c966e2d8cbae9931e1
// target: godot_cpp
// schema: workflow_card_v0
// DO NOT EDIT BY HAND — regenerate via: cc workflow generate pump_surf_pipeline
#include <godot_cpp/classes/node3d.hpp>
#include <godot_cpp/core/class_db.hpp>
#include <godot_cpp/variant/utility_functions.hpp>

namespace godot {

class PumpSurfPipeline : public Node3D {
    GDCLASS(PumpSurfPipeline, Node3D);
protected:
    static void _bind_methods() {
        ClassDB::bind_method(D_METHOD("run_pipeline"), &PumpSurfPipeline::run_pipeline);
        ClassDB::bind_method(D_METHOD("get_card_crystal"), &PumpSurfPipeline::get_card_crystal);
    }
public:
    String get_card_crystal() const { return "0dbb685dc6f60af4ac9c1026124cb36d2ceddf16ca55fb6f34301cbd8199177c31a77cdb7bad5e9a5f30551866ddf1cf7869112f262e75c966e2d8cbae9931e1"; }
    void run_pipeline() {
        UtilityFunctions::print("[pump_surf_pipeline] native pipeline run — crystal=", get_card_crystal().substr(0, 16));
        // each pass dispatches via the CC bridge (see GDScript controller)
    }
};

} // namespace godot
