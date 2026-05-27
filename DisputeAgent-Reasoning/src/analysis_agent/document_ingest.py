from __future__ import annotations

import json
import logging
import os
import re
import tempfile
from typing import Any, BinaryIO, Iterable
from urllib.parse import unquote, urlparse
import boto3
from botocore.exceptions import BotoCoreError, ClientError
from openai import OpenAI

from src.config import Settings

logger = logging.getLogger(__name__)

_MAX_DOWNLOAD_BYTES = 512 * 1024 * 1024
_S3_URI_RE = re.compile(r"^s3://([^/]+)/(.+)$", re.IGNORECASE)
_MISSING_PROPERTY_COMMA_RE = re.compile(
    r'("(?:\\.|[^"\\])*")\s*(?=\r?\n\s*"(?:\\.|[^"\\])*"\s*:)',
)


def _suggested_filename_from_key(key: str) -> str:
    name = key.rsplit("/", 1)[-1] if key else "document.pdf"
    return name if "." in name else f"{name}.pdf"


def parse_s3_bucket_and_key(s3_ref: str) -> tuple[str, str]:
    """
    Parse an S3 reference into ``(bucket, key)``.

    Supported forms:
    - ``s3://bucket/key``
    - ``bucket/key``
    - ``https://bucket.s3.amazonaws.com/key``
    - ``https://bucket.s3.<region>.amazonaws.com/key``
    - ``https://s3.amazonaws.com/bucket/key``
    - ``https://s3.<region>.amazonaws.com/bucket/key``
    """
    raw = (s3_ref or "").strip()
    if not raw:
        raise ValueError("S3 reference is empty")

    match = _S3_URI_RE.match(raw)
    if match:
        return match.group(1).strip(), match.group(2).strip()

    parsed = urlparse(raw)
    if parsed.scheme in {"http", "https"}:
        host = parsed.netloc.split("@")[-1].split(":", 1)[0]
        path = unquote(parsed.path.lstrip("/"))

        virtual_host_match = re.match(
            r"^(?P<bucket>.+)\.s3(?:[.-][a-z0-9-]+)?\.amazonaws\.com$",
            host,
            re.IGNORECASE,
        )
        if virtual_host_match and path:
            return virtual_host_match.group("bucket").strip(), path.strip()

        path_style_match = re.match(
            r"^s3(?:[.-][a-z0-9-]+)?\.amazonaws\.com$",
            host,
            re.IGNORECASE,
        )
        if path_style_match and "/" in path:
            bucket, key = path.split("/", 1)
            bucket = bucket.strip()
            key = key.strip()
            if bucket and key:
                return bucket, key

        raise ValueError(f"Unsupported S3 HTTPS URL format: {raw!r}")

    if "/" not in raw:
        raise ValueError(
            f"S3 reference must be s3://bucket/key, bucket/key, or S3 HTTPS URL; got {raw!r}"
        )

    bucket, key = raw.split("/", 1)
    bucket = bucket.strip()
    key = key.strip()
    if not bucket or not key:
        raise ValueError(f"Invalid S3 reference: {raw!r}")
    return bucket, key


def build_s3_uri(bucket: str, key: str) -> str:
    """Return a normalized ``s3://bucket/key`` URI."""
    b = (bucket or "").strip()
    k = (key or "").strip().lstrip("/")
    if not b or not k:
        raise ValueError("bucket and key are required to build an S3 URI")
    return f"s3://{b}/{k}"


def _loads_json_with_missing_comma_repair(text: str, *, source: str) -> Any:
    """Parse JSON, tolerating config files that omit commas between line entries."""
    try:
        return json.loads(text)
    except json.JSONDecodeError as original_error:
        repaired = _MISSING_PROPERTY_COMMA_RE.sub(r"\1,", text)
        if repaired == text:
            raise original_error

        try:
            parsed = json.loads(repaired)
        except json.JSONDecodeError:
            raise original_error

        logger.warning(
            "Parsed non-strict JSON from %s after repairing missing line-entry commas",
            source,
        )
        return parsed


