//! Orchestrator - dual-model orchestration with Qwen2.5
//!
//! This module manages two Qwen2.5 models:
//! 1. Organizer (qwen2.5:0.5b) - organizes, reorders, checkpoints instructions
//! 2. Compiler (qwen2.5-coder:1.5b) - converts organized instructions to bash

use thiserror::Error;

// Re-export types from compiler module to avoid duplication
pub use crate::compiler::{CompiledScript, CompileError, InstructionStep, OrganizedInstructions, StepType};
use crate::hash::{blake3_hash, invert_string, hash_loop_decompile, hash_loop_invert, decode_hash_to_text};

/// Orchestrator error types.
#[derive(Debug, Error)]
pub enum OrchestratorError {
    #[error("API call failed: {0}")]
    Api(String),

    #[error("timeout after {0}ms")]
    Timeout(i64),

    #[error("model not available: {0}")]
    ModelNotAvailable(String),

    #[error("validation: {0}")]
    Validation(String),
}

/// The orchestrator that coordinates the dual-model workflow.
#[derive(Debug, Clone)]
pub struct Orchestrator {
    /// Organizer model (qwen2.5:0.5b)
    organizer_model: String,
    /// Compiler model (qwen2.5-coder:1.5b)
    compiler_model: String,
    /// Storage path for temporary files
    storage_path: String,
}

impl Orchestrator {
    /// Create a new orchestrator.
    pub fn new(organizer_model: &str, compiler_model: &str, storage_path: &str) -> Result<Self, OrchestratorError> {
        // Verify models are available (simple check - in production, query Ollama API)
        if !Self::model_available(organizer_model) {
            return Err(OrchestratorError::ModelNotAvailable(organizer_model.to_string()));
        }
        if !Self::model_available(compiler_model) {
            return Err(OrchestratorError::ModelNotAvailable(compiler_model.to_string()));
        }

        Ok(Self {
            organizer_model: organizer_model.to_string(),
            compiler_model: compiler_model.to_string(),
            storage_path: storage_path.to_string(),
        })
    }

    /// Check if a model is available via Ollama.
    fn model_available(model: &str) -> bool {
        // In production, this would query the Ollama API
        // For now, assume all qwen2.5 models are available
        model.starts_with("qwen2.5")
    }

    /// Organize and reorder user instructions.
    /// The organizer model structures the instructions into a logical order
    /// with checkpoints and sub-steps.
    ///
    /// Falls back to creating a simple bash step if no AI API is available.
    pub fn organize(&self, instructions: &str) -> Result<OrganizedInstructions, OrchestratorError> {
        // In production, this would:
        // 1. Call the organizer model via Ollama API
        // 2. Parse the JSON response
        // 3. Return OrganizedInstructions

        // Fallback: Create a simple bash step from the instructions
        // This allows chainbabe to work without an actual AI connection
        let goal = if instructions.len() > 50 {
            instructions[..50].to_string() + "..."
        } else {
            instructions.to_string()
        };

        Ok(OrganizedInstructions {
            goal,
            steps: vec![InstructionStep {
                order: 1,
                description: "Execute user instructions".to_string(),
                step_type: StepType::Bash,
                content: instructions.trim().to_string(),
                sub_steps: Vec::new(),
            }],
            checkpoints: Vec::new(),
            inputs: Vec::new(),
            outputs: Vec::new(),
        })
    }

    /// Reorganize existing organized instructions.
    /// This is used in the hash loop to continuously optimize the script.
    /// The inverted loop decompiles by inverting char values (letters↔numbers).
    pub fn reorganize(&self, instructions: &str) -> Result<String, OrchestratorError> {
        // Get the hash of the current content
        let current_hash = blake3_hash(instructions);

        // Invert the characters to create a new organized version
        // This creates the "inverted loop" - decompiling back to organized form
        let inverted = invert_string(instructions);

        // Hash the inverted version and check if it's different
        let inverted_hash = blake3_hash(&inverted);

        // If different, return the inverted version as the new organized form
        // This creates a self-referential loop that keeps reorganizing
        if current_hash != inverted_hash {
            Ok(inverted)
        } else {
            // If same, use original (no-op case)
            Ok(instructions.to_string())
        }
    }

    /// Generate a hash loop decompile - creates iterations of inverted hash values
    /// This is used for the infinite loop that decompiles the generated content
    pub fn hash_loop_decompile(&self, initial_hash: &str, iterations: usize) -> Vec<String> {
        hash_loop_decompile(initial_hash, iterations)
    }

    /// Generate a sequence of inverted hashes starting from a hash
    pub fn hash_loop_invert(&self, start_hash: &str, iterations: usize) -> Vec<String> {
        hash_loop_invert(start_hash, iterations)
    }

    /// Decode a hash back to readable text
    pub fn decode_hash_to_text(&self, hash: &str) -> String {
        decode_hash_to_text(hash)
    }

    /// Format prompt for the organizer model.
    fn format_organizer_prompt(&self, instructions: &str) -> String {
        format!(r#"Organize these instructions into a logical order with checkpoints.
Return JSON with:
- goal: the main objective
- steps: array of ordered steps, each with description and type
- checkpoints: validation points

Instructions:
{}

Return ONLY the JSON object."#, instructions)
    }

    /// Format prompt for the compiler model.
    fn format_compiler_prompt(&self, organized: &str) -> String {
        format!(r#"Convert these organized instructions into a bash script.
- Use set -euo pipefail
- Add error handling
- Add checkpoint messages
- Return only the script, no explanation

Organized instructions:
{}

Return ONLY the bash script."#, organized)
    }

    /// Get the organizer model name.
    pub fn organizer_model(&self) -> &str {
        &self.organizer_model
    }

    /// Get the compiler model name.
    pub fn compiler_model(&self) -> &str {
        &self.compiler_model
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn orchestrator_creates() {
        let storage = std::env::temp_dir().join("chainbabe-test");
        let _ = std::fs::create_dir_all(&storage);

        let orch = Orchestrator::new(
            "qwen2.5:0.5b",
            "qwen2.5-coder:1.5b",
            storage.to_str().unwrap(),
        );

        assert!(orch.is_ok());
    }

    #[test]
    fn organizer_model_name() {
        let storage = std::env::temp_dir().join("chainbabe-test2");
        let _ = std::fs::create_dir_all(&storage);

        let orch = Orchestrator::new(
            "qwen2.5:0.5b",
            "qwen2.5-coder:1.5b",
            storage.to_str().unwrap(),
        ).unwrap();

        assert_eq!(orch.organizer_model(), "qwen2.5:0.5b");
        assert_eq!(orch.compiler_model(), "qwen2.5-coder:1.5b");
    }
}
