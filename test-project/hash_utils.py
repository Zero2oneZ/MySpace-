#!/usr/bin/env python3
"""Hash utilities for decompilation - standalone version"""

import hashlib


def invert_hash_char(c: str) -> str:
    """Invert a single hash character (hex chars: 0-9, a-f, A-F)"""
    if '0' <= c <= '9':
        n = ord(c) - ord('0')
        if n < 6:
            return chr(n + ord('a'))
        return c
    elif 'a' <= c <= 'f':
        n = ord(c) - ord('a')
        return chr(n + ord('0'))
    elif 'A' <= c <= 'F':
        n = ord(c) - ord('A')
        return chr(n + ord('0'))
    return c


def invert_hash(hash_str: str) -> str:
    """Invert all characters in a hash string"""
    return ''.join(invert_hash_char(c) for c in hash_str)


def hash_loop_invert(start_hash: str, iterations: int) -> list:
    """Generate a loop of inverted hashes"""
    hashes = []
    current = start_hash
    for _ in range(iterations):
        hashes.append(current)
        current = invert_hash(current)
    return hashes


def decode_hash_to_text(hash_str: str) -> str:
    """Decode a hash back to readable text"""
    inverted = invert_hash(hash_str)
    result = []
    for c in inverted:
        if c.isascii() and c.islower():
            result.append(c)
        elif c.isdigit():
            result.append(c)
    return ''.join(result)


def blake3_hash(data: str) -> str:
    """Compute BLAKE3 hash"""
    try:
        import blake3
        return blake3.blake3(data.encode()).hexdigest()
    except ImportError:
        # Fallback to blake2b if blake3 not available
        return hashlib.blake2b(data.encode()).hexdigest()


if __name__ == '__main__':
    # Test with a sample hash
    test_hash = "abc123def456"
    print(f"Original: {test_hash}")

    for i in range(5):
        test_hash = invert_hash(test_hash)
        print(f"Iteration {i+1}: {test_hash}")
