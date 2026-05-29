import os

from dotenv import load_dotenv
from openai import OpenAI


load_dotenv()


def main() -> None:
    try:
        client = OpenAI(
            api_key=os.getenv("DEEPSEEK_API_KEY"),
            base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
        )
        response = client.chat.completions.create(
            model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
            messages=[{"role": "user", "content": "请回复 OK"}],
            max_tokens=10,
        )
        print("✓ 大模型 API 调用成功:", response.choices[0].message.content)
    except Exception as exc:
        print(f"✗ 大模型 API 调用失败: {exc}")


if __name__ == "__main__":
    main()import os

from dotenv import load_dotenv
from openai import OpenAI


load_dotenv()


def main() -> None:
    try:
        client = OpenAI(
            api_key=os.getenv("DEEPSEEK_API_KEY"),
            base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
        )
        response = client.chat.completions.create(
            model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
            messages=[{"role": "user", "content": "请回复 OK"}],
            max_tokens=10,
        )
        print("✓ 大模型 API 调用成功:", response.choices[0].message.content)
    except Exception as exc:
        print(f"✗ 大模型 API 调用失败: {exc}")


if __name__ == "__main__":
    main()import os

from dotenv import load_dotenv
from openai import OpenAI


load_dotenv()


def main() -> None:
    try:
        client = OpenAI(
            api_key=os.getenv("DEEPSEEK_API_KEY"),
            base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
        )
        response = client.chat.completions.create(
            model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
            messages=[{"role": "user", "content": "请回复 OK"}],
            max_tokens=10,
        )
        print("✓ 大模型 API 调用成功:", response.choices[0].message.content)
    except Exception as exc:
        print(f"✗ 大模型 API 调用失败: {exc}")


if __name__ == "__main__":
    main()