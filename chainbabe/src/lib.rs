//! chainbabe — Semantic instruction compiler with dual-model orchestration
//!
//! ## Architecture
//!
//! ```text
//! ┌─────────────────────────────────────────────────────────────────────┐
//! │                          CHAINBABE ORCHESTRATOR                     │
//! ├─────────────────────────────────────────────────────────────────────┤
//! │                                                                       │
//! │   USER INPUT (semantic instructions)                                │
//! │        │                                                              │
//! │        ▼                                                              │
//! │   ┌─────────────────┐     ┌─────────────────┐                       │
//! │   │  ORCHESTRATOR   │     │  COMPILER       │                       │
//! │   │  (qwen2.5:0.5b) │     │  (qwen2.5-coder │                       │
//! │   │  - organize     │     │   :1.5b)        │                       │
//! │   │  - reorder      │     │  - code bash    │                       │
//! │   │  - checkpoint   │     │  - cache        │                       │
//! │   └────────┬────────┘     └────────┬────────┘                       │
//! │            │                      │                                 │
//! │            ▼                      ▼                                 │
//! │   ┌─────────────────┐    ┌─────────────────┐                       │
//! │   │  HASH ENGINE    │    │  CACHE LAYER    │                       │
//! │   │  (BLAKE3)       │    │  (SQLite)       │                       │
//! │   └────────┬────────┘    └────────┬────────┘                       │
//! │            │                      │                                 │
//! │            ▼                      ▼                                 │
//! │   ┌─────────────────┐    ┌─────────────────┐                       │
//! │   │   HASH LOOP     │◄───┤  FUNCTION LIB   │                       │
//! │   │  (infinite)     │    │  (semantic)     │                       │
//! │   └────────┬────────┘    └─────────────────┘                       │
//! │            │                                                        │
//! │            ▼                                                        │
//! │   ┌─────────────────┐                                               │
//! │   │   EXECUTOR      │                                               │
//! │   │  - run bash     │                                               │
//! │   │  - stash output │                                               │
//! │   │  - log history  │                                               │
//! │   └─────────────────┘                                               │
//! │                                                                       │
//! └─────────────────────────────────────────────────────────────────────┘
//!                                                                       │
//!   Northstar:  Database of all executions (append-only, never delete)
//!   Pattern:    Semantic similarity → reuse, not rewrite
//!   Hash:       BLAKE3 content address for all blocks
//!   Loop:       Constant reorganization via hash-based scanning
//! ```

#![forbid(unsafe_code)]

use std::path::PathBuf;
use std::sync::Arc;
use rusqlite::Connection;
use thiserror::Error;
use tracing::info;

// ─────────────────────────────────────────────────────────────────────────
// Public API
// ─────────────────────────────────────────────────────────────────────────

pub mod compiler;
pub mod executor;
pub mod hash;
pub mod cache;
pub mod orchestrator;
pub mod northstar;

pub use compiler::{compile, CompileError, CompiledScript, OrganizedInstructions};
pub use executor::{Executor, ExecutionResult};
pub use hash::{blake3_hash, HashEngine, HashBlock, invert_string, invert_char, invert_hash, hash_loop_decompile, hash_loop_invert, decode_hash_to_text};
pub use cache::{CacheKey, insert, get, list_all, get_stats, init_schema};
pub use orchestrator::{Orchestrator, OrchestratorError, InstructionStep, StepType};
pub use northstar::{Northstar, HistoryEntry};

// Re-export for convenience
pub use serde_json;

/// Global state for the chainbabe runtime.
/// Lives in `~/.gently/chainbabe/`.
#[derive(Debug)]
pub struct Chainbabe {
    /// SQLite connection for cache layer
    cache: Arc<Connection>,
    /// Northstar log (append-only execution history)
    northstar: Northstar,
    /// Path to storage directory
    storage_path: PathBuf,
    /// Active orchestrator (handles dual-model orchestration)
    orchestrator: Orchestrator,
}

