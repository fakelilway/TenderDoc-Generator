import os

import psycopg2
from dotenv import load_dotenv


load_dotenv()


def main() -> None:
    try:
        conn = psycopg2.connect(
            host=os.getenv("POSTGRES_HOST"),
            port=os.getenv("POSTGRES_PORT"),
            dbname=os.getenv("POSTGRES_DB"),
            user=os.getenv("POSTGRES_USER"),
            password=os.getenv("POSTGRES_PASSWORD"),
        )
        print("✓ PostgreSQL 连接成功")
        conn.close()
    except Exception as exc:
        print(f"✗ PostgreSQL 连接失败: {exc}")


if __name__ == "__main__":
    main()