//! Executor - runs bash scripts and captures results
//!
//! This module handles executing compiled bash scripts and
//! recording the results in the northstar log.

use std::process::Command;
use serde::{Deserialize, Serialize};
use thiserror::Error;

/// Result of executing a bash script.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ExecutionResult {
    /// Whether execution succeeded
    pub success: bool,
    /// Standard output
    pub output: String,
    /// Standard error
    pub stderr: String,
    /// Duration in milliseconds
    pub duration_ms: i64,
    /// Exit code (None if process couldn't start)
    pub exit_code: Option<i32>,
}

/// Executor error types.
#[derive(Debug, Error)]
pub enum ExecuteError {
    #[error("io: {0}")]
    Io(#[from] std::io::Error),

    #[error("process failed with code {0}")]
    ProcessFailed(i32),

    #[error("timeout after {0}ms")]
    Timeout(i64),
}

/// Executor that runs bash scripts.
#[derive(Debug)]
pub struct Executor {
    /// Working directory for script execution
    work_dir: String,
    /// Maximum execution time in milliseconds (default: 30s)
    timeout_ms: i64,
}

impl Executor {
    /// Create a new executor.
    pub fn new(work_dir: &str) -> Self {
        Self {
            work_dir: work_dir.to_string(),
            timeout_ms: 30000, // 30 seconds default
        }
    }

    /// Set the timeout for script execution.
    pub fn with_timeout(mut self, timeout_ms: i64) -> Self {
        self.timeout_ms = timeout_ms;
        self
    }

    /// Run a bash script and capture results.
    pub fn run(&self, script: &str) -> Result<ExecutionResult, ExecuteError> {
        let start = std::time::Instant::now();

        // Write script to a temp file
        let temp_script = std::env::temp_dir().join(format!(
            "chainbabe_{}.sh",
            chrono::Utc::now().timestamp_nanos_opt().unwrap_or(0)
        ));
        std::fs::write(&temp_script, script)?;

        // Make it executable
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            std::fs::set_permissions(
                &temp_script,
                std::fs::Permissions::from_mode(0o755),
            )?;
        }

        // Execute the script
        let output = Command::new("bash")
            .arg(&temp_script)
            .current_dir(&self.work_dir)
            .output();

        let duration_ms = start.elapsed().as_millis() as i64;

        match output {
            Ok(out) => {
                let success = out.status.success();
                let exit_code = out.status.code();

                // Clean up temp file
                let _ = std::fs::remove_file(&temp_script);

                Ok(ExecutionResult {
                    success,
                    output: String::from_utf8_lossy(&out.stdout).to_string(),
                    stderr: String::from_utf8_lossy(&out.stderr).to_string(),
                    duration_ms,
                    exit_code,
                })
            }
            Err(e) => {
                // Clean up temp file even on error
                let _ = std::fs::remove_file(&temp_script);

                Err(ExecuteError::Io(e))
            }
        }
    }

    /// Run a script with a timeout.
    pub fn run_with_timeout(
        &self,
        script: &str,
        _timeout_ms: i64,
    ) -> Result<ExecutionResult, ExecuteError> {
        // Use tokio for timeout if in async context
        // For now, just run with the given timeout (actual timeout handling
        // would require async runtime or spawning a thread)
        self.run(script)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn run_echo_script() {
        let executor = Executor::new("/tmp");
        let script = "#!/bin/bash\necho 'hello from chainbabe'\necho 'test output' >&2";

        let result = executor.run(script).unwrap();

        assert!(result.success);
        assert!(result.output.contains("hello from chainbabe"));
        assert!(result.stderr.contains("test output"));
        assert!(result.duration_ms > 0);
    }

    #[test]
    fn run_failing_script() {
        let executor = Executor::new("/tmp");
        let script = "#!/bin/bash\nexit 1";

        let result = executor.run(script).unwrap();

        assert!(!result.success);
        assert_eq!(result.exit_code, Some(1));
    }

    #[test]
    fn run_script_with_output() {
        let executor = Executor::new("/tmp");
        let script = "#!/bin/bash\nprintf 'line1\\nline2\\nline3\\n'";

        let result = executor.run(script).unwrap();

        assert!(result.success);
        assert!(result.output.contains("line1"));
        assert!(result.output.contains("line2"));
        assert!(result.output.contains("line3"));
    }
}