impl Chainbabe {
    /// Create a new Chainbabe instance scoped to project_id.
    /// Storage path: `~/.gently/chainbabe/<project_id>/`
    pub fn new(project_id: &str) -> Result<Self, ChainbabeError> {
        let home = dirs::home_dir()
            .ok_or_else(|| ChainbabeError::Config("no home directory".into()))?;
        let storage_path = home
            .join(".gently")
            .join("chainbabe")
            .join(project_id);

        std::fs::create_dir_all(&storage_path)
            .map_err(|e| ChainbabeError::Io(e, "create storage dir".into()))?;

        // Open SQLite for cache layer (also creates if not exists)
        let cache_path = storage_path.join("cache.db");
        let cache = Connection::open(&cache_path)
            .map_err(|e| ChainbabeError::Db(e, "open cache".into()))?;

        // Initialize cache schema
        cache::init_schema(&cache)
            .map_err(|e| ChainbabeError::Db(e, "init cache schema".into()))?;

        // Initialize northstar (execution log)
        let northstar_path = storage_path.join("northstar.db");
        let northstar = Northstar::init(northstar_path.to_str().ok_or_else(|| ChainbabeError::Config("invalid path".into()))?)
            .map_err(|e| ChainbabeError::Db(e, "init northstar".into()))?;

        // Initialize orchestrator with dual-model config
        let orchestrator = match Orchestrator::new(
            "qwen2.5:0.5b",
            "qwen2.5-coder:1.5b",
            storage_path.to_str().ok_or_else(|| ChainbabeError::Config("invalid path".into()))?,
        ) {
            Ok(o) => o,
            Err(e) => return Err(ChainbabeError::Orchestrator(e.to_string())),
        };

        Ok(Self {
            cache: Arc::new(cache),
            northstar,
            storage_path,
            orchestrator,
        })
    }

    /// Submit semantic instructions for compilation.
    /// Returns hash of the compiled result.
    pub fn submit(&self, instructions: &str) -> Result<String, ChainbabeError> {
        info!("submitting instructions to chainbabe");

        // Step 1: Orchestrator organizes/reorders instructions
        let organized = match self.orchestrator.organize(instructions) {
            Ok(o) => o,
            Err(e) => return Err(ChainbabeError::Orchestrator(e.to_string())),
        };

        // Step 2: Compile organized instructions to bash
        let compiled = match compile(&organized) {
            Ok(c) => c,
            Err(e) => return Err(ChainbabeError::Compiler(e)),
        };

        // Step 3: Hash the compiled script
        let script_hash = blake3_hash(&compiled.source);

        // Step 4: Cache the script (if not already cached)
        let cache_key = CacheKey::new(script_hash.clone(), "bash");
        if let Err(e) = insert(self.cache.as_ref(), &cache_key, &compiled.source) {
            return Err(ChainbabeError::Db(e, "insert cache".into()));
        }

        // Step 5: Log to northstar
        if let Err(e) = self.northstar.log_execution_shared(&instructions, &script_hash) {
            return Err(ChainbabeError::Db(e, "log northstar".into()));
        }

        Ok(script_hash)
    }

    /// Execute a script by its hash.
    /// Returns execution result and records to northstar.
    pub fn execute(&self, script_hash: &str) -> Result<ExecutionResult, ChainbabeError> {
        let cache_key = CacheKey::new(script_hash.to_string(), "bash");

        // Retrieve from cache
        let source = cache::get(self.cache.as_ref(), &cache_key)
            .ok_or_else(|| ChainbabeError::Cache("script not found".into()))?;

        // Execute via executor
        let executor = Executor::new(self.storage_path.to_str().ok_or_else(|| ChainbabeError::Config("invalid path".into()))?);
        let result = match executor.run(&source) {
            Ok(r) => r,
            Err(e) => return Err(ChainbabeError::Cache(format!("execution failed: {}", e))),
        };

        // Log to northstar
        if let Err(e) = self.northstar.log_execution_result_shared(script_hash, &result) {
            return Err(ChainbabeError::Db(e, "log result".into()));
        }

        Ok(result)
    }

    /// Get execution history from northstar.
    pub fn history(&self, limit: usize) -> Result<Vec<HistoryEntry>, ChainbabeError> {
        self.northstar.history(limit)
            .map_err(|e| ChainbabeError::Db(e, "fetch history".into()))
    }

    /// Get all cached scripts.
    pub fn cached_scripts(&self) -> Result<Vec<CacheKey>, ChainbabeError> {
        list_all(self.cache.as_ref())
            .map_err(|e| ChainbabeError::Db(e, "list cache".into()))
    }

    /// Get path to storage directory.
    pub fn storage_path(&self) -> &PathBuf {
        &self.storage_path
    }

    /// Get orchestrator reference.
    pub fn orchestrator(&self) -> &Orchestrator {
        &self.orchestrator
    }
}

// ─────────────────────────────────────────────────────────────────────────
// Error types
// ─────────────────────────────────────────────────────────────────────────

#[derive(Debug, Error)]
pub enum ChainbabeError {
    #[error("config: {0}")]
    Config(String),

