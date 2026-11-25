//! Compiler - converts organized instructions to bash scripts
//!
//! This module contains the compiler that takes organized instructions
//! from the orchestrator and produces executable bash scripts.

use serde::{Deserialize, Serialize};
use thiserror::Error;

use crate::hash::blake3_hash;

/// A compiled bash script with metadata.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CompiledScript {
    /// BLAKE3 hash of the script source
    pub hash: String,
    /// Bash script source code
    pub source: String,
    /// List of dependencies (external commands this script uses)
    pub dependencies: Vec<String>,
    /// Estimated execution time in milliseconds
    pub estimated_duration_ms: i64,
    /// Input file paths (if any)
    pub inputs: Vec<String>,
    /// Output file paths (if any)
    pub outputs: Vec<String>,
}

/// Compiler error types.
#[derive(Debug, Error)]
pub enum CompileError {
    #[error("empty instructions")]
    EmptyInstructions,

    #[error("invalid syntax at line {line}: {msg}")]
    Syntax { line: usize, msg: String },

    #[error("missing required field: {0}")]
    MissingField(String),

    #[error("unsupported instruction type: {0}")]
    UnsupportedType(String),
}

/// Organized instructions (from the orchestrator).
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OrganizedInstructions {
    /// Top-level goal or task
    pub goal: String,
    /// List of ordered steps
    pub steps: Vec<InstructionStep>,
    /// Checkpoints where validation should occur
    pub checkpoints: Vec<String>,
    /// Expected inputs
    pub inputs: Vec<String>,
    /// Expected outputs
    pub outputs: Vec<String>,
}

/// A single instruction step.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct InstructionStep {
    /// Step number
    pub order: usize,
    /// Step description
    pub description: String,
    /// Type of instruction
    pub step_type: StepType,
    /// Command or content
    pub content: String,
    /// Sub-steps (for complex operations)
    pub sub_steps: Vec<InstructionStep>,
}

/// Types of instruction steps.
#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq)]
pub enum StepType {
    /// Bash command execution
    Bash,
    /// File read operation
    ReadFile,
    /// File write operation
    WriteFile,
    /// Directory operation
    Dir,
    /// Variable assignment
    Var,
    /// Conditional
    If,
    /// Loop
    Loop,
    /// Function definition
    Function,
    /// Checkpoint/validation
    Checkpoint,
    /// Unknown/unspecified
    Unknown,
}

impl StepType {
    pub fn from_str(s: &str) -> Self {
        match s.to_lowercase().as_str() {
            "bash" | "command" | "exec" => StepType::Bash,
            "read" | "readfile" => StepType::ReadFile,
            "write" | "writefile" => StepType::WriteFile,
            "dir" | "directory" => StepType::Dir,
            "var" | "variable" => StepType::Var,
            "if" | "conditional" => StepType::If,
            "loop" | "repeat" => StepType::Loop,
            "func" | "function" => StepType::Function,
            "checkpoint" | "validate" => StepType::Checkpoint,
            _ => StepType::Unknown,
        }
    }
}

/// Compile organized instructions into a bash script.
pub fn compile(organized: &OrganizedInstructions) -> Result<CompiledScript, CompileError> {
    if organized.steps.is_empty() {
        return Err(CompileError::EmptyInstructions);
    }

    let mut source = String::new();
    let mut dependencies = Vec::new();
    let mut inputs = Vec::new();
    let mut outputs = Vec::new();

    // Header
    source.push_str("#!/bin/bash\n");
    source.push_str("# Auto-generated script from chainbabe\n");
    source.push_str(&format!("# Goal: {}\n", organized.goal));
    source.push_str(&format!("# Generated: {}\n", chrono::Utc::now().to_rfc3339()));
    source.push('\n');

    // Step 1: Setup and error handling
    source.push_str("set -euo pipefail\n");
    source.push('\n');

    // Step 2: Process each step
    for step in &organized.steps {
        compile_step(step, &mut source, &mut dependencies, &mut inputs, &mut outputs);
    }

    // Step 3: Add checkpoint validations
    for checkpoint in &organized.checkpoints {
        source.push_str(&format!("# Checkpoint: {}\n", checkpoint));
        source.push_str(&format!("echo \"Checkpoint: {}\"\n", checkpoint));
        source.push('\n');
    }

    // Calculate hash of the source
    let hash = blake3_hash(&source);

    // Estimate duration (simplified: 100ms per step + 50ms per command)
    let estimated_duration_ms = (organized.steps.len() as i64 * 100) + (dependencies.len() as i64 * 50);

    Ok(CompiledScript {
        hash,
        source,
        dependencies,
        estimated_duration_ms,
        inputs,
        outputs,
    })
}

