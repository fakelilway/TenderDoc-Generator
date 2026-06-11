from datetime import timedelta
from pathlib import Path
from io import BytesIO
from urllib.parse import quote, urlparse

from minio import Minio

from core.config import settings


# Buckets already verified/created in this process; avoids a bucket_exists
# round-trip before every object operation.
_verified_buckets: set[str] = set()


class MinioClient:
    def __init__(self) -> None:
        parsed_url = urlparse(settings.minio_api_url)
        endpoint = parsed_url.netloc or parsed_url.path
        secure = parsed_url.scheme == "https"
        self.client = Minio(
            endpoint,
            access_key=settings.minio_root_user,
            secret_key=settings.minio_root_password,
            secure=secure,
        )

    def _ensure_bucket(self, bucket: str) -> None:
        if bucket in _verified_buckets:
            return
        if not self.client.bucket_exists(bucket):
            self.client.make_bucket(bucket)
        _verified_buckets.add(bucket)

    def upload_file(self, bucket: str, file_path, object_name: str) -> str:
        self._ensure_bucket(bucket)

        if isinstance(file_path, (bytes, bytearray)):
            data = BytesIO(file_path)
            length = len(file_path)
            self.client.put_object(bucket, object_name, data, length=length)
            return object_name

        path = Path(file_path)
        self.client.fput_object(bucket, object_name, str(path))
        return object_name

    def download_file(self, bucket: str, object_name: str, dest_path: str) -> str:
        self._ensure_bucket(bucket)
        self.client.fget_object(bucket, object_name, dest_path)
        return dest_path

    def download_bytes(self, bucket: str, object_name: str) -> bytes:
        self._ensure_bucket(bucket)
        response = self.client.get_object(bucket, object_name)
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()

    def get_presigned_url(
        self,
        bucket: str,
        object_name: str,
        expiry: int = 3600,
        response_filename: str | None = None,
    ) -> str:
        # Presigned URLs only sign a request; no bucket round-trip needed.
        response_headers = None
        if response_filename:
            encoded = quote(response_filename)
            response_headers = {
                "response-content-disposition": (
                    f"attachment; filename*=UTF-8''{encoded}"
                )
            }
        return self.client.presigned_get_object(
            bucket,
            object_name,
            expires=timedelta(seconds=expiry),
            response_headers=response_headers,
        )

    def remove_file(self, bucket: str, object_name: str) -> None:
        self._ensure_bucket(bucket)
        self.client.remove_object(bucket, object_name)


minio_client = MinioClient()
