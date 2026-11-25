#!/usr/bin/env bash
#
# trust-loop-decompile.sh — Decompile trust loop into dual orchestrator chats
#
# Usage:
#   ./trust-loop-decompile.sh <genesis_hash>
#
# Process:
# 1. Clip genesis hash
# 2. Invert each char (letter→number, number→inverted)
# 3. Reduce to single digit via digital root
# 4. Split chain into 2 orchestrator looping chats
#

set -euo pipefail

# === CONFIG ===
CACHE_DIR="${CACHE_DIR:-$HOME/.cc/trust-loop}"
ORCHESTRATOR_1="${ORCHESTRATOR_1:-llama3.2:latest}"
ORCHESTRATOR_2="${ORCHESTRATOR_2:-qwen2.5-coder:1.5b}"

# === COLORS ===
CYAN='\033[0;36m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
MAGENTA='\033[0;35m'
NC='\033[0m'

log_step() { echo -e "${CYAN}[STEP $1]${NC} $2"; }
log_output() { echo -e "${GREEN}$1${NC}"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }

# === INIT ===
init_cache() {
    mkdir -p "$CACHE_DIR/orchestrator-1"
    mkdir -p "$CACHE_DIR/orchestrator-2"
    mkdir -p "$CACHE_DIR/chains"
}

