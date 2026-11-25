-- task_manager.lua
-- TaskChain rails: global + local symmetry
-- Every task rides the rails from first prompt

local M = {}

-- TaskChains stored by task_chain_id
M.task_chains = {}

-- StepState structure
local function create_step_state(vm_id, local_db, global_db)
    return {
        vm_id = vm_id,
        local_db = local_db or "defold://local.db",
        global_db = global_db or "defold://global.db",
        files = {},
        chain_ids = {},
        tags = {},
        status = "pending"
    }
end

-- Create new TaskChain
function M.start_task(sym_array, task_string, scope_header)
    local task_chain_id = M.hash_task_chain(sym_array, task_string, scope_header)
    local steps = {}
    for _, sym in ipairs(sym_array) do
        steps[sym] = create_step_state(sym)
    end
    local chain = {
        sym_array = sym_array,
        task = task_string,
        steps = steps,
        created_at = os.time(),
        status = "running"
    }
    M.task_chains[task_chain_id] = chain
    return task_chain_id, chain
end

-- Hash function for task_chain_id
function M.hash_task_chain(sym_array, task, scope)
    local input = table.concat(sym_array, ",") .. "|" .. task .. "|" .. (scope or "")
    local hash = 0
    for i = 1, #input do
        hash = ((hash * 31) + string.byte(input, i)) % 4294967296
    end
    return string.format("%08x", hash)
end

-- Update step
function M.update_step(task_chain_id, vm_id, updates)
    local chain = M.task_chains[task_chain_id]
    if not chain then
        print("ERROR: TaskChain not found: " .. task_chain_id)
        return false
    end
    local step = chain.steps[vm_id]
    if not step then
        print("ERROR: Step not found for vm: " .. vm_id)
        return false
    end
    for k, v in pairs(updates) do
        step[k] = v
    end
    return true
end

-- Add file to step
function M.add_file(task_chain_id, vm_id, file_coord)
    local chain = M.task_chains[task_chain_id]
    if chain and chain.steps[vm_id] then
        table.insert(chain.steps[vm_id].files, file_coord)
    end
end

-- Add chain reference to step
function M.add_chain(task_chain_id, vm_id, chain_run_id)
    local chain = M.task_chains[task_chain_id]
    if chain and chain.steps[vm_id] then
        table.insert(chain.steps[vm_id].chain_ids, chain_run_id)
    end
end

-- Get current active chain for a VM
function M.get_active_chain(vm_id)
    for id, chain in pairs(M.task_chains) do
        for _, sym in ipairs(chain.sym_array) do
            if sym == vm_id and chain.status == "running" then
                return id, chain
            end
        end
    end
    return nil, nil
end

-- Serialize to JSON-like string
function M.serialize(task_chain_id)
    local chain = M.task_chains[task_chain_id]
    if not chain then return "{}" end
    -- Simplified serialization
    local parts = {}
    table.insert(parts, '{"sym_array":[')
    for i, sym in ipairs(chain.sym_array) do
        table.insert(parts, '"' .. sym .. '"')
        if i < #chain.sym_array then table.insert(parts, ",") end
    end
    table.insert(parts, '],"task":"' .. chain.task .. '"}')
    return table.concat(parts)
end

return M
