#!/usr/bin/env bash
#
# cc-pipeline-123.sh — CC 1-2-3 dual-model pipeline
#
# Usage:
#   ./cc-pipeline-123.sh "your instructions here"
#
# Pipeline:
#   CC 1 (llama3.2:latest)    — Explains and reorders your instructions
#   CC 2 (codie-v4:latest)    — Outputs instruction blocks
#   CC 3 (qwen2.5-coder:1.5b) — Codes bash scripts from blocks
#
# All outputs cached in ~/.cc/pipeline_cache/ (JSON files)
#

set -euo pipefail

# === CONFIG ===
CACHE_DIR="${CACHE_DIR:-$HOME/.cc/pipeline_cache}"
SCRIPTS_DIR="${SCRIPTS_DIR:-/tmp/cc-pipeline-scripts}"
MODEL_1="${MODEL_1:-llama3.2:latest}"      # Explainer/Reorderer
MODEL_2="${MODEL_2:-llama3.2:latest}"      # Block outputter (codie-v4 outputs JSON, use llama)
MODEL_3="${MODEL_3:-qwen2.5-coder:1.5b}"   # Bash coder

# === COLORS ===
RED='\033[0;31m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
MAGENTA='\033[0;35m'
NC='\033[0m'

log_stage() {
    echo -e "${CYAN}[STAGE $1]${NC} $2"
}

log_output() {
    echo -e "${GREEN}$1${NC}"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1" >&2
}

log_info() {
    echo -e "${YELLOW}[INFO]${NC} $1"
}

# === INIT CACHE DIR ===
init_cache() {
    mkdir -p "$CACHE_DIR"
    mkdir -p "$SCRIPTS_DIR"
    mkdir -p "$CACHE_DIR/northstar"
}

# === GENERATE RUN ID ===
generate_run_id() {
    date +%Y%m%d_%H%M%S_$$
}

# === STAGE 1: LLAMA3.2 — EXPLAIN + REORDER ===
stage1_explain_reorder() {
    local input="$1"
    local run_id="$2"

    log_stage "1" "llama3.2:latest — Explaining and reordering instructions..."

    local prompt="You are the instruction organizer. The user will give you rough instructions.
Your job:
1. Explain what they want to achieve (1-2 sentences)
2. Reorder their instructions into a logical sequence (numbered list)
3. Keep it concise and actionable

User instructions:
$input

Output format:
EXPLANATION: <your 1-2 sentence summary>
ORDERED:
1. <first step>
2. <second step>
3. <third step>
..."

    local output
    output=$(ollama run "$MODEL_1" "$prompt" 2>/dev/null)

    # Save to cache
    echo "$output" > "$CACHE_DIR/${run_id}_stage1.txt"

    log_output "$output"
    echo "$output"
}

# === STAGE 2: CODIE-V4 — OUTPUT INSTRUCTION BLOCKS ===
stage2_output_blocks() {
    local stage1_output="$1"
    local run_id="$2"

    log_stage "2" "codie-v4:latest — Extracting instruction blocks..."

    local prompt="You are the block extractor. Take the organized instructions and output
them as discrete instruction blocks. Each block should be self-contained
and ready to be turned into code.

IMPORTANT: Output PLAIN TEXT only, not JSON. No {"s":...} format.

Format:
BLOCK 1: <title>
<instruction content>

BLOCK 2: <title>
<instruction content>

Input:
$stage1_output

Extract the blocks now:"

    local output
    output=$(ollama run "$MODEL_2" "$prompt" 2>/dev/null)

    # Save to cache
    echo "$output" > "$CACHE_DIR/${run_id}_stage2.txt"

    log_output "$output"
    echo "$output"
}

