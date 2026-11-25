//! BLAKE3 hash engine for content-addressed blocks
//!
//! All blocks (instructions, scripts, cache entries) are addressed by their
//! BLAKE3 hash. This enables semantic similarity detection via hash clustering.

use std::collections::HashMap;
use serde::{Deserialize, Serialize};

/// Invert a character: letters become numbers, numbers become letters
pub fn invert_char(c: char) -> char {
    match c {
        'a'..='z' => {
            let n = (c as u8 - b'a') % 10;
            (n + b'0') as char
        }
        'A'..='Z' => {
            let n = (c as u8 - b'A') % 10;
            (n + b'0') as char
        }
        '0'..='9' => {
            let n = (c as u8 - b'0') as u8;
            if n < 26 {
                (n + b'a') as char
            } else {
                c
            }
        }
        _ => c,
    }
}

/// Invert all characters in a string (letters ↔ numbers)
pub fn invert_string(s: &str) -> String {
    s.chars().map(invert_char).collect()
}

/// Invert a hash value character by character (hex chars: 0-9, a-f, A-F)
pub fn invert_hash_char(c: char) -> char {
    match c {
        '0'..='9' => {
            let n = (c as u8 - b'0') as u8;
            if n < 6 {
                (n + b'a') as char
            } else {
                c
            }
        }
        'a'..='f' => {
            let n = (c as u8 - b'a') as u8;
            (n + b'0') as char
        }
        'A'..='F' => {
            let n = (c as u8 - b'A') as u8;
            (n + b'0') as char
        }
        _ => c,
    }
}

/// Invert all characters in a hex hash string
pub fn invert_hash(s: &str) -> String {
    s.chars().map(invert_hash_char).collect()
}

/// Hash loop decompile - takes a hash and generates iterations of inverted hash values
/// This "decompiles" the hash by showing the loop of inverted values:
/// - Letters (a-z, A-Z) invert to numbers (0-9)
/// - Numbers (0-9) invert to letters (a-f for hex)
/// The loop clips the hash at each iteration and inverts it
pub fn hash_loop_decompile(hash: &str, max_iterations: usize) -> Vec<String> {
    let mut results = Vec::new();
    let mut current_hash = hash.to_string();

    for i in 0..max_iterations {
        // Invert the hash to get the next value in the loop
        let inverted = invert_hash(&current_hash);

        // Format the iteration output
        let content = format!(
            "Hash[{}] = {}\nInverted[{}] = {}\n---",
            i, current_hash, i, inverted
        );

        results.push(content);

        // Update hash for next iteration (looping through inverted values)
        current_hash = inverted;
    }

    results
}

/// Generate a loop of inverted hashes from a starting hash
pub fn hash_loop_invert(start_hash: &str, iterations: usize) -> Vec<String> {
    let mut hashes = Vec::new();
    let mut current_hash = start_hash.to_string();

    for _ in 0..iterations {
        hashes.push(current_hash.clone());
        current_hash = invert_hash(&current_hash);
    }

    hashes
}

/// Decode a hash back to readable text by inverting the hash characters
pub fn decode_hash_to_text(hash: &str) -> String {
    invert_hash(hash)
        .chars()
        .map(|c| {
            if c.is_ascii_lowercase() {
                // Convert 'a'-'f' to ASCII letters
                ((c as u8 - b'a') % 26 + b'a') as char
            } else if c.is_ascii_digit() {
                // Keep digits as-is
                c
            } else {
                c
            }
        })
        .collect()
}

/// A content-addressed hash block containing metadata and content.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct HashBlock {
    /// BLAKE3 hash of the content
    pub hash: String,
    /// Type of content (e.g., "prompt", "script", "bash", "checkpoint")
    pub block_type: String,
    /// Content bytes
    pub content: String,
    /// Timestamp of creation
    pub created_at: String,
    /// Size in bytes
    pub size: usize,
    /// Optional parent hash (for chain traversal)
    pub parent_hash: Option<String>,
}

impl HashBlock {
    pub fn new(content: &str, block_type: &str) -> Self {
        let hash = blake3_hash(content);
        Self {
            hash,
            block_type: block_type.to_string(),
            content: content.to_string(),
            created_at: chrono::Utc::now().to_rfc3339(),
            size: content.len(),
            parent_hash: None,
        }
    }

