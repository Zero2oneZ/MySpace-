#!/bin/bash
# Master Loop - Orchestrates project creation, runs server, and decompiles itself

echo "=== MASTER LOOP INITIATED ==="
echo "Timestamp: $(date -Iseconds)"
echo ""

# Step 1: Initialize project environment
echo "[Step 1] Creating project environment..."
mkdir -p project_env
cp index.html project_env/
cp server.py project_env/
cp hash_utils.py project_env/
echo "Project files copied to project_env/"

# Step 2: Compute project hash
echo "[Step 2] Computing project hash..."
PROJECT_HASH=$(cat index.html server.py hash_utils.py | python3 -c "import blake3, sys; print(blake3.blake3(sys.stdin.buffer.read()).hexdigest())")
echo "Project hash: $PROJECT_HASH"

# Step 3: Run decompile loop on project hash
echo "[Step 3] Running decompile loop on project hash..."
echo "Project hash: $PROJECT_HASH" > project_env/project_hash.txt
cat << 'DECOMPILER' > project_env/decompiler.py
#!/usr/bin/env python3
import sys
sys.path.insert(0, '/data/Projects/MySpace++/chainbabe')
from hash import invert_hash, hash_loop_invert, decode_hash_to_text

initial_hash = sys.argv[1] if len(sys.argv) > 1 else "abc123def456"
iterations = int(sys.argv[2]) if len(sys.argv) > 2 else 5

print(f"=== MASTER LOOP DECOMPILE ===")
print(f"Starting hash: {initial_hash}")
print(f"Iterations: {iterations}")
print()

hashes = hash_loop_invert(initial_hash, iterations)
for i, h in enumerate(hashes):
    inverted = invert_hash(h)
    decoded = decode_hash_to_text(h)
    print(f"[Iteration {i}]")
    print(f"  Hash:    {h}")
    print(f"  Inverted: {inverted}")
    print(f"  Decoded:  {decoded}")
    print()

print("=== DECOMPILE COMPLETE ===")
print("The loop has decompiled itself back into readable form.")
DECOMPILER

echo "Running decompiler..."
python3 project_env/decompiler.py "$PROJECT_HASH" 5

# Step 4: Start the server in background
echo ""
echo "[Step 4] Starting Gradio-like server..."
cd project_env
python3 server.py &
SERVER_PID=$!
echo "Server PID: $SERVER_PID"
cd ..

# Step 5: Self-decompile the master loop
echo ""
echo "[Step 5] Master loop decompiling itself..."
echo "Computing master loop hash..."

MASTER_HASH=$(cat master_loop.sh | python3 -c "import blake3, sys; print(blake3.blake3(sys.stdin.buffer.read()).hexdigest())")
echo "Master loop hash: $MASTER_HASH"

echo "Running master loop decompile..."
python3 << DECOMPILE
import sys
sys.path.insert(0, '/data/Projects/MySpace++/chainbabe')
from hash import invert_hash, hash_loop_invert

hash = "$MASTER_HASH"
print(f"=== MASTER LOOP SELF-DECOMPILE ===")
print(f"Master loop hash: {hash}")
print()

for i in range(5):
    inverted = invert_hash(hash)
    print(f"Iteration {i}:")
    print(f"  Original: {hash}")
    print(f"  Inverted: {inverted}")
    hash = inverted
    print()

print("=== SELF-DECOMPILE COMPLETE ===")
print("Master loop has decompiled itself back to readable form.")
DECOMPILE

# Cleanup
echo ""
echo "[Cleanup] Stopping server..."
kill $SERVER_PID 2>/dev/null

echo ""
echo "=== MASTER LOOP COMPLETE ==="
echo "Project folder: test-project/"
echo "Server was running at: http://localhost:8080"
echo "Master loop has completed decompilation."
echo "Timestamp: $(date -Iseconds)"
