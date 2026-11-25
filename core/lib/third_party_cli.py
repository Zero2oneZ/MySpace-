#!/usr/bin/env python3
# ============================================================================
# AGENT CARD                                                                  =
# ----------------------------------------------------------------------------=
# name:        third_party (umbrella — base / manager / per-service          =
#              connectors / third_party_cli)                                  =
# role:        OUTBOUND · CONNECTOR_FABRIC                                    =
# tier:        L0                                                             =
# substrate:   studio/third_party (per-service auth + token rotation)        =
# engine:      abstract base.Connector (connect/send/history/disconnect) +    =
#              per-platform subclasses (discord/telegram/twitter/fb/wa)       =
# storage:     studio/third_party/{service}/<config>.json (mode-600)         =
#              every send appends an InferenceRecord (tier='outbound')        =
# card:        studio/assets/_agents/agent_defs/                              =
#              vm_mspc_001.agents.agent_defs.third_party.active.json          =
# ----------------------------------------------------------------------------=
# ROUTING CONNECTIONS                                                         =
# ----------------------------------------------------------------------------=
# inbound:                                                                    =
#   - core/cc.sh::cmd_third_party_*  (connect/send/list/status/archive)      =
#   - CLI: python3 third_party_cli.py <subcmd>                                =
#   - endpoints.RoutingOperator  (action=reply | action=broadcast)            =
#   - chat.py  (when a chat response should surface to an external channel)   =
# outbound (per service):                                                     =
#   - discord-py-interactions / python-telegram-bot / tweepy / Graph API /    =
#     WhatsApp Cloud API                                                      =
# substrate touch:                                                            =
#   - reads:  studio/third_party/{service}/*.json                             =
#   - writes: per-service send logs + inference_logger crystal chain         =
# MERGE POINT WITH MOE STACK:                                                 =
#   Every send → one InferenceRecord (tier='outbound', model='<service>',    =
#   original_prompt='<message>', output_text='<delivery_receipt>'). MoE       =
#   retrieval can later surface past sends as priors for new outbound calls.  =
# ============================================================================
"""third_party_cli.py — cc bash dispatcher integration for outbound connectivity.

Subcommands:
  connect    --service <svc> --token <t> [--name <n>] [--tags <t,t>]
  send       --service <svc> --to <recipient> --message <msg>
  list       [--service <svc>] [--state active|paused|archived]
  status     [--service <svc>]
  archive    --asset-id <id>
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Ensure core/lib is importable
sys.path.insert(0, str(Path(__file__).resolve().parent))

from third_party.base import ConnectionConfig
from third_party.manager import ThirdPartyManager


def cmd_connect(args: argparse.Namespace) -> None:
    mgr = ThirdPartyManager()
    cfg = ConnectionConfig(
        service=args.service,
        name=args.name or f"{args.service}_auto",
        auth={"bot_token": args.token} if args.token else {},
        routing_tags=(args.tags or "").split(",") if args.tags else ["broadcast"],
    )
    path = mgr.add_config(cfg)
    print(f"Connected {args.service} → {path}")


def cmd_send(args: argparse.Namespace) -> None:
    mgr = ThirdPartyManager().load_all()
    results = mgr.send(args.service, args.to, args.message)
    for r in results:
        status = "OK" if r.success else "FAIL"
        print(f"[{status}] {r.service} → {r.recipient}: {r.message_preview}")
        if r.error:
            print(f"  error: {r.error}")


def cmd_list(args: argparse.Namespace) -> None:
    mgr = ThirdPartyManager().load_all()
    cfgs = mgr.configs(args.service) if args.service else mgr.configs()
    for c in cfgs:
        if args.state and c.state != args.state:
            continue
        print(f"{c.service:12} {c.name:20} {c.state:8} {c.asset_id}")


def cmd_status(args: argparse.Namespace) -> None:
    mgr = ThirdPartyManager().load_all()
    status = mgr.status()
    print(json.dumps(status, indent=2))


def cmd_archive(args: argparse.Namespace) -> None:
    mgr = ThirdPartyManager()
    result = mgr.archive_config(args.asset_id)
    if result:
        print(f"Archived → {result}")
    else:
        print("Asset not found", file=sys.stderr)
        sys.exit(1)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="cc third_party")
    sub = parser.add_subparsers(dest="cmd")

    p_connect = sub.add_parser("connect")
    p_connect.add_argument("--service", required=True)
    p_connect.add_argument("--token", default="")
    p_connect.add_argument("--name", default="")
    p_connect.add_argument("--tags", default="")

    p_send = sub.add_parser("send")
    p_send.add_argument("--service", required=True)
    p_send.add_argument("--to", required=True)
    p_send.add_argument("--message", required=True)

    p_list = sub.add_parser("list")
    p_list.add_argument("--service", default="")
    p_list.add_argument("--state", default="")

    p_status = sub.add_parser("status")
    p_status.add_argument("--service", default="")

    p_archive = sub.add_parser("archive")
    p_archive.add_argument("--asset-id", required=True)

    args = parser.parse_args(argv)
    if not args.cmd:
        parser.print_help()
        return 1

    {
        "connect": cmd_connect,
        "send": cmd_send,
        "list": cmd_list,
        "status": cmd_status,
        "archive": cmd_archive,
    }[args.cmd](args)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
