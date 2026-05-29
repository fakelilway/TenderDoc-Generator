import os

from dotenv import load_dotenv
from sentence_transformers import SentenceTransformer


load_dotenv()


def main() -> None:
    try:
        model_name = os.getenv("EMBEDDING_MODEL", "BAAI/bge-large-zh-v1.5")
        device = os.getenv("EMBEDDING_DEVICE", "cpu")
        model = SentenceTransformer(model_name, device=device)
        embedding = model.encode("测试文本")
        print(f"✓ Embedding 模型加载成功，输出维度: {len(embedding)}")
    except Exception as exc:
        print(f"✗ Embedding 模型加载失败: {exc}")


if __name__ == "__main__":
    main()