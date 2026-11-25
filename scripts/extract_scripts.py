#!/usr/bin/env python3
"""
extract_scripts.py — Extract bash scripts from LLM output

Usage: python3 extract_scripts.py <input_file> <output_dir> <cache_dir> <run_id>

Handles nested code blocks and SCRIPT: markers in various formats.
"""

import sys
import os
import re

def extract_scripts(stage3_output, scripts_dir, cache_dir, run_id):
    """Extract bash scripts from LLM output.

    Handles format:
    SCRIPT: name.sh
    ```bash
    #!/usr/bin/env bash
    ...
    ```
    """

    scripts = []
    script_counter = 0

    lines = stage3_output.split('\n')
    in_code_block = False
    current_name = None
    current_script = []

    for line in lines:
        # Check for SCRIPT: name.sh pattern (OUTSIDE code blocks)
        # Handles: "SCRIPT: name.sh", "### SCRIPT: name.sh", "# SCRIPT: name.sh"
        if not in_code_block:
            match = re.match(r'^(?:#+\s*)?SCRIPT:\s*([a-zA-Z0-9_-]+\.sh)\s*$', line)
            if match:
                current_name = match.group(1)
                current_script = []
                continue

        # Check for code block start
        if line.strip() == '```bash' or line.strip() == '```':
            if not in_code_block:
                # Starting a code block
                in_code_block = True
                current_script = []
            else:
                # Ending a code block - save if we have a name
                if current_name:
                    script_content = '\n'.join(current_script)

                    if script_content.strip():
                        scripts.append((current_name, script_content))

                        # Save to file
                        script_path = os.path.join(scripts_dir, current_name)
                        with open(script_path, 'w') as f:
                            f.write(script_content + '\n')
                        os.chmod(script_path, 0o755)

                        # Save to cache
                        cache_path = os.path.join(cache_dir, f"{run_id}_script_{current_name.replace('.sh', '')}.txt")
                        with open(cache_path, 'w') as f:
                            f.write(script_content + '\n')

                        print(f"  Saved: {script_path}")

                current_name = None
                current_script = []
                in_code_block = False

        elif in_code_block:
            current_script.append(line)

    # Handle unclosed code blocks
    if current_name and current_script:
        clean_lines = [l for l in current_script if not re.match(r'\s*#?\s*SCRIPT:', l)]
        script_content = '\n'.join(clean_lines)

        if script_content.strip():
            scripts.append((current_name, script_content))

            script_path = os.path.join(scripts_dir, current_name)
            with open(script_path, 'w') as f:
                f.write(script_content + '\n')
            os.chmod(script_path, 0o755)

            cache_path = os.path.join(cache_dir, f"{run_id}_script_{current_name.replace('.sh', '')}.txt")
            with open(cache_path, 'w') as f:
                f.write(script_content + '\n')

            print(f"  Saved: {script_path}")

    return len(scripts)


if __name__ == '__main__':
    if len(sys.argv) != 5:
        print(f"Usage: {sys.argv[0]} <input_file> <output_dir> <cache_dir> <run_id>")
        sys.exit(1)

    input_file, scripts_dir, cache_dir, run_id = sys.argv[1:5]

    # Create directories
    os.makedirs(scripts_dir, exist_ok=True)
    os.makedirs(cache_dir, exist_ok=True)
    os.makedirs(os.path.join(cache_dir, 'northstar'), exist_ok=True)

    # Read input
    with open(input_file, 'r') as f:
        stage3_output = f.read()

    # Extract scripts
    count = extract_scripts(stage3_output, scripts_dir, cache_dir, run_id)

    # Log to northstar
    import datetime
    northstar_line = {
        "run_id": run_id,
        "event": "scripts_saved",
        "count": count,
        "dir": scripts_dir,
        "ts": datetime.datetime.utcnow().isoformat() + 'Z'
    }

    with open(os.path.join(cache_dir, 'northstar', f'{run_id}.jsonl'), 'a') as f:
        import json
        f.write(json.dumps(northstar_line) + '\n')

    print(f"Extracted {count} scripts")
