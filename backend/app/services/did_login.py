from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import Any

from eth_account import Account
from eth_account.messages import encode_defunct


WALLET_ADDRESS_PATTERN = re.compile(r"^0x[0-9a-fA-F]{40}$")


class DidWalletConfigurationError(ValueError):
    """Raised when the deployment's DID wallet binding configuration is invalid."""


def normalize_wallet_address(value: str) -> str:
    normalized = value.strip()
    if not WALLET_ADDRESS_PATTERN.fullmatch(normalized):
        raise ValueError("钱包地址格式无效")
    return normalized.lower()


def challenge_message(
    *,
    host: str,
    wallet_address: str,
    challenge: str,
    expires_at: datetime,
) -> str:
    expires = expires_at.replace(tzinfo=UTC).isoformat().replace("+00:00", "Z")
    return (
        "隐链明算 DID 钱包登录\n"
        f"域名: {host}\n"
        f"钱包地址: {wallet_address}\n"
        f"一次性挑战: {challenge}\n"
        f"有效期至: {expires}"
    )


def recover_wallet_address(message: str, signature: str) -> str:
    recovered = Account.recover_message(
        encode_defunct(text=message),
        signature=signature,
    )
    return normalize_wallet_address(recovered)


def configured_did_for_wallet(raw_bindings: str, wallet_address: str) -> str | None:
    try:
        bindings: Any = json.loads(raw_bindings or "{}")
    except (TypeError, json.JSONDecodeError) as exc:
        raise DidWalletConfigurationError("DID 钱包绑定配置不是有效 JSON") from exc
    if not isinstance(bindings, dict):
        raise DidWalletConfigurationError("DID 钱包绑定配置必须是 DID 到钱包地址的对象")

    normalized_wallet = normalize_wallet_address(wallet_address)
    matched_did: str | None = None
    for did_id, configured_address in bindings.items():
        if not isinstance(did_id, str) or not did_id.startswith("did:"):
            raise DidWalletConfigurationError("DID 钱包绑定配置包含无效 DID")
        if not isinstance(configured_address, str):
            raise DidWalletConfigurationError("DID 钱包绑定配置包含无效钱包地址")
        try:
            normalized_configured_address = normalize_wallet_address(configured_address)
        except ValueError as exc:
            raise DidWalletConfigurationError("DID 钱包绑定配置包含无效钱包地址") from exc
        if normalized_configured_address != normalized_wallet:
            continue
        if matched_did is not None and matched_did != did_id:
            raise DidWalletConfigurationError("同一钱包地址不能绑定多个 DID")
        matched_did = did_id
    return matched_did