# === DIGITAL ROOT (reduce to single digit) ===
digital_root() {
    local n="$1"
    while [[ ${#n} -gt 1 ]]; do
        local sum=0
        for ((i=0; i<${#n}; i++)); do
            sum=$((sum + ${n:$i:1}))
        done
        n="$sum"
    done
    echo "$n"
}

# === INVERT CHAR ===
# Letter → position in alphabet (a=1, b=2, ...)
# Number → 10 - n
invert_char() {
    local char="$1"
    local lower=$(echo "$char" | tr '[:upper:]' '[:lower:]')

    if [[ "$char" =~ [a-zA-Z] ]]; then
        # Letter → position (a=1, b=2, ... z=26)
        local pos=$(printf "%d" "'$lower")
        pos=$((pos - 96))  # 'a' = 97 in ASCII, so subtract 96
        echo "$pos"
    elif [[ "$char" =~ [0-9] ]]; then
        # Number → inverted (10 - n, but keep 0 as 0)
        if [[ "$char" == "0" ]]; then
            echo "0"
        else
            echo $((10 - char))
        fi
    else
        # Special chars → ASCII value mod 10
        printf "%d" "'$char" | awk '{print $1 % 10}'
    fi
}

# === PROCESS GENESIS HASH ===
process_genesis_hash() {
    local genesis_hash="$1"
    local inverted_values=()
    local reduced_values=()

    log_step "1" "Processing genesis hash: $genesis_hash"

    # Clip to first 32 chars
    local clipped="${genesis_hash:0:32}"
    log_output "  Clipped: $clipped"

    # Process each character
    for ((i=0; i<${#clipped}; i++)); do
        local char="${clipped:$i:1}"
        local inverted=$(invert_char "$char")

        # Digital root reduction
        local reduced=$(digital_root "$inverted")

        inverted_values+=("$inverted")
        reduced_values+=("$reduced")
    done

    log_output "  Inverted: ${inverted_values[*]}"
    log_output "  Reduced:  ${reduced_values[*]}"

    # Store in cache
    echo "${reduced_values[*]}" > "$CACHE_DIR/chains/reduced_chain.txt"
    echo "${inverted_values[*]}" > "$CACHE_DIR/chains/inverted_chain.txt"
}

# === SPLIT CHAIN INTO 2 ORCHESTRATORS ===
split_chain() {
    local reduced_chain="$CACHE_DIR/chains/reduced_chain.txt"

    log_step "2" "Splitting chain into 2 orchestrators..."

    # Read reduced values
    local values=($(cat "$reduced_chain"))
    local len=${#values[@]}
    local mid=$((len / 2))

    # Split: even indices → Orchestrator 1, odd indices → Orchestrator 2
    local orch1=()
    local orch2=()

    for ((i=0; i<len; i++)); do
        if [[ $((i % 2)) -eq 0 ]]; then
            orch1+=("${values[$i]}")
        else
            orch2+=("${values[$i]}")
        fi
    done

    # Save orchestrator chains
    echo "${orch1[*]}" > "$CACHE_DIR/orchestrator-1/chain.txt"
    echo "${orch2[*]}" > "$CACHE_DIR/orchestrator-2/chain.txt"

    log_output "  Orchestrator 1 (${#orch1[@]} values): ${orch1[*]}"
    log_output "  Orchestrator 2 (${#orch2[@]} values): ${orch2[*]}"

    # Generate chain hashes
    local hash1=$(echo "${orch1[*]}" | blake3 2>/dev/null || sha256sum | cut -d' ' -f1)
    local hash2=$(echo "${orch2[*]}" | blake3 2>/dev/null || sha256sum | cut -d' ' -f1)

    echo "$hash1" > "$CACHE_DIR/orchestrator-1/chain_hash.txt"
    echo "$hash2" > "$CACHE_DIR/orchestrator-2/chain_hash.txt"

    log_output "  Chain 1 hash: ${hash1:0:16}..."
    log_output "  Chain 2 hash: ${hash2:0:16}..."
}

# === START ORCHESTRATOR LOOPS ===
start_orchestrator_loops() {
    log_step "3" "Starting orchestrator loops..."

    # Orchestrator 1 prompt
    local prompt1="You are Orchestrator 1 in a dual-loop trust system.
Your chain values: $(cat $CACHE_DIR/orchestrator-1/chain.txt)
Your chain hash: $(cat $CACHE_DIR/orchestrator-1/chain_hash.txt)

Task: Decompile and reassemble the trust loop.
For each value in your chain:
1. Explain what this value represents
2. Generate a bash command that embodies this value
3. Pass the result to Orchestrator 2

Begin the loop."

    # Orchestrator 2 prompt
    local prompt2="You are Orchestrator 2 in a dual-loop trust system.
Your chain values: $(cat $CACHE_DIR/orchestrator-2/chain.txt)
Your chain hash: $(cat $CACHE_DIR/orchestrator-2/chain_hash.txt)

Task: Invert and validate the trust loop from Orchestrator 1.
For each value in your chain:
1. Verify the value from Orchestrator 1
2. Generate an inverted bash command
3. Pass validation back to Orchestrator 1

Begin the loop."

    # Save prompts
    echo "$prompt1" > "$CACHE_DIR/orchestrator-1/prompt.txt"
    echo "$prompt2" > "$CACHE_DIR/orchestrator-2/prompt.txt"

    log_output "  Orchestrator 1 prompt: $CACHE_DIR/orchestrator-1/prompt.txt"
    log_output "  Orchestrator 2 prompt: $CACHE_DIR/orchestrator-2/prompt.txt"

    # Run orchestrators (can be parallel or sequential)
    log_step "4" "Running Orchestrator 1..."
    ollama run "$ORCHESTRATOR_1" "$prompt1" > "$CACHE_DIR/orchestrator-1/output.txt" 2>&1 &
    local pid1=$!

    log_step "5" "Running Orchestrator 2..."
    ollama run "$ORCHESTRATOR_2" "$prompt2" > "$CACHE_DIR/orchestrator-2/output.txt" 2>&1 &
    local pid2=$!

    # Wait for both
    wait $pid1
    wait $pid2

    log_output "  Orchestrator 1 output: $CACHE_DIR/orchestrator-1/output.txt"
    log_output "  Orchestrator 2 output: $CACHE_DIR/orchestrator-2/output.txt"
}

# === GENERATE LOOP REPORT ===
generate_report() {
    log_step "6" "Generating loop report..."

    cat > "$CACHE_DIR/loop_report.md" << EOF
# Trust Loop Decompile Report

## Genesis Hash
\`\`\`
$1
\`\`\`

## Clipped Hash (32 chars)
\`\`\`
${1:0:32}
\`\`\`

## Chain Processing
- Inverted values: $(cat $CACHE_DIR/chains/inverted_chain.txt)
- Reduced values: $(cat $CACHE_DIR/chains/reduced_chain.txt)

## Orchestrator Split

### Orchestrator 1
- Values: $(cat $CACHE_DIR/orchestrator-1/chain.txt)
- Hash: $(cat $CACHE_DIR/orchestrator-1/chain_hash.txt)
- Output: $CACHE_DIR/orchestrator-1/output.txt

### Orchestrator 2
- Values: $(cat $CACHE_DIR/orchestrator-2/chain.txt)
- Hash: $(cat $CACHE_DIR/orchestrator-2/chain_hash.txt)
- Output: $CACHE_DIR/orchestrator-2/output.txt

## Loop Status
- Orchestrator 1: $([ -f $CACHE_DIR/orchestrator-1/output.txt ] && echo "COMPLETE" || echo "RUNNING")
- Orchestrator 2: $([ -f $CACHE_DIR/orchestrator-2/output.txt ] && echo "COMPLETE" || echo "RUNNING")

Generated: $(date -u +%Y-%m-%dT%H:%M:%SZ)
EOF

    log_output "  Report: $CACHE_DIR/loop_report.md"
}

# === MAIN ===
main() {
    local genesis_hash="${1:-}"

    if [[ -z "$genesis_hash" ]]; then
        # Generate from current date if not provided
        genesis_hash=$(date +%s | sha256sum | cut -d' ' -f1)
        log_warn "No genesis hash provided, generated: $genesis_hash"
    fi

    init_cache

    echo ""
    echo "=========================================="
    echo "     TRUST LOOP DECOMPILE"
    echo "=========================================="
    echo ""

    process_genesis_hash "$genesis_hash"
    split_chain
    start_orchestrator_loops
    generate_report "$genesis_hash"

    echo ""
    echo "=========================================="
    echo "     DECOMPILE COMPLETE"
    echo "=========================================="
    echo ""
    echo "Cache: $CACHE_DIR"
    echo "Report: $CACHE_DIR/loop_report.md"
    echo ""
    echo "To view orchestrator outputs:"
    echo "  cat $CACHE_DIR/orchestrator-1/output.txt"
    echo "  cat $CACHE_DIR/orchestrator-2/output.txt"
    echo ""
}

main "$@"