/// Compile a single instruction step.
fn compile_step(
    step: &InstructionStep,
    source: &mut String,
    dependencies: &mut Vec<String>,
    inputs: &mut Vec<String>,
    outputs: &mut Vec<String>,
) {
    match step.step_type {
        StepType::Bash => {
            source.push_str(&format!("{}\n", step.content));
        }
        StepType::ReadFile => {
            source.push_str(&format!("if [[ -f \"{}\" ]]; then\n", step.content));
            source.push_str(&format!("    cat \"{}\"\n", step.content));
            source.push_str("else\n");
            source.push_str(&format!("    echo \"Error: File not found: {}\" >&2\n", step.content));
            source.push_str("    exit 1\n");
            source.push_str("fi\n");
            inputs.push(step.content.clone());
        }
        StepType::WriteFile => {
            // content contains the file path, we need to infer the command
            if let Some((file, cmd)) = step.content.split_once('=') {
                source.push_str(&format!("{} > \"{}\"\n", cmd.trim(), file.trim()));
                outputs.push(file.trim().to_string());
            } else {
                source.push_str(&format!("echo \"{}\" > \"{}\"\n", "output", step.content));
                outputs.push(step.content.clone());
            }
        }
        StepType::Dir => {
            source.push_str(&format!("mkdir -p \"{}\"\n", step.content));
        }
        StepType::Var => {
            if let Some((name, value)) = step.content.split_once('=') {
                source.push_str(&format!("{}={}\n", name.trim(), value.trim()));
            } else {
                source.push_str(&format!("{}=\"\"\n", step.content));
            }
        }
        StepType::If => {
            source.push_str(&format!("if {}\n", step.content));
            source.push_str("then\n");
            for sub in &step.sub_steps {
                compile_step(sub, source, dependencies, inputs, outputs);
            }
            source.push_str("fi\n");
        }
        StepType::Loop => {
            source.push_str(&format!("while {}\n", step.content));
            source.push_str("do\n");
            for sub in &step.sub_steps {
                compile_step(sub, source, dependencies, inputs, outputs);
            }
            source.push_str("done\n");
        }
        StepType::Function => {
            // Parse function definition: name() { body }
            if let Some((name, _body)) = step.content.split_once('(') {
                source.push_str(&format!("{}()\n", name.trim()));
                source.push_str("{}\n");
            } else {
                source.push_str(&format!("{}() {{\n", step.content));
                source.push_str("}\n");
            }
        }
        StepType::Checkpoint => {
            source.push_str(&format!("# Checkpoint: {}\n", step.content));
            source.push_str(&format!("echo \"Checkpoint reached: {}\"\n", step.content));
        }
        StepType::Unknown => {
            source.push_str(&format!("# Unknown: {}\n", step.content));
        }
    }

    // Track dependencies (commands used in the step)
    track_dependencies(&step.content, dependencies);
}

/// Track which external commands are used.
fn track_dependencies(content: &str, dependencies: &mut Vec<String>) {
    // Simple heuristic: extract words that look like commands
    // In production, use proper shell parsing
    let commands = [
        "echo", "cat", "mkdir", "cp", "mv", "rm", "ls", "cd", "chmod", "chown",
        "grep", "awk", "sed", "find", "xargs", "curl", "wget", "git", "docker",
        "python", "python3", "node", "npm", "yarn", "jq", "base64", "sort", "uniq",
        "tee", "head", "tail", "wc", "test", "[", "sha256sum", "md5sum", "blake3sum",
    ];

    for cmd in commands {
        if content.contains(cmd) {
            if !dependencies.contains(&cmd.to_string()) {
                dependencies.push(cmd.to_string());
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn compile_empty_instructions_errors() {
        let instructions = OrganizedInstructions {
            goal: "test".to_string(),
            steps: Vec::new(),
            checkpoints: Vec::new(),
            inputs: Vec::new(),
            outputs: Vec::new(),
        };

        assert!(compile(&instructions).is_err());
    }

    #[test]
    fn compile_simple_bash() {
        let instructions = OrganizedInstructions {
            goal: "print hello".to_string(),
            steps: vec![InstructionStep {
                order: 1,
                description: "Print hello world".to_string(),
                step_type: StepType::Bash,
                content: "echo 'hello world'".to_string(),
                sub_steps: Vec::new(),
            }],
            checkpoints: Vec::new(),
            inputs: Vec::new(),
            outputs: Vec::new(),
        };

        let compiled = compile(&instructions).unwrap();
        assert!(compiled.source.contains("echo 'hello world'"));
        assert!(!compiled.hash.is_empty());
    }

    #[test]
    fn compile_with_dependencies() {
        let instructions = OrganizedInstructions {
            goal: "process files".to_string(),
            steps: vec![InstructionStep {
                order: 1,
                description: "Find and process files".to_string(),
                step_type: StepType::Bash,
                content: "find . -name '*.txt' | xargs grep pattern".to_string(),
                sub_steps: Vec::new(),
            }],
            checkpoints: Vec::new(),
            inputs: Vec::new(),
            outputs: Vec::new(),
        };

        let compiled = compile(&instructions).unwrap();
        // Should have found find, xargs, grep as dependencies
        assert!(compiled.dependencies.contains(&"find".to_string()));
        assert!(compiled.dependencies.contains(&"xargs".to_string()));
        assert!(compiled.dependencies.contains(&"grep".to_string()));
    }
}
