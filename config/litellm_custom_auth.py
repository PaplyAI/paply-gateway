import hmac
import os

from fastapi import HTTPException, Request
from litellm.proxy._types import LitellmUserRoles, UserAPIKeyAuth


def _required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


async def user_api_key_auth(request: Request, api_key: str) -> UserAPIKeyAuth:
    """Trust only the Paply edge or the operator master key.

    The public client cannot reach this listener. The edge authenticates a
    Paply session, removes caller-supplied identity headers, and supplies the
    stable user id below. LiteLLM remains the spend and token source of truth.
    """

    master_key = _required_env("LITELLM_MASTER_KEY")
    if hmac.compare_digest(api_key, master_key):
        return UserAPIKeyAuth(
            api_key=api_key,
            user_id="paply-proxy-admin",
            user_role=LitellmUserRoles.PROXY_ADMIN,
        )

    service_token = _required_env("PAPLY_LITELLM_SERVICE_TOKEN")
    if not hmac.compare_digest(api_key, service_token):
        raise HTTPException(status_code=401, detail="Invalid internal Gateway credential")

    user_id = request.headers.get("x-paply-user-id", "").strip()
    if not user_id or len(user_id) > 128:
        raise HTTPException(status_code=401, detail="Missing trusted Paply user identity")
    return UserAPIKeyAuth(
        api_key=api_key,
        user_id=user_id,
        end_user_id=user_id,
        user_role=LitellmUserRoles.INTERNAL_USER,
        models=["paply-chat", "paply-vision", "paply-image"],
    )
