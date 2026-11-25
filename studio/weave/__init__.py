"""weave/ — cross-device compute fabric.

WEAVE sits on top of TWINS (cc.db + .cc/local.db). Where TWINS coordinates
*sessions*, WEAVE coordinates *compute* — distributing inference work
across every device that opens the master SVG, using Chromium WebGPU as
the universal accelerator.

Three pillars:

  topology  — who is online, what GPU adapters they have, what they're doing
  plans     — declarative routing rules (conditional: "if X then route to Y")
  routing   — decide where a pass should run, given the live snapshot

The master TWINS-MASTER.svg is the consensus document. Every device polls
it, agrees on the current topology + plans, and self-assigns work via the
WebSocket relay (studio/weave/weave_server.py).

Browser side: studio/weave/webgpu_worker.html opens in any Chromium tab,
probes WebGPU, registers as a worker. Friends can become compute nodes
just by opening the URL.

Submodule names are kept LAZY so script-mode (`python3 weave/plans.py`)
doesn't trigger circular initialization.
"""
__all__ = ["topology", "plans", "routing"]
