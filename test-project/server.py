#!/usr/bin/env python3
"""Gradio-like HTTP server using only stdlib + HTMX"""

import json
import os
import hashlib
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime

# Import chainbabe decompile functions
import sys
sys.path.insert(0, '/data/Projects/MySpace++/test-project')

from hash_utils import invert_hash, hash_loop_invert, blake3_hash, decode_hash_to_text


# blake3_hash imported from hash_utils


PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))


def get_project_files() -> dict:
    """Get all files in project directory"""
    files = {}
    for root, dirs, filenames in os.walk(PROJECT_DIR):
        # Skip hidden files and __pycache__
        dirs[:] = [d for d in dirs if not d.startswith('.')]
        if '__pycache__' in dirs:
            dirs.remove('__pycache__')

        for fname in filenames:
            if fname.startswith('.'):
                continue
            fpath = os.path.join(root, fname)
            try:
                with open(fpath, 'r', encoding='utf-8') as f:
                    files[fpath] = f.read()
            except:
                pass
    return files


def decompile_hash_loop(hash_str: str, iterations: int) -> list:
    """Run the hash loop decompile"""
    hashes = hash_loop_invert(hash_str, iterations)
    results = []
    for i, h in enumerate(hashes):
        results.append({
            "iteration": i,
            "hash": h,
            "inverted": invert_hash(h)
        })
    return results


class RequestHandler(BaseHTTPRequestHandler):
    """HTTP request handler"""

    def log_message(self, format, *args):
        """Suppress default logging"""
        pass

    def send_json(self, data: dict, status: int = 200):
        """Send JSON response"""
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def send_html(self, content: str, status: int = 200):
        """Send HTML response"""
        self.send_response(status)
        self.send_header('Content-Type', 'text/html')
        self.end_headers()
        self.wfile.write(content.encode())

    def do_GET(self):
        """Handle GET requests"""
        if self.path == '/' or self.path == '/index.html':
            with open(os.path.join(PROJECT_DIR, 'index.html'), 'r') as f:
                self.send_html(f.read())
        elif self.path == '/project-hash':
            files = get_project_files()
            combined = json.dumps(files, sort_keys=True)
            project_hash = blake3_hash(combined)
            decompiled = decompile_hash_loop(project_hash, 5)
            self.send_json({
                "project_hash": project_hash,
                "file_count": len(files),
                "decompiled": decompiled
            })
        else:
            self.send_error(404)

    def do_POST(self):
        """Handle POST requests"""
        if self.path == '/generate':
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length).decode()
            form_data = json.loads(body) if body else {}

            prompt = form_data.get('prompt', '')
            iterations = int(form_data.get('iterations', 5))

            # Create a prompt hash
            prompt_hash = blake3_hash(prompt)
            decompiled = decompile_hash_loop(prompt_hash, iterations)

            # Simulate some generated output
            output_lines = [
                f"=== Generated Output (from prompt hash) ===",
                f"Prompt hash: {prompt_hash}",
                f"Iterations: {iterations}",
                ""
            ]
            for d in decompiled:
                output_lines.append(f"Iteration {d['iteration']}:")
                output_lines.append(f"  Hash: {d['hash']}")
                output_lines.append(f"  Inverted: {d['inverted']}")
                output_lines.append("")

            self.send_json({
                "status": "complete",
                "output": "\n".join(output_lines)
            })
        else:
            self.send_error(404)


def main():
    """Start the server"""
    port = 8081
    server = HTTPServer(('localhost', port), RequestHandler)
    print(f"Gradio-like HTMX server running at http://localhost:{port}")
    print(f"Project directory: {PROJECT_DIR}")
    server.serve_forever()


if __name__ == '__main__':
    main()
