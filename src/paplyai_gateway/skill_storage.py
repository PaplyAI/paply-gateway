from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Protocol

import oss2
from alibabacloud_credentials.client import Client as CredentialsClient
from alibabacloud_credentials.models import Config as CredentialsConfig

from paplyai_gateway.settings import Settings


@dataclass(frozen=True)
class StoredObject:
    key: str
    size: int
    etag: str


class SkillObjectStore(Protocol):
    def get_bytes(self, key: str, *, maximum_bytes: int) -> bytes: ...

    def get_optional_bytes(self, key: str, *, maximum_bytes: int) -> bytes | None: ...

    def put_bytes(self, key: str, value: bytes, *, content_type: str) -> StoredObject: ...

    def head(self, key: str) -> StoredObject: ...

    def iter_bytes(self, key: str, *, chunk_size: int = 256 * 1024) -> Iterator[bytes]: ...


class _CredentialsProvider(oss2.CredentialsProvider):
    def __init__(self, client: CredentialsClient) -> None:
        self._client = client

    def get_credentials(self) -> oss2.credentials.Credentials:
        value = self._client.get_credential()
        if not value.access_key_id or not value.access_key_secret:
            raise RuntimeError("Alibaba Cloud credential provider returned empty credentials")
        return oss2.credentials.Credentials(
            value.access_key_id,
            value.access_key_secret,
            value.security_token or "",
        )


class AliyunOssSkillStore:
    def __init__(self, settings: Settings) -> None:
        if settings.paply_skills_storage != "oss":
            raise RuntimeError("Aliyun OSS skill storage is not enabled")
        if settings.paply_skills_oss_credentials == "ecs_ram_role":
            credentials = CredentialsClient(
                CredentialsConfig(
                    type="ecs_ram_role",
                    role_name=settings.paply_skills_oss_ecs_role_name or None,
                    disable_imds_v1=True,
                )
            )
        else:
            credentials = CredentialsClient()
        auth = oss2.ProviderAuthV4(_CredentialsProvider(credentials))
        self._bucket = oss2.Bucket(
            auth,
            settings.paply_skills_oss_endpoint,
            settings.paply_skills_oss_bucket,
            region=settings.paply_skills_oss_region,
            connect_timeout=10,
        )

    def get_bytes(self, key: str, *, maximum_bytes: int) -> bytes:
        metadata = self.head(key)
        if metadata.size > maximum_bytes:
            raise ValueError(f"OSS object exceeds the allowed size: {key}")
        result = self._bucket.get_object(key)
        try:
            value = result.read(maximum_bytes + 1)
        finally:
            result.close()
        if len(value) > maximum_bytes:
            raise ValueError(f"OSS object exceeds the allowed size: {key}")
        return value

    def get_optional_bytes(self, key: str, *, maximum_bytes: int) -> bytes | None:
        try:
            return self.get_bytes(key, maximum_bytes=maximum_bytes)
        except KeyError:
            return None

    def put_bytes(self, key: str, value: bytes, *, content_type: str) -> StoredObject:
        result = self._bucket.put_object(
            key,
            value,
            headers={"Content-Type": content_type, "Cache-Control": "private, no-store"},
        )
        if result.status < 200 or result.status >= 300:
            raise RuntimeError(f"OSS rejected object upload: {key} ({result.status})")
        stored = self.head(key)
        if stored.size != len(value):
            raise RuntimeError(f"OSS object size verification failed: {key}")
        return stored

    def head(self, key: str) -> StoredObject:
        try:
            result = self._bucket.head_object(key)
        except oss2.exceptions.NoSuchKey as error:
            raise KeyError(key) from error
        return StoredObject(
            key=key,
            size=int(result.content_length),
            etag=str(result.etag).strip('"'),
        )

    def iter_bytes(self, key: str, *, chunk_size: int = 256 * 1024) -> Iterator[bytes]:
        result = self._bucket.get_object(key)
        try:
            while True:
                chunk = result.read(chunk_size)
                if not chunk:
                    return
                yield chunk
        finally:
            result.close()


class MemorySkillStore:
    """In-memory object storage used only by focused tests."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def get_bytes(self, key: str, *, maximum_bytes: int) -> bytes:
        value = self.objects[key]
        if len(value) > maximum_bytes:
            raise ValueError(f"object exceeds the allowed size: {key}")
        return value

    def get_optional_bytes(self, key: str, *, maximum_bytes: int) -> bytes | None:
        if key not in self.objects:
            return None
        return self.get_bytes(key, maximum_bytes=maximum_bytes)

    def put_bytes(self, key: str, value: bytes, *, content_type: str) -> StoredObject:
        del content_type
        self.objects[key] = value
        return self.head(key)

    def head(self, key: str) -> StoredObject:
        from hashlib import md5

        value = self.objects[key]
        return StoredObject(key=key, size=len(value), etag=md5(value).hexdigest())

    def iter_bytes(self, key: str, *, chunk_size: int = 256 * 1024) -> Iterator[bytes]:
        value = self.objects[key]
        for offset in range(0, len(value), chunk_size):
            yield value[offset : offset + chunk_size]
