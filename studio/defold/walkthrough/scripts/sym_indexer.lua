-- sym_indexer.lua
-- 2-Pass LLM: LLM-F (forward/semantic) + LLM-R (reverse/symbolic indexer)
-- SYM_INDEX appended to every reply for navigability

local M = {}

-- Generate SYM_INDEX from task chain + model response
function M.generate(task_chain_id, vm_registry, task_manager)
    local chain = task_manager.task_chains[task_chain_id]
    if not chain then
        print("ERROR: Cannot index — TaskChain not found")
        return nil
    end

    local sym_index = {}
    for _, sym in ipairs(chain.sym_array) do
        local step = chain.steps[sym]
        local vm = vm_registry[sym]
        sym_index[sym] = {
            project = vm and vm.case or "unknown",
            roles = { vm and vm.role or "unknown" },
            touched_files = step and step.files or {},
            related_tasks = { chain.task },
            chains = step and step.chain_ids or {},
            status = step and step.status or "pending"
        }
    end
    return sym_index
end

-- Format SYM_INDEX as a string (appended to LLM reply)
function M.format_string(sym_index)
    local lines = { "\nSYM_INDEX = {" }
    for vm_id, data in pairs(sym_index) do
        table.insert(lines, '  "' .. vm_id .. '" = {')
        table.insert(lines, '    project = "' .. data.project .. '",')
        table.insert(lines, '    roles = { "' .. table.concat(data.roles, '", "') .. '" },')
        table.insert(lines, '    touched_files = { ' .. #data.touched_files .. ' entries },')
        table.insert(lines, '    related_tasks = { "' .. table.concat(data.related_tasks, '", "') .. '" },')
        table.insert(lines, '    chains = { ' .. #data.chains .. ' entries },')
        table.insert(lines, '    status = "' .. data.status .. '"')
        table.insert(lines, '  },')
    end
    table.insert(lines, "}")
    return table.concat(lines, "\n")
end

return M
