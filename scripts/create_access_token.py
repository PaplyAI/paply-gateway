#!/usr/bin/env python3
import argparse
import os
from time import time

from paplyai_gateway.auth import encode_access_token


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create a development Paply login access token."
    )
    parser.add_argument("user_id", help="Stable Paply user id used for accounting")
    parser.add_argument("--hours", type=int, default=24, help="Lifetime in hours (default: 24)")
    parser.add_argument("--issuer", default=os.environ.get("PAPLY_AUTH_JWT_ISSUER", "paply"))
    parser.add_argument(
        "--audience",
        default=os.environ.get("PAPLY_AUTH_JWT_AUDIENCE", "paplyai-gateway"),
    )
    arguments = parser.parse_args()
    if arguments.hours <= 0:
        parser.error("--hours must be greater than zero")
    secret = os.environ.get("PAPLY_AUTH_JWT_SECRET", "").strip()
    if not secret:
        parser.error("PAPLY_AUTH_JWT_SECRET must be set")
    now = int(time())
    print(
        encode_access_token(
            user_id=arguments.user_id,
            secret=secret,
            issuer=arguments.issuer,
            audience=arguments.audience,
            issued_at=now,
            expires_at=now + arguments.hours * 3600,
        )
    )


if __name__ == "__main__":
    main()
