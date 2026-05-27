"""DynamoDB helpers for dual-LLM dispute analysis rows and HITL session metadata."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import boto3
from boto3.dynamodb.conditions import Key
from botocore.config import Config
from botocore.exceptions import BotoCoreError
import base64
import hashlib
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import padding
from src.analysis_agent.retry import call_with_retry
from src.config import Settings
logger = logging.getLogger(__name__)
from datetime import datetime

# Single Table handle per process (lazy); avoids boto3.resource(...) on every Put/Update.
_dynamo_table: Any | None = None


def _botocore_config(settings: Settings) -> Config:
    max_attempts = max(1, int(settings.dynamo_db_max_retry) or 5)
    conn = int(settings.connect_timeout) if settings.connect_timeout > 0 else 5
    read = int(settings.read_timeout) if settings.read_timeout > 0 else 60
    return Config(
        region_name=settings.aws_region,
        connect_timeout=conn,
        read_timeout=read,
        retries={"max_attempts": max_attempts, "mode": "standard"},
        tcp_keepalive=True,
    )


def connect_to_dynamodb(settings: Settings) -> Any:
    """Build a DynamoDB Table resource (optional local endpoint + explicit keys from settings)."""
    table_name = (settings.aws_dynamodb_table or "").strip()
    if not table_name:
        raise ValueError("aws_dynamodb_table is not configured")

    resource_kwargs: dict[str, Any] = {
        "region_name": settings.aws_region,
        "config": _botocore_config(settings),
    }
    try:
        dynamodb = boto3.resource("dynamodb", **resource_kwargs)
        return dynamodb.Table(table_name)
    except BotoCoreError:
        logger.exception("DynamoDB resource initialization failed (region=%s)", settings.aws_region)
        raise


def get_dynamo_table(settings: Settings) -> Any:
    """
    Return the shared Table resource, creating it once on first use.

    Callers should ensure ``aws_dynamodb_table`` is set before invoking Put/Update helpers.
    """
    global _dynamo_table
    if _dynamo_table is not None:
        return _dynamo_table
    _dynamo_table = connect_to_dynamodb(settings=settings)
    return _dynamo_table


def reset_dynamo_table_cache() -> None:
    """Clear cached table (e.g. tests or after config hot-reload)."""
    global _dynamo_table
    _dynamo_table = None

#Used to write the analysis to the DynamoDB table
def put_item_with_retry(
    *,
    item: dict[str, Any],
    state: Mapping[str, Any],
    settings: Settings,
) -> None:
    table = get_dynamo_table(settings=settings)

    def _put() -> None:
        table.put_item(Item=item)

    call_with_retry(
        _put,
        attempts=settings.dynamo_db_max_retry,
        operation="DynamoDB put_item",
        state=state,
        settings=settings,
    )

def query_items_by_pk_and_sk_prefix_with_retry(
    *,
    pk: str,
    sk_prefix: str,
    state: Mapping[str, Any],
    settings: Settings,
) -> list[dict[str, Any]]:
    """Query items by ``PK`` and an ``SK`` prefix with the shared retry policy."""
    pk_val = (pk or "").strip()
    sk_prefix_val = (sk_prefix or "").strip()
    if not pk_val or not sk_prefix_val:
        raise ValueError(
            "query_items_by_pk_and_sk_prefix_with_retry requires non-empty pk and sk_prefix"
        )

    table = get_dynamo_table(settings=settings)

    def _query() -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        last_evaluated_key: dict[str, Any] | None = None
        while True:
            query_kwargs: dict[str, Any] = {
                "KeyConditionExpression": Key("PK").eq(pk_val)
                & Key("SK").begins_with(sk_prefix_val)
            }
            if last_evaluated_key:
                query_kwargs["ExclusiveStartKey"] = last_evaluated_key
            resp = table.query(**query_kwargs)
            items.extend(dict(item) for item in resp.get("Items", []))
            last_evaluated_key = resp.get("LastEvaluatedKey")
            if not last_evaluated_key:
                break
        logger.info(
            "DynamoDB query returned %d item(s) pk=%s sk_prefix=%s",
            len(items),
            pk_val,
            sk_prefix_val,
        )
        return items

    return call_with_retry(
        _query,
        attempts=settings.dynamo_db_max_retry,
        operation="DynamoDB query",
        state=state,
        settings=settings,
    )


class DisputeRecordNotFoundError(LookupError):
    """Raised when the source dispute row does not exist in DynamoDB."""


def get_item_with_retry(
    *,
    pk: str,
    sk: str,
    state: Mapping[str, Any],
    settings: Settings,
) -> dict[str, Any] | None:
    """Return the DynamoDB item at ``PK``/``SK``, or ``None`` if it does not exist."""
    pk_val = (pk or "").strip()
    sk_val = (sk or "").strip()
    if not pk_val or not sk_val:
        raise ValueError("get_item_with_retry requires non-empty pk and sk")

    table = get_dynamo_table(settings=settings)

    def _get() -> dict[str, Any] | None:
        resp = table.get_item(Key={"PK": pk_val, "SK": sk_val})
        item = resp.get("Item")
        return dict(item) if item else None

    return call_with_retry(
        _get,
        attempts=settings.dynamo_db_max_retry,
        operation="DynamoDB get_item",
        state=state,
        settings=settings,
    )


def assert_dispute_record_exists(
    *,
    pk: str,
    sk: str,
    state: Mapping[str, Any],
    settings: Settings,
) -> dict[str, Any]:
    """Require a row at ``PK``/``SK``; raise ``DisputeRecordNotFoundError`` if missing."""
    item = get_item_with_retry(pk=pk, sk=sk, state=state, settings=settings)
    if item is None:
        raise DisputeRecordNotFoundError(
            f"No DynamoDB dispute record at PK={pk!r} SK={sk!r} "
            f"(table={settings.aws_dynamodb_table!r})"
        )
    return item


def update_item_with_retry(
    *,
    pk: str,
    sk: str,
    attribute_updates: dict[str, Any],
    state: Mapping[str, Any],
    settings: Settings,
) -> None:
    """
    Update top-level attributes on an existing DynamoDB item with retries.

    ``attribute_updates`` maps attribute names to new values (e.g. ``disputeStatus``).
    Uses ``ExpressionAttributeNames`` / ``ExpressionAttributeValues`` for safe expressions.
    """
    pk_val = (pk or "").strip()
    sk_val = (sk or "").strip()
    if not pk_val or not sk_val:
        raise ValueError("update_item_with_retry requires non-empty pk and sk")
    if not attribute_updates:
        raise ValueError("update_item_with_retry requires at least one attribute to update")

    table = get_dynamo_table(settings=settings)

    def _update() -> None:
        names: dict[str, str] = {"#pk": "PK"}
        values: dict[str, Any] = {}
        set_parts: list[str] = []
        for idx, (attr_name, attr_value) in enumerate(attribute_updates.items()):
            name_token = f"#n{idx}"
            value_token = f":v{idx}"
            names[name_token] = attr_name
            values[value_token] = attr_value
            set_parts.append(f"{name_token} = {value_token}")

        table.update_item(
            Key={"PK": pk_val, "SK": sk_val},
            UpdateExpression="SET " + ", ".join(set_parts),
            ConditionExpression="attribute_exists(#pk)",
            ExpressionAttributeNames=names,
            ExpressionAttributeValues=values,
        )

    call_with_retry(
        _update,
        attempts=settings.dynamo_db_max_retry,
        operation="DynamoDB update_item",
        state=state,
        settings=settings,
    )

def get_ssm_parameter(region_name: str, name: str) -> str:
    client = boto3.client("ssm", region_name=region_name)
    resp = client.get_parameter(Name=name, WithDecryption=True)
    return resp["Parameter"]["Value"]

def decrypt_value(encrypted_value: str, settings: Settings):
    """
    Decrypt a base64 encoded AES-256-CBC value.

    The configured SSM encryption key is hashed to a 32-byte AES key.
    """
    if encrypted_value is None:
        return None

    try:
        encrypted_data = base64.b64decode(encrypted_value)
        if len(encrypted_data) <= 16:
            raise ValueError("encrypted payload is too short to contain IV and ciphertext")

        iv = encrypted_data[:16]
        ciphertext = encrypted_data[16:]
        raw_key = get_ssm_parameter(settings.aws_region, settings.encryption_key_ssm_parameter)
        key = hashlib.sha256(raw_key.encode("utf-8")).digest()

        cipher = Cipher(
            algorithms.AES(key),
            modes.CBC(iv),
            backend=default_backend(),
        )
        decryptor = cipher.decryptor()
        padded_data = decryptor.update(ciphertext) + decryptor.finalize()

        unpadder = padding.PKCS7(algorithms.AES.block_size).unpadder()
        data = unpadder.update(padded_data) + unpadder.finalize()
        decoded = data.decode("utf-8")
        try:
            return datetime.strptime(decoded, "%Y-%m-%d").date()
        except ValueError:
            return decoded
    except Exception:
        logger.exception("Failed to decrypt consumer field")
        raise