#!/usr/bin/env python3
"""Create one budgeted LiteLLM virtual key without persisting the master key."""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("user_id", help="Stable Paply user ID; do not use an email address")
    parser.add_argument("--alias", help="Operator-friendly key alias")
    parser.add_argument("--max-budget", type=float, default=20.0, help="Budget in USD")
    parser.add_argument("--budget-duration", default="30d")
    parser.add_argument(
        "--models",
        nargs="+",
        default=["paply-chat", "paply-vision", "paply-image"],
    )
    parser.add_argument(
        "--litellm-url",
        default=os.environ.get("LITELLM_ADMIN_URL", "http://127.0.0.1:4000"),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    master_key = os.environ.get("LITELLM_MASTER_KEY", "").strip()
    if not master_key:
        print("LITELLM_MASTER_KEY is required", file=sys.stderr)
        return 2
    if args.max_budget <= 0:
        print("--max-budget must be greater than zero", file=sys.stderr)
        return 2

    payload = {
        "user_id": args.user_id,
        "key_alias": args.alias or f"paply-{args.user_id}",
        "models": args.models,
        "max_budget": args.max_budget,
        "budget_duration": args.budget_duration,
        "metadata": {"issued_by": "paply-token-gateway"},
    }
    request = urllib.request.Request(
        f"{args.litellm_url.rstrip('/')}/key/generate",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "authorization": f"Bearer {master_key}",
            "content-type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            result = json.load(response)
    except urllib.error.HTTPError as error:
        print(f"LiteLLM rejected key creation with status {error.code}", file=sys.stderr)
        return 1
    except urllib.error.URLError as error:
        print(f"LiteLLM is unreachable: {error.reason}", file=sys.stderr)
        return 1

    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