def copy_s3_object(
    *,
    source_bucket: str,
    source_key: str,
    dest_bucket: str,
    dest_key: str,
    aws_region: str,
    content_type: str | None = None,
) -> str:
    """
    Copy an object from one S3 bucket to another (server-side ``CopyObject``).

    Returns the destination ``s3://`` URI. Requires IAM permission on source read and dest write.
    """
    src_bucket = (source_bucket or "").strip()
    src_key = (source_key or "").strip()
    dst_bucket = (dest_bucket or "").strip()
    dst_key = (dest_key or "").strip()
    if not src_bucket or not src_key:
        raise ValueError("source_bucket and source_key must be non-empty")
    if not dst_bucket or not dst_key:
        raise ValueError("dest_bucket and dest_key must be non-empty")

    client = boto3.client("s3", region_name=aws_region)
    copy_source = {"Bucket": src_bucket, "Key": src_key}
    extra_args: dict[str, str] = {}
    if content_type:
        extra_args["ContentType"] = content_type
    else:
        try:
            head = client.head_object(Bucket=src_bucket, Key=src_key)
            if head.get("ContentType"):
                extra_args["ContentType"] = str(head["ContentType"])
        except (ClientError, BotoCoreError):
            pass

    try:
        params: dict[str, object] = {
            "Bucket": dst_bucket,
            "Key": dst_key,
            "CopySource": copy_source,
            "MetadataDirective": "COPY",
        }
        if extra_args.get("ContentType"):
            params["ContentType"] = extra_args["ContentType"]
        client.copy_object(**params)  # type: ignore[arg-type]
    except (ClientError, BotoCoreError) as e:
        raise RuntimeError(
            f"S3 copy failed s3://{src_bucket}/{src_key} -> s3://{dst_bucket}/{dst_key}: {e}"
        ) from e

    dest_uri = build_s3_uri(dst_bucket, dst_key)
    logger.info("Copied S3 object to %s", dest_uri)
    return dest_uri


def copy_s3_object_from_uri(
    source_s3_uri: str,
    *,
    dest_bucket: str,
    dest_key: str,
    aws_region: str,
) -> str:
    """Copy from a source ``s3://`` (or ``bucket/key``) URI to ``dest_bucket``/``dest_key``."""
    src_bucket, src_key = parse_s3_bucket_and_key(source_s3_uri)
    return copy_s3_object(
        source_bucket=src_bucket,
        source_key=src_key,
        dest_bucket=dest_bucket,
        dest_key=dest_key,
        aws_region=aws_region,
    )


def copy_s3_object_uri_to_uri(
    source_s3_uri: list[str],
    dest_s3_uri: str,
    *,
    aws_region: str,
) -> list[str]:
    """Copy source S3 files into a destination S3 URI/prefix; returns copied URIs."""
    dest_bucket, dest_prefix = parse_s3_bucket_and_key(dest_s3_uri)
    dest_is_prefix = dest_s3_uri.rstrip().endswith("/")
    copied_uris: list[str] = []

    for uri in source_s3_uri:
        src_bucket, src_key = parse_s3_bucket_and_key(str(uri or ""))
        filename = src_key.rsplit("/", 1)[-1]
        dest_key = (
            f"{dest_prefix.rstrip('/')}/{filename}"
            if dest_is_prefix
            else dest_prefix
        )
        try:
            copied_uri = copy_s3_object(
                source_bucket=src_bucket,
                source_key=src_key,
                dest_bucket=dest_bucket,
                dest_key=dest_key,
                aws_region=aws_region,
            )
            copied_uris.append(copied_uri)
        except Exception as e:
            raise RuntimeError(
                f"S3 copy failed for s3://{src_bucket}/{src_key} -> s3://{dest_bucket}/{dest_key}: {e}"
            ) from e
    return copied_uris


def _download_s3_object_to_path(bucket: str, key: str, dest_path: str, *, region: str) -> str:
    client = boto3.client("s3", region_name=region)
    try:
        obj = client.get_object(Bucket=bucket, Key=key)
        body = obj["Body"]
        total = 0
        with open(dest_path, "wb") as out:
            while True:
                chunk = body.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > _MAX_DOWNLOAD_BYTES:
                    raise ValueError(
                        f"Document exceeds max download size ({_MAX_DOWNLOAD_BYTES} bytes)."
                    )
                out.write(chunk)
    except (ClientError, BotoCoreError) as e:
        raise RuntimeError(
            f"S3 download failed for s3://{bucket}/{key!r}: {e}"
        ) from e
    return _suggested_filename_from_key(key)


