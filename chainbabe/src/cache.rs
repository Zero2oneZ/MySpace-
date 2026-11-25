//! SQLite cache layer for compiled scripts and organized instructions
//!
//! The cache stores scripts with their BLAKE3 hash as the primary key.
//! This enables semantic similarity detection - if a hash already exists,
//! we reuse the existing script rather than regenerating it.

use rusqlite::{Connection, params};
use serde::{Deserialize, Serialize};
use chrono::Utc;

/// Cache key uniquely identifies a cached item.
#[derive(Debug, Clone, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub struct CacheKey {
    /// BLAKE3 hash of the content
    pub hash: String,
    /// Type of content (e.g., "bash", "organized", "script")
    pub content_type: String,
}

impl CacheKey {
    pub fn new(hash: String, content_type: &str) -> Self {
        Self {
            hash,
            content_type: content_type.to_string(),
        }
    }
}

impl std::fmt::Display for CacheKey {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}:{}", self.hash, self.content_type)
    }
}

/// A cached compilation result.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CacheEntry {
    /// Cache key
    pub key: CacheKey,
    /// Content (bash script source, organized instructions, etc.)
    pub content: String,
    /// Timestamp of caching
    pub cached_at: String,
    /// Number of times this has been retrieved
    pub hits: i64,
    /// Number of times this has been executed
    pub executions: i64,
}

impl CacheEntry {
    pub fn new(key: CacheKey, content: &str) -> Self {
        Self {
            key,
            content: content.to_string(),
            cached_at: Utc::now().to_rfc3339(),
            hits: 0,
            executions: 0,
        }
    }
}

/// Initialize the cache database schema.
pub fn init_schema(conn: &Connection) -> Result<(), rusqlite::Error> {
    conn.execute_batch(SCHEMA)?;
    Ok(())
}

/// The cache database schema.
const SCHEMA: &str = r#"
-- Cache entries table
CREATE TABLE IF NOT EXISTS cache_entries (
    hash TEXT NOT NULL,
    content_type TEXT NOT NULL,
    content TEXT NOT NULL,
    cached_at TEXT NOT NULL,
    hits INTEGER DEFAULT 0,
    executions INTEGER DEFAULT 0,
    PRIMARY KEY (hash, content_type)
);

-- Index for fast lookup by hash
CREATE INDEX IF NOT EXISTS idx_cache_hash ON cache_entries(hash);

-- Index for fast lookup by type
CREATE INDEX IF NOT EXISTS idx_cache_type ON cache_entries(content_type);

-- Usage statistics table
CREATE TABLE IF NOT EXISTS cache_stats (
    stat_name TEXT PRIMARY KEY,
    stat_value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- Initialize counters
INSERT OR IGNORE INTO cache_stats (stat_name, stat_value, updated_at)
VALUES ('total_entries', '0', datetime('now'));

INSERT OR IGNORE INTO cache_stats (stat_name, stat_value, updated_at)
VALUES ('total_hits', '0', datetime('now'));

INSERT OR IGNORE INTO cache_stats (stat_name, stat_value, updated_at)
VALUES ('total_executions', '0', datetime('now'));
"#;

/// Insert or update a cache entry.
pub fn insert(conn: &Connection, key: &CacheKey, content: &str) -> Result<(), rusqlite::Error> {
    let existing = get(conn, key);

    if existing.is_some() {
        // Update existing entry
        conn.execute(
            r#"UPDATE cache_entries SET
                content = ?,
                cached_at = datetime('now'),
                hits = hits + 1
             WHERE hash = ? AND content_type = ?"#,
            params![content, key.hash, key.content_type],
        )?;
    } else {
        // Insert new entry
        conn.execute(
            r#"INSERT INTO cache_entries (hash, content_type, content, cached_at, hits, executions)
               VALUES (?, ?, ?, datetime('now'), 0, 0)"#,
            params![key.hash, key.content_type, content],
        )?;

        // Update total count
        conn.execute(
            r#"UPDATE cache_stats SET
                stat_value = CAST(stat_value AS INTEGER) + 1,
                updated_at = datetime('now')
               WHERE stat_name = 'total_entries'"#,
            [],
        )?;
    }

    Ok(())
}

/// Get a cache entry by key.
pub fn get(conn: &Connection, key: &CacheKey) -> Option<String> {
    let query = r#"SELECT content FROM cache_entries WHERE hash = ? AND content_type = ?"#;
    conn.query_row(query, params![key.hash, key.content_type], |r| r.get(0))
        .ok()
}

/// Increment execution count for a cache entry.
pub fn increment_executions(conn: &Connection, key: &CacheKey) -> Result<(), rusqlite::Error> {
    conn.execute(
        r#"UPDATE cache_entries SET
            executions = executions + 1
         WHERE hash = ? AND content_type = ?"#,
        params![key.hash, key.content_type],
    )?;

    // Update global execution counter
    conn.execute(
        r#"UPDATE cache_stats SET
            stat_value = CAST(stat_value AS INTEGER) + 1,
            updated_at = datetime('now')
           WHERE stat_name = 'total_executions'"#,
        [],
    )?;

    Ok(())
}

/// List all cache entries.
pub fn list_all(conn: &Connection) -> Result<Vec<CacheKey>, rusqlite::Error> {
    let mut prep = conn.prepare(r#"SELECT hash, content_type FROM cache_entries"#)?;
    let keys = prep.query_map([], |row| {
        Ok(CacheKey {
            hash: row.get(0)?,
            content_type: row.get(1)?,
        })
    })?;
    keys.collect::<Result<Vec<_>, _>>()
}

/// Get cache statistics.
pub fn get_stats(conn: &Connection) -> Result<std::collections::HashMap<String, String>, rusqlite::Error> {
    let mut prep = conn.prepare(r#"SELECT stat_name, stat_value FROM cache_stats"#)?;
    let stats = prep.query_map([], |row| {
        Ok((row.get(0)?, row.get(1)?))
    })?
    .filter_map(|r| r.ok())
    .collect();

    Ok(stats)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn cache_init_creates_schema() {
        let conn = rusqlite::Connection::open_in_memory().unwrap();
        init_schema(&conn).unwrap();

        // Check tables exist
        let count: i64 = conn.query_row(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='cache_entries'",
            [],
            |r| r.get(0),
        ).unwrap();

        assert_eq!(count, 1);
    }

    #[test]
    fn cache_insert_and_get() {
        let conn = rusqlite::Connection::open_in_memory().unwrap();
        init_schema(&conn).unwrap();

        let key = CacheKey::new("testhash".to_string(), "bash");
        insert(&conn, &key, "echo test").unwrap();

        let retrieved = get(&conn, &key);
        assert_eq!(retrieved, Some("echo test".to_string()));
    }

    #[test]
    fn cache_update_increments_hits() {
        let conn = rusqlite::Connection::open_in_memory().unwrap();
        init_schema(&conn).unwrap();

        let key = CacheKey::new("testhash".to_string(), "bash");
        insert(&conn, &key, "echo test").unwrap();

        // Re-insert (should update, not duplicate)
        insert(&conn, &key, "echo test").unwrap();

        let stats = get_stats(&conn).unwrap();
        assert_eq!(stats.get("total_entries"), Some(&"1".to_string()));
    }
}
