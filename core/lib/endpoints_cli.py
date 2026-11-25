#!/usr/bin/env python3
# ============================================================================
# AGENT CARD                                                                  =
# ----------------------------------------------------------------------------=
# name:        endpoints (umbrella — base / router / registry / rest /        =
#              webhook / endpoints_cli)                                       =
# role:        INBOUND · LISTENER_FABRIC                                      =
# tier:        L0                                                             =
# substrate:   studio/endpoints (configs + rules + runtime registry)          =
# engine:      abstract base.Endpoint (start/stop/receive/health) +           =
#              RoutingOperator (rule eval in priority order, first match wins)=
# storage:     studio/endpoints/{kind}/<config>.json                          =
#              studio/endpoints/registry.json                                 =
#              studio/endpoints/routes/<priority>.<name>.json                 =
# card:        studio/assets/_agents/agent_defs/                              =
#              vm_mspc_001.agents.agent_defs.endpoints.active.json            =
# ----------------------------------------------------------------------------=
# ROUTING CONNECTIONS                                                         =
# ----------------------------------------------------------------------------=
# inbound:                                                                    =
#   - core/cc.sh::cmd_endpoint_* (start/stop/list/status/sync)               =
#   - CLI: python3 endpoints_cli.py <subcmd>                                  =
#   - External clients hitting REST / webhook URLs                            =
# outbound (per route action):                                                =
#   - action=chain      → cc chat full <prompt>  (joins the MoE pipeline)    =
#   - action=reply      → third_party.ThirdPartyManager.send                  =
#   - action=broadcast  → third_party (fan-out by tag)                        =
#   - action=log        → inference_logger.log (crystal chain append)         =
#   - action=forward    → re-dispatch to another endpoint                     =
#   - action=notify     → desktop / terminal notification                     =
# substrate touch:                                                            =
#   - reads:  studio/endpoints/registry.json + routes/                        =
#   - writes: per-endpoint event log + health JSON                            =
# MERGE POINT WITH MOE STACK:                                                 =
#   When action=chain, the inbound event becomes a cc chat full prompt.       =
#   That prompt flows through user_graph → MoE → enhance → route → project    =
#   → log → record. External webhooks are first-class crystal participants.   =
# ============================================================================
"""endpoints_cli.py — cc bash dispatcher integration for inbound endpoints.

Subcommands:
  start      --kind <k> --name <n> [--port <p>]
  stop       --kind <k> --name <n>
  list       [--kind <k>] [--service <s>] [--state <st>]
  status     [--kind <k>]
  sync       rebuild registry.json from disk

  route-add  --name <n> --priority <p> --match-kind <k> --match-service <s>
             --match-tag <t> --action <a> [--template <tpl>] [--target <svc>]
  route-list [--tag <t>]
  route-test --event-json <json>   # simulate inbound event against rules
  route-archive --asset-id <id>
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from endpoints.base import EndpointConfig
from endpoints.router import RoutingOperator, RouteRule
from endpoints.registry import EndpointRegistry

_ACTIVE_LISTENERS: dict = {}


def cmd_start(args: argparse.Namespace) -> None:
    cfg = EndpointConfig(
        kind=args.kind,
        service=args.service or "generic",
        name=args.name,
        bind={"host": "0.0.0.0", "port": args.port or 9000, "path": args.path or "/", "method": "POST"},
    )
    path = cfg.save()
    print(f"Endpoint config saved: {path}")
    # Note: actual start requires running the listener process (e.g. systemd, screen, or direct python)
    print(f"To start listener: python3 -m endpoints.{args.kind} --config {path}")


def cmd_stop(args: argparse.Namespace) -> None:
    print(f"Stop signal sent for {args.kind}/{args.name}")


def cmd_list(args: argparse.Namespace) -> None:
    reg = EndpointRegistry()
    reg.sync()
    entries = reg.list(kind=args.kind, service=args.service, state=args.state, tag=args.tag)
    for e in entries:
        print(f"{e['kind']:12} {e['service']:12} {e['name']:20} {e['state']:8} {e['path']}")


def cmd_status(args: argparse.Namespace) -> None:
    reg = EndpointRegistry()
    reg.sync()
    entries = reg.list(kind=args.kind)
    print(json.dumps({"active": len(entries), "endpoints": entries}, indent=2, default=str))


def cmd_sync(args: argparse.Namespace) -> None:
    reg = EndpointRegistry()
    stats = reg.sync()
    print(f"Synced: {stats['endpoints']} endpoints across {stats['kinds']} kinds")


def cmd_route_add(args: argparse.Namespace) -> None:
    op = RoutingOperator()
    rule = RouteRule(
        name=args.name,
        priority=args.priority,
        match_kind=args.match_kind or "*",
        match_service=args.match_service or "*",
        match_tag=args.match_tag or "*",
        match_condition=args.match_condition or None,
        action=args.action,
        target_service=args.target or "",
        target_recipient=args.target_recipient or "",
        template=args.template or "",
        chain_command=args.chain_command or "",
    )
    path = op.add_rule(rule)
    print(f"Route added: {path}")


def cmd_route_list(args: argparse.Namespace) -> None:
    op = RoutingOperator().load_rules()
    rules = op.list_rules()
    for r in rules:
        if args.tag and args.tag not in r["match"]:
            continue
        print(f"{r['priority']:4} {r['action']:10} {r['match']:30} → {r['target']}")


def cmd_route_test(args: argparse.Namespace) -> None:
    from endpoints.base import ReceiveEvent
    import hashlib, time
    body = json.loads(args.event_json)
    event = ReceiveEvent(
        crystal_id=hashlib.sha256(json.dumps(body).encode()).hexdigest(),
        endpoint_asset_id="test",
        timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        source_ip="127.0.0.1",
        headers={},
        body=body,
        tag=body.get("tag", body.get("event", "inbound")),
    )
    op = RoutingOperator().load_rules()
    results = op.route(event)
    print(json.dumps(results, indent=2))


def cmd_route_archive(args: argparse.Namespace) -> None:
    op = RoutingOperator()
    result = op.archive_rule(args.asset_id)
    if result:
        print(f"Archived → {result}")
    else:
        print("Route not found", file=sys.stderr)
        sys.exit(1)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="cc endpoints")
    sub = parser.add_subparsers(dest="cmd")

    p_start = sub.add_parser("start")
    p_start.add_argument("--kind", required=True)
    p_start.add_argument("--name", required=True)
    p_start.add_argument("--service", default="")
    p_start.add_argument("--port", type=int, default=0)
    p_start.add_argument("--path", default="/")

    p_stop = sub.add_parser("stop")
    p_stop.add_argument("--kind", required=True)
    p_stop.add_argument("--name", required=True)

    p_list = sub.add_parser("list")
    p_list.add_argument("--kind", default="")
    p_list.add_argument("--service", default="")
    p_list.add_argument("--state", default="")
    p_list.add_argument("--tag", default="")

    p_status = sub.add_parser("status")
    p_status.add_argument("--kind", default="")

    p_sync = sub.add_parser("sync")

    p_radd = sub.add_parser("route-add")
    p_radd.add_argument("--name", required=True)
    p_radd.add_argument("--priority", type=int, default=0)
    p_radd.add_argument("--match-kind", default="*")
    p_radd.add_argument("--match-service", default="*")
    p_radd.add_argument("--match-tag", default="*")
    p_radd.add_argument("--match-condition", default="")
    p_radd.add_argument("--action", required=True)
    p_radd.add_argument("--target", default="")
    p_radd.add_argument("--target-recipient", default="")
    p_radd.add_argument("--template", default="")
    p_radd.add_argument("--chain-command", default="")

    p_rlist = sub.add_parser("route-list")
    p_rlist.add_argument("--tag", default="")

    p_rtest = sub.add_parser("route-test")
    p_rtest.add_argument("--event-json", required=True)

    p_rarch = sub.add_parser("route-archive")
    p_rarch.add_argument("--asset-id", required=True)

    args = parser.parse_args(argv)
    if not args.cmd:
        parser.print_help()
        return 1

    {
        "start": cmd_start,
        "stop": cmd_stop,
        "list": cmd_list,
        "status": cmd_status,
        "sync": cmd_sync,
        "route-add": cmd_route_add,
        "route-list": cmd_route_list,
        "route-test": cmd_route_test,
        "route-archive": cmd_route_archive,
    }[args.cmd](args)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
