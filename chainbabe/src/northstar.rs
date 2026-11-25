//! Northstar — the append-only execution history log
//!
//! This is the "Northstar" database that tracks ALL executions.
//! It's append-only (never delete) and serves as the source of truth
//! for what has been executed and what the results were.

use rusqlite::{Connection, params};
use serde::{Deserialize, Serialize};
use chrono::Utc;

/// An entry in the execution history.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct HistoryEntry {
    /// Unique entry ID
    pub id: i64,
    /// Timestamp of execution
    pub timestamp: String,
    /// Original instructions that triggered execution
    pub instructions: String,
    /// Hash of the compiled script that was executed
    pub result_hash: String,
    /// Execution status ("success", "failure", "timeout") - None until execution completes
    #[serde(default)]
    pub status: Option<String>,
    /// Output from execution (truncated)
    #[serde(default)]
    pub output: String,
    /// Duration in milliseconds
    pub duration_ms: i64,
}

/// Northstar database for execution logging.
#[derive(Debug)]
pub struct Northstar {
    conn: Connection,
    /// Path to the database file
    pub path: String,
}

impl Northstar {
    /// Initialize northstar at the given path.
    pub fn init(path: &str) -> Result<Self, rusqlite::Error> {
        let conn = Connection::open(path)?;
        conn.execute_batch(SCHEMA)?;
        Ok(Self {
            conn,
            path: path.to_string(),
        })
    }

    /// Log an execution entry.
    pub fn log_execution(&mut self, instructions: &str, result_hash: &str) -> Result<(), rusqlite::Error> {
        let timestamp = Utc::now().to_rfc3339();
        // Use default values to avoid NULL handling issues in rusqlite 0.32
        self.conn.execute(
            r#"INSERT INTO executions (instructions, result_hash, status, output, duration_ms, timestamp, created_at)
               VALUES (?, ?, '', '', 0, ?, datetime('now'))"#,
            params![instructions, result_hash, timestamp],
        )?;
        Ok(())
    }

    /// Log an execution result.
    pub fn log_execution_result(
        &mut self,
        result_hash: &str,
        result: &crate::executor::ExecutionResult,
    ) -> Result<(), rusqlite::Error> {
        let status = if result.success { "success" } else { "failure" };
        let output = &result.output[..result.output.len().min(4096)]; // Truncate long outputs
        let duration_ms = result.duration_ms;

        self.conn.execute(
            r#"UPDATE executions SET
                status = ?,
                output = ?,
                duration_ms = ?
               WHERE result_hash = ? AND status IS NULL"#,
            params![status, output, duration_ms, result_hash],
        )?;

        Ok(())
    }

    /// Open a new connection and log an execution entry (for use with &self).
    pub fn log_execution_shared(&self, instructions: &str, result_hash: &str) -> Result<(), rusqlite::Error> {
        let conn = Connection::open(&self.path)?;
        let timestamp = Utc::now().to_rfc3339();
        // Use default values to avoid NULL handling issues in rusqlite 0.32
        conn.execute(
            r#"INSERT INTO executions (instructions, result_hash, status, output, duration_ms, timestamp, created_at)
               VALUES (?, ?, '', '', 0, ?, datetime('now'))"#,
            params![instructions, result_hash, timestamp],
        )?;
        Ok(())
    }

    /// Open a new connection and log an execution result (for use with &self).
    pub fn log_execution_result_shared(
        &self,
        result_hash: &str,
        result: &crate::executor::ExecutionResult,
    ) -> Result<(), rusqlite::Error> {
        let conn = Connection::open(&self.path)?;
        let status = if result.success { "success" } else { "failure" };
        let output = &result.output[..result.output.len().min(4096)];
        let duration_ms = result.duration_ms;

        conn.execute(
            r#"UPDATE executions SET
                status = ?,
                output = ?,
                duration_ms = ?
               WHERE result_hash = ? AND status IS NULL"#,
            params![status, output, duration_ms, result_hash],
        )?;

        Ok(())
    }

