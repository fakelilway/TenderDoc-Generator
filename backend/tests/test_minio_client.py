"""MinIO 客户端连接池超时配置测试。

2026-07-29 真实事故:一次 Docker 端口转发抽风让解析线程卡在 get_object
半个多小时(无超时=无限等),项目状态永远停在"解析中"。此后连接池必须带
超时与有限重试,超时后异常冒出走失败分支,不许静默挂死。
"""
from utils.minio_client import _pooled_http_client


def test_pooled_http_client_has_timeouts_and_bounded_retries() -> None:
    pool = _pooled_http_client()
    timeout = pool.connection_pool_kw["timeout"]
    assert timeout.connect_timeout == 10
    assert timeout.read_timeout == 120
    retries = pool.connection_pool_kw["retries"]
    assert retries.total == 2
