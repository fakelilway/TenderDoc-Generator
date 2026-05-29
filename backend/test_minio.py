import os

from dotenv import load_dotenv
from minio import Minio


load_dotenv()


def main() -> None:
    try:
        endpoint = os.getenv("MINIO_API_URL", "http://localhost:9000")
        host = endpoint.replace("http://", "").replace("https://", "")
        secure = endpoint.startswith("https://")
        client = Minio(
            host,
            access_key=os.getenv("MINIO_ROOT_USER", "minioadmin"),
            secret_key=os.getenv("MINIO_ROOT_PASSWORD", "minioadmin"),
            secure=secure,
        )
        bucket = os.getenv("MINIO_BUCKET", "tender-files")
        if not client.bucket_exists(bucket):
            client.make_bucket(bucket)
            print(f"✓ 创建 bucket: {bucket}")
        print("✓ MinIO 连接成功")
    except Exception as exc:
        print(f"✗ MinIO 连接失败: {exc}")


if __name__ == "__main__":
    main()import os

from dotenv import load_dotenv
from minio import Minio


load_dotenv()


def main() -> None:
    try:
        endpoint = os.getenv("MINIO_API_URL", "http://localhost:9000").replace("http://", "").replace("https://", "")
        secure = os.getenv("MINIO_API_URL", "http://localhost:9000").startswith("https://")
        client = Minio(
            endpoint,
            access_key=os.getenv("MINIO_ROOT_USER", "minioadmin"),
            secret_key=os.getenv("MINIO_ROOT_PASSWORD", "minioadmin"),
            secure=secure,
        )
        bucket = os.getenv("MINIO_BUCKET", "tender-files")
        if not client.bucket_exists(bucket):
            client.make_bucket(bucket)
            print(f"✓ 创建 bucket: {bucket}")
        print("✓ MinIO 连接成功")
    except Exception as exc:
        print(f"✗ MinIO 连接失败: {exc}")


if __name__ == "__main__":
    main()import os

from dotenv import load_dotenv
from minio import Minio


load_dotenv()


def main() -> None:
    try:
        endpoint = os.getenv("MINIO_API_URL", "http://localhost:9000").replace("http://", "").replace("https://", "")
        secure = os.getenv("MINIO_API_URL", "http://localhost:9000").startswith("https://")
        client = Minio(
            endpoint,
            access_key=os.getenv("MINIO_ROOT_USER", "minioadmin"),
            secret_key=os.getenv("MINIO_ROOT_PASSWORD", "minioadmin"),
            secure=secure,
        )
        bucket = os.getenv("MINIO_BUCKET", "tender-files")
        if not client.bucket_exists(bucket):
            client.make_bucket(bucket)
            print(f"✓ 创建 bucket: {bucket}")
        print("✓ MinIO 连接成功")
    except Exception as exc:
        print(f"✗ MinIO 连接失败: {exc}")


if __name__ == "__main__":
    main()