    /// Get recent history entries.
    pub fn history(&self, limit: usize) -> Result<Vec<HistoryEntry>, rusqlite::Error> {
        let mut prep = self.conn.prepare(
            r#"SELECT id, timestamp, instructions, result_hash,
                      IFNULL(status, ''), IFNULL(output, ''), IFNULL(duration_ms, 0)
               FROM executions
               ORDER BY timestamp DESC
               LIMIT ?"#,
        )?;

        let entries: Result<Vec<HistoryEntry>, rusqlite::Error> = prep.query_map(params![limit], |row| {
            // All columns are now guaranteed non-NULL due to IFNULL
            Ok(HistoryEntry {
                id: row.get(0)?,
                timestamp: row.get(1)?,
                instructions: row.get(2)?,
                result_hash: row.get(3)?,
                status: Some(row.get::<_, String>(4)?),
                output: row.get::<_, String>(5)?,
                duration_ms: row.get::<_, i64>(6)?,
            })
        })?
        .collect();

        entries
    }

    /// Get total execution count.
    pub fn execution_count(&self) -> Result<usize, rusqlite::Error> {
        let count: i64 = self.conn.query_row(
            "SELECT COUNT(*) FROM executions",
            [],
            |r| r.get(0),
        )?;
        Ok(count as usize)
    }

    /// Get success rate.
    pub fn success_rate(&self) -> Result<f64, rusqlite::Error> {
        let total: i64 = self.conn.query_row(
            "SELECT COUNT(*) FROM executions",
            [],
            |r| r.get(0),
        )?;

        if total == 0 {
            return Ok(1.0);
        }

        let success: i64 = self.conn.query_row(
            "SELECT COUNT(*) FROM executions WHERE status = 'success'",
            [],
            |r| r.get(0),
        )?;

        Ok(success as f64 / total as f64)
    }
}

/// Northstar database schema.
const SCHEMA: &str = r#"
-- Execution history table (append-only, never delete)
CREATE TABLE IF NOT EXISTS executions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    instructions TEXT NOT NULL,
    result_hash TEXT NOT NULL,
    status TEXT DEFAULT '',  -- Empty string instead of NULL
    output TEXT DEFAULT '',  -- Empty string instead of NULL
    duration_ms INTEGER DEFAULT 0,  -- 0 instead of NULL
    timestamp TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now'))
);

-- Index for fast lookup by result hash
CREATE INDEX IF NOT EXISTS idx_executions_hash ON executions(result_hash);

-- Index for fast filtering by status
CREATE INDEX IF NOT EXISTS idx_executions_status ON executions(status);

-- Index for fast time-based queries
CREATE INDEX IF NOT EXISTS idx_executions_timestamp ON executions(timestamp);

-- Statistics table
CREATE TABLE IF NOT EXISTS northstar_stats (
    stat_name TEXT PRIMARY KEY,
    stat_value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- Initialize counters
INSERT OR IGNORE INTO northstar_stats (stat_name, stat_value, updated_at)
VALUES ('total_executions', '0', datetime('now'));

INSERT OR IGNORE INTO northstar_stats (stat_name, stat_value, updated_at)
VALUES ('total_success', '0', datetime('now'));

INSERT OR IGNORE INTO northstar_stats (stat_name, stat_value, updated_at)
VALUES ('total_failure', '0', datetime('now'));
"#;

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn northstar_logs_executions() {
        let tmp = std::env::temp_dir().join("northstar-test.db");
        let _ = std::fs::remove_file(&tmp);

        let mut northstar = Northstar::init(tmp.to_str().unwrap()).unwrap();

        northstar.log_execution("echo hello", "abc123").unwrap();
        northstar.log_execution("echo world", "def456").unwrap();

        let history = northstar.history(10).unwrap();
        assert_eq!(history.len(), 2);
        assert_eq!(history[0].instructions, "echo world");
        assert_eq!(history[1].instructions, "echo hello");

        // Cleanup
        let _ = std::fs::remove_file(tmp);
    }

    #[test]
    fn northstar_updates_results() {
        let tmp = std::env::temp_dir().join("northstar-update-test.db");
        let _ = std::fs::remove_file(&tmp);

        let mut northstar = Northstar::init(tmp.to_str().unwrap()).unwrap();

        northstar.log_execution("echo test", "hash123").unwrap();

        // Simulate execution result
        let result = crate::executor::ExecutionResult {
            success: true,
            output: "test output\n".to_string(),
            stderr: "".to_string(),
            duration_ms: 150,
            exit_code: Some(0),
        };

        northstar.log_execution_result("hash123", &result).unwrap();

        // Verify update
        let history = northstar.history(10).unwrap();
        assert_eq!(history[0].status, "success");
        assert_eq!(history[0].output, "test output");
        assert_eq!(history[0].duration_ms, 150);

        // Cleanup
        let _ = std::fs::remove_file(tmp);
    }
}
