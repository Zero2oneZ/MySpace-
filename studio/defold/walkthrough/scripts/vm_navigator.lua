-- vm_navigator.lua
-- Virtual Module graph walker for Defold
-- Mirrors the ~/.vmfs/ concept inside the engine

local M = {}

-- Registry of all VMs (equivalent to ~/.vmfs/)
M.registry = {}

-- Symbol array tracking current context
M.sym_array = {}

-- VM card template
local function create_vm_card(vm_id, case_name, role, scope, crystal)
    return {
        vm_id = vm_id,
        case = case_name or "MySpace++",
        role = role or "asset",
        crystal = crystal or nil,
        scope = scope or "defold://walkthrough",
        created_at = os.date("!%Y-%m-%dT%H:%M:%SZ"),
        files = {},
        docs = {},
        imports = {}
    }
end

-- Register a new VM
function M.register_vm(vm_id, case_name, role, scope, crystal)
    if not M.registry[vm_id] then
        M.registry[vm_id] = create_vm_card(vm_id, case_name, role, scope, crystal)
        table.insert(M.sym_array, vm_id)
    end
    return M.registry[vm_id]
end

-- Import one VM into another (creates symlink equivalent)
function M.vm_import(host_vm_id, guest_vm_id)
    local host = M.registry[host_vm_id]
    local guest = M.registry[guest_vm_id]
    if not host or not guest then
        print("ERROR: Cannot import — VM not found")
        return false
    end
    table.insert(host.imports, guest_vm_id)
    return true
end

-- Graph walker (DFS)
function M.walk_graph(start_vm_id, visit_fn)
    local visited = {}
    local stack = { start_vm_id }

    while #stack > 0 do
        local current = table.remove(stack)
        if not visited[current] then
            visited[current] = true
            if visit_fn then
                visit_fn(M.registry[current])
            end
            local vm = M.registry[current]
            if vm then
                for _, import_id in ipairs(vm.imports) do
                    if not visited[import_id] then
                        table.insert(stack, import_id)
                    end
                end
            end
        end
    end
end

-- Canonical filename generator
-- symbol{array}.project.folder.file.git.branch
function M.canonical_name(vm_id, slot, project, folder, file, git, branch)
    local symbol = vm_id
    local array = tostring(slot or 0)
    return string.format("%s{%s}.%s.%s.%s.%s.%s.txt",
        symbol, array, project, folder, file, git or "nogit", branch or "nogit")
end

-- Derive vm_id from scope (mirrors cc_current_vm_id)
function M.derive_vm_id(cwd, agent_uuid)
    local base = cwd .. "|" .. agent_uuid
    -- Simple hash (in real impl: sha256)
    local hash = 0
    for i = 1, #base do
        hash = ((hash * 31) + string.byte(base, i)) % 4294967296
    end
    return "vm_" .. string.format("%08x", hash)
end

-- Add file to VM
function M.see_file(vm_id, path, project, folder, file, git, branch)
    local vm = M.registry[vm_id]
    if not vm then
        print("ERROR: VM not found: " .. vm_id)
        return nil
    end
    local slot = #vm.files
    local name = M.canonical_name(vm_id, slot, project, folder, file, git, branch)
    table.insert(vm.files, {
        canonical = name,
        path = path,
        project = project,
        folder = folder,
        file = file,
        git = git or "nogit",
        branch = branch or "nogit"
    })
    return name
end

return M