# === STAGE 3: QWEN2.5-CODER — CODE BASH SCRIPTS ===
stage3_code_bash() {
    local stage2_output="$1"
    local run_id="$2"

    log_stage "3" "qwen2.5-coder:1.5b — Coding bash scripts from blocks..."

    local prompt="You are the bash coder. Take the instruction blocks and write bash scripts
that implement them.

OUTPUT FORMAT (MUST FOLLOW EXACTLY):
For each instruction block, write:

SCRIPT: <name>.sh
\`\`\`bash
#!/usr/bin/env bash
set -euo pipefail
# your code here
\`\`\`

RULES:
- SCRIPT: line must be OUTSIDE the code block (not inside)
- Each script gets its own SCRIPT: + code block pair
- Use clear function names and comments

Instruction blocks:
$stage2_output

Code the scripts now:"

    local output
    output=$(ollama run "$MODEL_3" "$prompt" 2>/dev/null)

    # Save to cache
    echo "$output" > "$CACHE_DIR/${run_id}_stage3.txt"

    log_output "$output"
    echo "$output"
}

# === EXTRACT + SAVE SCRIPTS ===
extract_and_save_scripts() {
    local stage3_output="$1"
    local run_id="$2"

    log_stage "EXTRACT" "Saving scripts to $SCRIPTS_DIR..."

    # Use Python extractor for robust parsing
    local script_count
    script_count=$(python3 /data/Projects/MySpace++/scripts/extract_scripts.py \
        "$CACHE_DIR/${run_id}_stage3.txt" \
        "$SCRIPTS_DIR" \
        "$CACHE_DIR" \
        "$run_id" 2>&1 | grep -oP 'Extracted \K[0-9]+' || echo "0")

    # Show saved scripts
    for script in "$SCRIPTS_DIR"/*.sh; do
        if [[ -f "$script" ]]; then
            log_output "  Saved: $script"
        fi
    done

    log_info "Extracted $script_count scripts"
}

# === RUN CACHED SCRIPTS ===
run_cached_scripts() {
    local run_id="$1"

    log_stage "RUN" "Executing cached scripts..."

    local success_count=0
    local fail_count=0

    for script in "$SCRIPTS_DIR"/*.sh; do
        if [[ -f "$script" ]]; then
            log_output "Running: $script"

            local output
            local exit_code=0
            output=$("$script" 2>&1) || exit_code=$?

            # Log output
            local script_name
            script_name=$(basename "$script")
            echo "$output" > "$CACHE_DIR/${run_id}_output_${script_name%.sh}.txt"

            # Log to northstar
            echo "{\"run_id\": \"$run_id\", \"event\": \"script_executed\", \"script\": \"$script_name\", \"exit_code\": $exit_code, \"ts\": \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"}" >> "$CACHE_DIR/northstar/${run_id}.jsonl"

            if [[ $exit_code -eq 0 ]]; then
                log_output "  ✓ Success"
                ((success_count++))
            else
                log_error "  ✗ Failed (exit $exit_code)"
                ((fail_count++))
                echo "$output"
            fi
        fi
    done

    log_info "Results: $success_count succeeded, $fail_count failed"
}

# === SHOW CACHE STATUS ===
show_cache_status() {
    log_info "Cache directory: $CACHE_DIR"
    log_info "Scripts directory: $SCRIPTS_DIR"
    echo ""

    if [[ -d "$CACHE_DIR" ]]; then
        log_info "Cached runs:"
        ls -la "$CACHE_DIR"/*.txt 2>/dev/null | head -10 || echo "  (none)"
    fi

    if [[ -d "$SCRIPTS_DIR" ]]; then
        log_info "Cached scripts:"
        ls -la "$SCRIPTS_DIR"/*.sh 2>/dev/null | head -10 || echo "  (none)"
    fi
}

# === MAIN ===
main() {
    local input="${1:-}"

    case "$input" in
        -status|--status|-s)
            show_cache_status
            exit 0
            ;;
        -clear|--clear|-c)
            log_info "Clearing cache..."
            rm -rf "$CACHE_DIR"/*
            rm -rf "$SCRIPTS_DIR"/*
            log_output "Cache cleared"
            exit 0
            ;;
        -help|--help|-h)
            echo "Usage: $0 [options] \"your instructions here\""
            echo ""
            echo "Pipeline:"
            echo "  CC 1 (llama3.2:latest)    — Explains and reorders"
            echo "  CC 2 (codie-v4:latest)    — Outputs instruction blocks"
            echo "  CC 3 (qwen2.5-coder:1.5b) — Codes bash scripts"
            echo ""
            echo "Options:"
            echo "  -status, -s    Show cache status"
            echo "  -clear, -c     Clear cache"
            echo "  -help, -h      Show this help"
            echo ""
            echo "Environment:"
            echo "  CACHE_DIR      Cache directory (default: ~/.cc/pipeline_cache)"
            echo "  SCRIPTS_DIR    Scripts output directory (default: /tmp/cc-pipeline-scripts)"
            echo "  MODEL_1-3      Override models"
            exit 0
            ;;
    esac

    if [[ -z "$input" ]]; then
        echo "Usage: $0 \"your instructions here\""
        echo ""
        echo "Use -help for options."
        exit 1
    fi

    init_cache

    local run_id
    run_id=$(generate_run_id)

    # Save input
    echo "$input" > "$CACHE_DIR/${run_id}_input.txt"

    echo ""
    echo "=========================================="
    echo "     CC 1-2-3 PIPELINE"
    echo "=========================================="
    echo ""
    echo "Input: $input"
    echo "Run ID: $run_id"
    echo ""

    # Stage 1
    local stage1_output
    stage1_output=$(stage1_explain_reorder "$input" "$run_id")

    echo ""

    # Stage 2
    local stage2_output
    stage2_output=$(stage2_output_blocks "$stage1_output" "$run_id")

    echo ""

    # Stage 3
    local stage3_output
    stage3_output=$(stage3_code_bash "$stage2_output" "$run_id")

    echo ""

    # Extract and save scripts
    extract_and_save_scripts "$stage3_output" "$run_id"

    echo ""

    # Run cached scripts
    run_cached_scripts "$run_id"

    echo ""
    echo "=========================================="
    echo "     PIPELINE COMPLETE"
    echo "=========================================="
    echo ""
    echo "Cache: $CACHE_DIR"
    echo "Scripts: $SCRIPTS_DIR"
    echo ""
    echo "Northstar log: $CACHE_DIR/northstar/${run_id}.jsonl"
    echo ""
}

main "$@"
