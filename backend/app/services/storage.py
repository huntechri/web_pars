from functools import lru_cache
from pathlib import Path

import boto3
from botocore.client import Config
from dotenv import dotenv_values

from ..config import settings


def _env_file_values() -> dict[str, str]:
    env_file = Path(__file__).resolve().parents[2] / ".env"
    if not env_file.exists():
        return {}
    values = dotenv_values(env_file)
    return {str(k): str(v) for k, v in values.items() if k and v is not None}


def _resolved_storage_config() -> dict[str, str | int | None]:
    env_vals = _env_file_values()

    bucket = settings.storage_bucket or env_vals.get("APP_STORAGE_BUCKET")
    endpoint_url = settings.storage_endpoint_url or env_vals.get("APP_STORAGE_ENDPOINT_URL")
    access_key_id = settings.storage_access_key_id or env_vals.get("APP_STORAGE_ACCESS_KEY_ID")
    secret_access_key = settings.storage_secret_access_key or env_vals.get("APP_STORAGE_SECRET_ACCESS_KEY")
    region = settings.storage_region or env_vals.get("APP_STORAGE_REGION") or "auto"
    presign_expire = settings.storage_presign_expire_seconds

    raw_presign = env_vals.get("APP_STORAGE_PRESIGN_EXPIRE_SECONDS")
    if raw_presign and (not isinstance(presign_expire, int) or presign_expire <= 0):
        try:
            presign_expire = int(raw_presign)
        except Exception:
            presign_expire = 3600

    return {
        "bucket": bucket,
        "endpoint_url": endpoint_url,
        "access_key_id": access_key_id,
        "secret_access_key": secret_access_key,
        "region": region,
        "presign_expire_seconds": presign_expire,
    }


def is_object_storage_enabled() -> bool:
    conf = _resolved_storage_config()
    return bool(
        conf.get("bucket")
        and conf.get("endpoint_url")
        and conf.get("access_key_id")
        and conf.get("secret_access_key")
    )


@lru_cache(maxsize=1)
def _get_s3_client():
    conf = _resolved_storage_config()
    if not is_object_storage_enabled():
        raise RuntimeError("Object storage is not configured")

    return boto3.client(
        "s3",
        endpoint_url=conf["endpoint_url"],
        aws_access_key_id=conf["access_key_id"],
        aws_secret_access_key=conf["secret_access_key"],
        region_name=conf["region"],
        config=Config(signature_version="s3v4"),
    )


def upload_csv(local_path: Path, object_key: str) -> str:
    conf = _resolved_storage_config()
    client = _get_s3_client()
    client.upload_file(
        str(local_path),
        conf["bucket"],
        object_key,
        ExtraArgs={"ContentType": "text/csv; charset=utf-8"},
    )
    return object_key


def get_download_url(object_key: str) -> str:
    conf = _resolved_storage_config()
    client = _get_s3_client()
    return client.generate_presigned_url(
        ClientMethod="get_object",
        Params={"Bucket": conf["bucket"], "Key": object_key},
        ExpiresIn=int(conf["presign_expire_seconds"] or 3600),
    )
