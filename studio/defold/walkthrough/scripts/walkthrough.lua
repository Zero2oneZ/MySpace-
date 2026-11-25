-- walkthrough.lua
-- Main controller for real estate walkthrough
-- Integrates VM navigator + chain runner + task manager + sym indexer

local vm_nav = require("scripts.vm_navigator")
local chain = require("scripts.chain_runner")
local task_mgr = require("scripts.task_manager")
local sym_idx = require("scripts.sym_indexer")

local M = {}

-- Fixed-state variables (prevents memory leaks)
M.current_room = "living_room"
M.is_transitioning = false
M.vm_id = nil
M.task_chain_id = nil

-- Room definitions
M.rooms = {
    living_room = { position = vmath.vector3(0, 0, 0), label = "Living Room" },
    kitchen = { position = vmath.vector3(10, 0, 0), label = "Kitchen" },
    bedroom = { position = vmath.vector3(5, 0, -8), label = "Bedroom" },
    bathroom = { position = vmath.vector3(8, 0, -4), label = "Bathroom" }
}

function init(self)
    --  [Initialization]
    --   └── Derive VM ID from scope
    --   └── Register this walkthrough as a VM
    --   └── Start TaskChain rails
    --   └── Acquire input focus
    self.vm_id = vm_nav.derive_vm_id("defold://walkthrough", tostring(math.random(100000)))
    vm_nav.register_vm(self.vm_id, "realestate", "walkthrough", "defold://walkthrough")
    self.task_chain_id = task_mgr.start_task(
        { self.vm_id },
        "real estate walkthrough initialization",
        "scope:defold;agent:walkthrough"
    )
    msg.post(".", "acquire_input_focus")
    print("Walkthrough initialized. VM: " .. self.vm_id .. " TaskChain: " .. self.task_chain_id)

    -- Register rooms as assets
    for room_id, room_data in pairs(M.rooms) do
        vm_nav.see_file(self.vm_id, "scene://" .. room_id, "realestate", "scenes", room_id, "nogit", "main")
    end
end

function update(self, dt)
    --  [Continuous Loop]
    --   └── Monitor for memory drift
    --   └── Handle camera transitions
    if self.is_transitioning then
        smooth_glide_to_viewpoint(self, dt)
    end
end

function on_message(self, message_id, message, sender)
    --  [State Transitions]
    --   └── Listen for hotspot clicks
    --   └── Swap room context safely
    if message_id == hash("trigger_teleport") then
        local target_room = message.destination
        if target_room ~= M.current_room then
            M.current_room = target_room
            self.is_transitioning = true
            target_viewpoint = M.rooms[target_room].position
            print("Transitioning to: " .. target_room)
            -- Record in chain
            local chain_result = chain.run_chain("teleport:" .. target_room)
            task_mgr.add_chain(self.task_chain_id, self.vm_id, chain_result.chain_id)
        end
    elseif message_id == hash("query_sym_index") then
        --  [Sym Index Request]
        --   └── Generate navigable index
        local index = sym_idx.generate(self.task_chain_id, vm_nav.registry, task_mgr)
        msg.post(sender, "sym_index_response", { index = index })
    end
end

function on_input(self, action_id, action)
    --  [Input Handling]
    --   └── Click to transition
    if action_id == hash("touch") and action.pressed then
        -- Raycast or hit-test to determine which room was clicked
        -- For now, simple cycle
        local room_keys = {}
        for k in pairs(M.rooms) do table.insert(room_keys, k) end
        local current_idx = 1
        for i, k in ipairs(room_keys) do
            if k == M.current_room then current_idx = i; break end
        end
        local next_idx = (current_idx % #room_keys) + 1
        msg.post(".", "trigger_teleport", { destination = room_keys[next_idx] })
    end
end

function smooth_glide_to_viewpoint(self, dt)
    --  [Camera Transition]
    --   └── Interpolate camera position
    local cam = go.get_position("camera")
    local target = target_viewpoint or cam
    local new_pos = vmath.lerp(dt * 2, cam, target)
    go.set_position(new_pos, "camera")
    if vmath.length(target - cam) < 0.1 then
        self.is_transitioning = false
    end
end

-- Export module functions
M.vm_nav = vm_nav
M.chain = chain
M.task_mgr = task_mgr
M.sym_idx = sym_idx

return M