def download_s3_json_object(
    bucket: str,
    key: str,
    *,
    aws_region: str,
) -> Any:
    """Download one S3 object and parse its body as UTF-8 JSON."""
    b = bucket.strip()
    k = key.strip()
    if not b or not k:
        raise ValueError("S3 bucket and object key must both be non-empty")

    client = boto3.client("s3", region_name=aws_region)
    try:
        obj = client.get_object(Bucket=b, Key=k)
        body = obj["Body"].read()
    except (ClientError, BotoCoreError) as e:
        raise RuntimeError(f"S3 download failed for s3://{b}/{k!r}: {e}") from e

    if len(body) > _MAX_DOWNLOAD_BYTES:
        raise ValueError(
            f"JSON object exceeds max download size ({_MAX_DOWNLOAD_BYTES} bytes)."
        )

    try:
        text = body.decode("utf-8")
        return _loads_json_with_missing_comma_repair(text, source=f"s3://{b}/{k}")
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise ValueError(f"Invalid JSON in s3://{b}/{k!r}: {e}") from e


def download_s3_object_to_tempfile(
    bucket: str,
    key: str,
    *,
    aws_region: str,
) -> tuple[str, str]:
    """Download one object. Returns ``(temp_path, filename)`` for OpenAI upload."""
    b = bucket.strip()
    k = key.strip()
    if not b or not k:
        raise ValueError("S3 bucket and object key must both be non-empty")

    fd, temp_path = tempfile.mkstemp(prefix="dispute_doc_", suffix=".bin")
    os.close(fd)
    try:
        fname = _download_s3_object_to_path(b, k, temp_path, region=aws_region)
        return temp_path, fname
    except Exception:
        try:
            os.unlink(temp_path)
        except OSError:
            pass
        raise

def get_ssm_parameter(settings: Settings, name: str) -> str:
    if not (name or "").strip():
        raise ValueError("SSM parameter name is required")
    client = boto3.client("ssm", region_name=settings.aws_region)
    try:
        resp = client.get_parameter(Name=name, WithDecryption=True)
        logger.info("Loaded SSM parameter %s", name)
        return resp["Parameter"]["Value"]
    except (ClientError, BotoCoreError) as e:
        raise RuntimeError(f"SSM get_parameter failed for {name!r}: {e}") from e

def upload_file_to_analysis_model(settings: Settings, file_obj: BinaryIO, filename: str) -> str:
    """Upload to OpenAI Files API; returns ``file_id`` for chat ``content`` file parts."""
    api_key = get_ssm_parameter(settings, settings.analysis_model_api_key_ssm_parameter)
    if not api_key:
        raise ValueError("Missing ANALYSIS_MODEL_API_KEY from SSM parameter.")
    client = OpenAI(api_key=api_key)
    try:
        created = client.files.create(file=(filename, file_obj), purpose="assistants")
        logger.info("OpenAI file upload succeeded filename=%s file_id=%s", filename, created.id)
        return created.id
    except Exception as e:
        raise RuntimeError(f"OpenAI file upload failed for {filename!r}: {e}") from e

def cleanup_analysis_model_uploads(settings: Settings, file_ids: Iterable[str]) -> list[str]:
    """
    Delete OpenAI file uploads created for this run.
    """
    ids = [fid for fid in (str(x or "").strip() for x in file_ids) if fid]
    if not ids:
        return []
    api_key = get_ssm_parameter(settings, settings.analysis_model_api_key_ssm_parameter)
    if not api_key:
        return [f"analysis model API key missing; skipped deleting {len(ids)} OpenAI file upload(s)"]
    client = OpenAI(api_key=api_key)
    success = 0
    errors: list[str] = []
    for fid in ids:
        try:
            client.files.delete(file_id=fid)
            success += 1
        except Exception as exc:  # pragma: no cover - best-effort cleanup
            errors.append(f"analysis model delete failed for file_id {fid}: {exc}")
    logs: list[str] = []
    if success:
        logs.append(f"Deleted {success} analysis model file upload(s)")
    logs.extend(errors)
    return logs


def ensure_s3_folder(bucket: str, key: str, *, aws_region: str):
    """Ensure an S3 folder exists."""
    try:
        client = boto3.client("s3", region_name=aws_region)
        client.put_object(Bucket=bucket, Key=key)
    except ClientError as e:
        if e.response['Error']['Code'] == '404':
            client.put_object(Bucket=bucket, Key=key)
            return False
        else:
            raise
    return f"s3://{bucket}/{key}"