    /// Create a child block referencing this one as parent.
    pub fn with_parent(&self, content: &str, block_type: &str) -> Self {
        let mut child = HashBlock::new(content, block_type);
        child.parent_hash = Some(self.hash.clone());
        child
    }
}

/// BLAKE3 hash of a string.
pub fn blake3_hash(input: &str) -> String {
    let hash = blake3::hash(input.as_bytes());
    hash.to_hex().to_string()
}

/// Hash engine that maintains a registry of all blocks.
#[derive(Debug, Default)]
pub struct HashEngine {
    /// Registry of hash -> block
    blocks: HashMap<String, HashBlock>,
    /// Index for type -> hashes
    by_type: HashMap<String, Vec<String>>,
    /// Index for parent -> children
    by_parent: HashMap<String, Vec<String>>,
}

impl HashEngine {
    pub fn new() -> Self {
        Self {
            blocks: HashMap::new(),
            by_type: HashMap::new(),
            by_parent: HashMap::new(),
        }
    }

    /// Insert a block into the engine.
    /// Returns the hash of the inserted block.
    pub fn insert(&mut self, block: HashBlock) -> String {
        let hash = block.hash.clone();

        self.blocks.insert(hash.clone(), block);
        self.by_type
            .entry(hash.clone())
            .or_insert_with(Vec::new)
            .push(hash.clone());

        hash
    }

    /// Get a block by its hash.
    pub fn get(&self, hash: &str) -> Option<&HashBlock> {
        self.blocks.get(hash)
    }

    /// List all blocks of a given type.
    pub fn by_type(&self, block_type: &str) -> Vec<&HashBlock> {
        let hashes = self.by_type.get(block_type).cloned().unwrap_or_default();
        hashes
            .into_iter()
            .filter_map(|h| self.blocks.get(&h))
            .collect()
    }

    /// Find blocks that are similar based on hash similarity.
    /// Uses hash prefix matching as a cheap similarity proxy.
    /// For production, replace with actual embedding-based similarity.
    pub fn find_similar(&self, hash: &str, threshold: u8) -> Vec<&HashBlock> {
        let input_hash = blake3::hash(hash.as_bytes());
        let input_bytes = input_hash.as_bytes();

        self.blocks
            .values()
            .filter(|block| {
                let block_hash = blake3::hash(block.hash.as_bytes());
                let block_bytes = block_hash.as_bytes();

                // Count matching bytes at start
                let matches = input_bytes.iter()
                    .zip(block_bytes.iter())
                    .take(threshold as usize)
                    .filter(|(a, b)| a == b)
                    .count();

                matches >= threshold as usize
            })
            .collect()
    }

    /// Get all blocks.
    pub fn all(&self) -> Vec<&HashBlock> {
        self.blocks.values().collect()
    }

    /// Number of blocks in the engine.
    pub fn len(&self) -> usize {
        self.blocks.len()
    }

    /// Check if empty.
    pub fn is_empty(&self) -> bool {
        self.blocks.is_empty()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn hash_engine_stores_blocks() {
        let mut engine = HashEngine::new();

        let block = HashBlock::new("test content", "test");
        let hash = engine.insert(block);

        assert_eq!(engine.get(&hash).unwrap().content, "test content");
        assert_eq!(engine.len(), 1);
    }

    #[test]
    fn hash_is_deterministic() {
        let content = "same content";
        let hash1 = blake3_hash(content);
        let hash2 = blake3_hash(content);

        assert_eq!(hash1, hash2);
    }

    #[test]
    fn block_type_index_works() {
        let mut engine = HashEngine::new();

        engine.insert(HashBlock::new("a", "type1"));
        engine.insert(HashBlock::new("b", "type1"));
        engine.insert(HashBlock::new("c", "type2"));

        let type1_blocks = engine.by_type("type1");
        assert_eq!(type1_blocks.len(), 2);

        let type2_blocks = engine.by_type("type2");
        assert_eq!(type2_blocks.len(), 1);
    }
}
