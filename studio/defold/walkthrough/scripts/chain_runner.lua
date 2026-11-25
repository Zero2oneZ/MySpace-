-- chain_runner.lua
-- Chain coordination: predict -> execute -> extend -> mirror -> crystallize
-- Mirrors gently's chain hashing in Lua

local M = {}

-- Global chain registry (equivalent to chain_runs table)
M.chain_runs = {}
M.mirror_runs = {}

-- Simple hash function (placeholder for sha256/blake3)
local function simple_hash(input)
    local hash = 0
    for i = 1, #input do
        hash = ((hash * 31) + string.byte(input, i)) % 4294967296
    end
    return string.format("%08x", hash)
end

-- XOR two hashes (for crystal)
local function xor_hashes(a, b)
    -- Pad to same length
    local max_len = math.max(#a, #b)
    local pa = string.rep("0", max_len - #a) .. a
    local pb = string.rep("0", max_len - #b) .. b
    local result = {}
    for i = 1, max_len do
        local ba = tonumber(pa:sub(i,i), 16) or 0
        local bb = tonumber(pb:sub(i,i), 16) or 0
        table.insert(result, string.format("%x", bit32.bxor(ba, bb)))
    end
    return table.concat(result)
end

-- Step 1: Genesis (runtime identity binding)
function M.genesis(runtime_binary_hash)
    local run = {
        id = #M.chain_runs + 1,
        hash = runtime_binary_hash or simple_hash("genesis"),
        prev_hash = nil,
        op = "genesis",
        data = { runtime = runtime_binary_hash },
        crystal = runtime_binary_hash,
        timestamp = os.time()
    }
    table.insert(M.chain_runs, run)
    return run.hash
end

-- Step 2: Predict
function M.predict(prev_hash, prompt)
    local op_hash = simple_hash(prompt)
    local run = {
        id = #M.chain_runs + 1,
        hash = op_hash,
        prev_hash = prev_hash,
        op = "predict",
        data = { prompt = prompt },
        crystal = nil,
        timestamp = os.time()
    }
    table.insert(M.chain_runs, run)
    return op_hash
end

-- Step 3: Execute
function M.execute(op_hash, result)
    local result_hash = simple_hash(result)
    local run = {
        id = #M.chain_runs + 1,
        hash = result_hash,
        prev_hash = op_hash,
        op = "execute",
        data = { result = result },
        crystal = nil,
        timestamp = os.time()
    }
    table.insert(M.chain_runs, run)
    return result_hash
end

-- Step 4: Extend
function M.extend(prev_hash, new_hash)
    local chain_hash = simple_hash(prev_hash .. new_hash)
    local run = {
        id = #M.chain_runs + 1,
        hash = chain_hash,
        prev_hash = prev_hash,
        op = "extend",
        data = { extended = new_hash },
        crystal = nil,
        timestamp = os.time()
    }
    table.insert(M.chain_runs, run)
    return chain_hash
end

-- Step 5: Mirror (anti-particle)
function M.mirror(op_hash, inverse_op)
    local mirror_hash = simple_hash(inverse_op)
    local run = {
        id = #M.mirror_runs + 1,
        run_id = #M.chain_runs,
        mirror_hash = mirror_hash,
        inverse_op = inverse_op,
        timestamp = os.time()
    }
    table.insert(M.mirror_runs, run)
    return mirror_hash
end

-- Step 6: Crystallize
function M.crystallize(chain_id)
    local forward_hash = M.chain_runs[#M.chain_runs].hash
    local mirror_hash = M.mirror_runs[#M.mirror_runs] and M.mirror_runs[#M.mirror_runs].mirror_hash or "00000000"
    local crystal = xor_hashes(forward_hash, mirror_hash)
    local run = {
        id = #M.chain_runs + 1,
        hash = crystal,
        prev_hash = forward_hash,
        op = "crystallize",
        data = { crystal = crystal },
        crystal = crystal,
        timestamp = os.time()
    }
    table.insert(M.chain_runs, run)
    return crystal
end

-- Full chain run
function M.run_chain(instruction)
    local prev = M.genesis()
    local predict_hash = M.predict(prev, instruction)
    local result = "Result of: " .. instruction
    local result_hash = M.execute(predict_hash, result)
    local chain_hash = M.extend(predict_hash, result_hash)
    local mirror_hash = M.mirror(predict_hash, "undo-execute:" .. result_hash)
    local crystal = M.crystallize()
    return {
        crystal = crystal,
        forward_hash = chain_hash,
        mirror_hash = mirror_hash,
        chain_id = #M.chain_runs
    }
end

-- Correlation ID (sha256 of both halves' UUIDs)
function M.correlation_id(mspc_uuid, gently_uuid)
    return simple_hash(mspc_uuid .. "|" .. gently_uuid)
end

return M