    #[error("io: {1}: {0}")]
    Io(#[source] std::io::Error, String),

    #[error("db: {1}: {0}")]
    Db(#[source] rusqlite::Error, String),

    #[error("cache: {0}")]
    Cache(String),

    #[error("orchestrator: {0}")]
    Orchestrator(String),

    #[error("compiler: {0}")]
    Compiler(#[from] CompileError),
}

// ─────────────────────────────────────────────────────────────────────────
// Module declarations
// ─────────────────────────────────────────────────────────────────────────

/// Initialize a new chainbabe instance and run it.
/// This is the entry point for CLI usage.
pub fn init_and_run(project_id: &str) -> Result<(), ChainbabeError> {
    let chainbabe = Chainbabe::new(project_id)?;

    // Main CLI loop
    let mut cli = clap::Command::new("chainbabe")
        .version(env!("CARGO_PKG_VERSION"))
        .author("Zero2oneZ")
        .about("Semantic instruction compiler with dual-model orchestration")
        .subcommand(
            clap::Command::new("submit")
                .about("Submit semantic instructions for compilation")
                .arg(clap::Arg::new("instructions").required(true).num_args(1..)),
        )
        .subcommand(
            clap::Command::new("execute")
                .about("Execute a script by its hash")
                .arg(clap::Arg::new("hash").required(true).num_args(1)),
        )
        .subcommand(
            clap::Command::new("history")
                .about("Show execution history")
                .arg(clap::Arg::new("limit").long("limit").default_value("10")),
        )
        .subcommand(
            clap::Command::new("decompile")
                .about("Decompile hash loop - shows inverted hash iterations")
                .arg(clap::Arg::new("hash").long("hash").required(true).num_args(1))
                .arg(clap::Arg::new("iterations").long("iterations").default_value("5")),
        );

    let matches = cli.clone().get_matches();

    match matches.subcommand() {
        Some(("submit", sub_matches)) => {
            let instructions = sub_matches.get_one::<String>("instructions")
                .ok_or_else(|| ChainbabeError::Config("instructions required".into()))?;
            let hash = chainbabe.submit(instructions)?;
            println!("Hash: {}", hash);
        }
        Some(("execute", sub_matches)) => {
            let hash = sub_matches.get_one::<String>("hash")
                .ok_or_else(|| ChainbabeError::Config("hash required".into()))?;
            match chainbabe.execute(hash) {
                Ok(result) => println!("Result: {:?}", result),
                Err(e) => eprintln!("Error: {}", e),
            }
        }
        Some(("history", sub_matches)) => {
            let limit: usize = sub_matches.get_one::<String>("limit")
                .unwrap().parse().unwrap_or(10);
            for entry in chainbabe.history(limit)? {
                println!("{}: {} -> {}", entry.timestamp, entry.instructions, entry.result_hash);
            }
        }
        Some(("decompile", sub_matches)) => {
            let hash = sub_matches.get_one::<String>("hash")
                .ok_or_else(|| ChainbabeError::Config("hash required".into()))?;
            let iterations: usize = sub_matches.get_one::<String>("iterations")
                .unwrap().parse().unwrap_or(5);

            println!("Hash Loop Decompile: {}", hash);
            println!("Iterations: {}", iterations);
            println!("---");

            let results = chainbabe.orchestrator.hash_loop_decompile(hash, iterations);
            for (i, content) in results.iter().enumerate() {
                println!("[Iteration {}]\n{}", i, content);
            }
        }
        _ => {
            cli.print_help().map_err(|e| ChainbabeError::Io(e, "print help".into()))?;
        }
    }

    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn hash_is_deterministic() {
        let input1 = "print hello world";
        let input2 = "print hello world";
        let input3 = "print hello world!";

        let hash1 = blake3_hash(input1);
        let hash2 = blake3_hash(input2);
        let hash3 = blake3_hash(input3);

        assert_eq!(hash1, hash2, "same input produces same hash");
        assert_ne!(hash1, hash3, "different input produces different hash");
    }

    #[test]
    fn init_creates_storage_dir() {
        let tmp = std::env::temp_dir().join("chainbabe-test");
        let _ = std::fs::remove_dir_all(&tmp);

        let chainbabe = Chainbabe::new("test-init").unwrap();
        let path = chainbabe.storage_path();

        assert!(path.ends_with("test-init"));
        assert!(path.exists());

        // Cleanup
        let _ = std::fs::remove_dir_all(tmp);
    }
}
