#!/usr/bin/env python3
"""blender_mcp.py — Blender Claude-Code MCP connector.

Wraps an MCP server that exposes Blender's bpy API to Claude / our chain. When
the MCP server is running locally (typical stdio JSON-RPC), this connector
proxies tool calls like:

  blender_mcp_tool('mesh.create', {'shape': 'cube', 'size': 2.0})
  blender_mcp_tool('material.set', {'object': 'Cube', 'fill_rgb': [1,0.5,0]})
  blender_mcp_tool('render.image', {'output': '/tmp/render.png', 'samples': 64})

Pattern mirrors third_party/discord.py + third_party/pinterest.py. Auth via
$BLENDER_MCP_TOKEN or local socket. Falls back to subprocess `blender --python`
when MCP server unreachable.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from typing import Any, Dict, List, Optional

from .base import ThirdPartyConnector, ConnectionConfig, SendResult


# Common tool surface the Blender MCP server is expected to expose.
EXPECTED_TOOLS = (
    "mesh.create",
    "mesh.import_fbx",
    "mesh.export_gltf",
    "material.set",
    "material.bake_pbr",
    "light.add",
    "camera.set",
    "scene.list_objects",
    "scene.clear",
    "render.image",
    "render.animation",
    "bone.list",
    "bone.set_rotation",
    "modifier.add",
    "python.exec",            # last resort — execute raw bpy python
)


class BlenderMCPConnector(ThirdPartyConnector):
    SERVICE = "blender_mcp"

    def __init__(self, config: ConnectionConfig):
        super().__init__(config)
        self._token: str = (
            (config.auth or {}).get("token")
            or os.environ.get("BLENDER_MCP_TOKEN")
            or ""
        )
        self._endpoint: str = (
            (config.auth or {}).get("endpoint")
            or os.environ.get("BLENDER_MCP_ENDPOINT")
            or "stdio://blender-mcp"   # default: spawn local MCP server via stdio
        )

    # ---- lifecycle -------------------------------------------------

    def connect(self) -> str:
        """Discover the Blender MCP server. Order:
        (a) BLENDER_MCP_ENDPOINT env points at running server
        (b) gh-installed `blender-mcp` binary in PATH
        (c) `blender --background --python -` subprocess fallback (no MCP, raw bpy)
        """
        if self._endpoint.startswith("stdio://"):
            cmd = self._endpoint[len("stdio://"):]
            if shutil.which(cmd) is None and shutil.which("blender") is None:
                self._connected = False
                return "blender_mcp_not_found"
            self._connected = True
            return f"blender_mcp_stdio_ready"
        elif self._endpoint.startswith(("http://", "https://")):
            self._connected = True
            return "blender_mcp_http_ready"
        else:
            self._connected = False
            return f"blender_mcp_unknown_endpoint:{self._endpoint}"

    def disconnect(self) -> str:
        self._connected = False
        return "blender_mcp_disconnected"

    # ---- main op (tool invocation) ---------------------------------

    def send(self, recipient: str, message: str, **kwargs) -> SendResult:
        """For Blender, 'recipient' = tool name (e.g. 'mesh.create'),
        'message' = JSON args."""
        self._rate_limit_wait()
        ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        tool = recipient
        try:
            args = json.loads(message) if message else {}
        except Exception:
            args = {"raw": message}

        if not self._connected:
            connect_status = self.connect()
            if not self._connected:
                result = SendResult(
                    success=False,
                    crystal_id="blender_mcp_disconnected_" + str(hash(tool + ts)),
                    service="blender_mcp",
                    recipient=tool,
                    message_preview=message[:120],
                    timestamp=ts,
                    error=f"could not connect: {connect_status}",
                )
                self._log_send(result)
                return result

        try:
            result_data = self._invoke_tool(tool, args)
        except Exception as e:
            result = SendResult(
                success=False,
                crystal_id="blender_mcp_invoke_failed_" + str(hash(tool + ts)),
                service="blender_mcp",
                recipient=tool,
                message_preview=message[:120],
                timestamp=ts,
                error=f"{type(e).__name__}: {e}",
            )
            self._log_send(result)
            return result

        result = SendResult(
            success=True,
            crystal_id="blender_mcp_" + str(hash(tool + ts)),
            service="blender_mcp",
            recipient=tool,
            message_preview=f"{tool}({len(message)} bytes args)",
            timestamp=ts,
            metadata=result_data,
        )
        self._log_send(result)
        return result

    # ---- the actual tool invocation -------------------------------

    def _invoke_tool(self, tool: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """Invoke a Blender MCP tool. Currently supports the stdio MCP server
        pattern + a fallback raw-bpy subprocess for tools the MCP doesn't expose."""
        if self._endpoint.startswith("stdio://"):
            return self._invoke_stdio(tool, args)
        elif self._endpoint.startswith(("http://", "https://")):
            return self._invoke_http(tool, args)
        else:
            raise RuntimeError(f"unknown endpoint scheme: {self._endpoint}")

    def _invoke_stdio(self, tool: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """Send JSON-RPC over stdio to the Blender MCP server subprocess."""
        cmd = self._endpoint[len("stdio://"):]
        if shutil.which(cmd) is None:
            # MCP server not installed — fall back to raw bpy subprocess for python.exec
            if tool == "python.exec":
                return self._fallback_bpy(args.get("code", ""))
            return {"deferred": True, "tool": tool, "reason": "blender_mcp_server_not_in_path"}

        req = {"jsonrpc": "2.0", "id": 1, "method": tool, "params": args}
        try:
            proc = subprocess.run(
                [cmd],
                input=(json.dumps(req) + "\n").encode("utf-8"),
                capture_output=True,
                timeout=60,
            )
            out = proc.stdout.decode("utf-8", errors="replace").strip().splitlines()
            if not out:
                return {"deferred": True, "tool": tool, "reason": "empty_response"}
            response = json.loads(out[-1])
            return response.get("result") or response
        except Exception as e:
            return {"deferred": True, "tool": tool, "error": str(e)}

    def _invoke_http(self, tool: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """HTTP MCP endpoint — placeholder; would use urllib.request to POST JSON-RPC."""
        return {"deferred": True, "tool": tool, "reason": "http_mcp_not_yet_implemented"}

    def _fallback_bpy(self, code: str) -> Dict[str, Any]:
        """Last-resort: execute raw bpy code via `blender --background --python -`.
        Returns the stdout of the subprocess."""
        if shutil.which("blender") is None:
            return {"deferred": True, "reason": "blender_not_in_path"}
        try:
            proc = subprocess.run(
                ["blender", "--background", "--python-expr", code],
                capture_output=True, timeout=120,
            )
            return {
                "via": "fallback_bpy",
                "exit": proc.returncode,
                "stdout_tail": proc.stdout.decode("utf-8", errors="replace")[-2000:],
            }
        except Exception as e:
            return {"deferred": True, "error": str(e)}

    # ---- convenience wrappers ---------------------------------

    def create_primitive(self, shape: str = "cube", size: float = 2.0,
                          name: Optional[str] = None) -> SendResult:
        args = {"shape": shape, "size": size}
        if name:
            args["name"] = name
        return self.send("mesh.create", json.dumps(args))

    def set_material_rgb(self, object_name: str, rgb: List[float],
                          metallic: float = 0.0, roughness: float = 0.5) -> SendResult:
        return self.send("material.set", json.dumps({
            "object": object_name, "fill_rgb": rgb,
            "metallic": metallic, "roughness": roughness,
        }))

    def add_light(self, position: List[float], rgb: List[float],
                   intensity: float = 1.0, kind: str = "POINT") -> SendResult:
        return self.send("light.add", json.dumps({
            "position": position, "rgb": rgb, "intensity": intensity, "type": kind,
        }))

    def render_image(self, output: str, samples: int = 64,
                      resolution: List[int] = None) -> SendResult:
        args = {"output": output, "samples": samples}
        if resolution:
            args["resolution"] = resolution
        return self.send("render.image", json.dumps(args))

    def history(self, recipient: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        return self._read_log_tail(limit)
