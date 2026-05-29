import os

import redis
from dotenv import load_dotenv


load_dotenv()


def main() -> None:
    try:
        client = redis.Redis(
            host=os.getenv("REDIS_HOST", "localhost"),
            port=int(os.getenv("REDIS_PORT", "6379")),
            decode_responses=True,
        )
        client.ping()
        print("✓ Redis 连接成功")
    except Exception as exc:
        print(f"✗ Redis 连接失败: {exc}")


if __name__ == "__main__":
    main()