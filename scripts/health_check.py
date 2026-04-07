#!/usr/bin/env python3
"""Health check script to verify all services are running."""
import asyncio
import sys
from typing import Optional


async def check_redis(host: str = "localhost", port: int = 6379, password: str = "") -> tuple[bool, str]:
    try:
        import redis.asyncio as aioredis
        url = f"redis://:{password}@{host}:{port}" if password else f"redis://{host}:{port}"
        client = aioredis.from_url(url, decode_responses=True)
        await client.ping()
        info = await client.info()
        await client.aclose()
        return True, f"Redis {info.get('redis_version')} OK"
    except Exception as e:
        return False, f"Redis FAILED: {e}"


async def check_milvus(host: str = "localhost", port: int = 19530) -> tuple[bool, str]:
    try:
        from pymilvus import connections, utility
        connections.connect(alias="health", host=host, port=port)
        version = utility.get_server_version()
        connections.disconnect("health")
        return True, f"Milvus {version} OK"
    except Exception as e:
        return False, f"Milvus FAILED: {e}"


async def check_dashscope(api_key: str) -> tuple[bool, str]:
    if not api_key or api_key.startswith("sk-your"):
        return False, "DashScope SKIPPED (API key not configured)"
    try:
        import dashscope
        from dashscope import TextEmbedding
        dashscope.api_key = api_key
        resp = TextEmbedding.call(
            model="text-embedding-v3",
            input=["test"],
            text_type="query",
        )
        if resp.status_code == 200:
            return True, "DashScope text-embedding-v3 OK"
        else:
            return False, f"DashScope FAILED: {resp.code} - {resp.message}"
    except ImportError:
        return False, "DashScope SKIPPED (dashscope package not installed)"
    except Exception as e:
        return False, f"DashScope FAILED: {e}"


async def check_qwen(api_key: str) -> tuple[bool, str]:
    if not api_key or api_key.startswith("sk-your"):
        return False, "Qwen SKIPPED (API key not configured)"
    try:
        from langchain_community.chat_models.tongyi import ChatTongyi
        from langchain_core.messages import HumanMessage
        import os
        os.environ["DASHSCOPE_API_KEY"] = api_key
        llm = ChatTongyi(model="qwen-turbo")
        resp = await llm.ainvoke([HumanMessage(content="Say 'OK' only.")])
        return True, f"Qwen API OK (response: {resp.content[:30]})"
    except ImportError:
        return False, "Qwen SKIPPED (langchain-community not installed)"
    except Exception as e:
        return False, f"Qwen FAILED: {e}"


async def main():
    import os
    from dotenv import load_dotenv

    load_dotenv()

    dashscope_key = os.getenv("DASHSCOPE_API_KEY", "")
    redis_host = os.getenv("REDIS_HOST", "localhost")
    redis_port = int(os.getenv("REDIS_PORT", "6379"))
    redis_password = os.getenv("REDIS_PASSWORD", "")
    milvus_host = os.getenv("MILVUS_HOST", "localhost")
    milvus_port = int(os.getenv("MILVUS_PORT", "19530"))

    print("=" * 50)
    print(" ArXiv Agent - Service Health Check")
    print("=" * 50)

    checks = await asyncio.gather(
        check_redis(redis_host, redis_port, redis_password),
        check_milvus(milvus_host, milvus_port),
        check_dashscope(dashscope_key),
        check_qwen(dashscope_key),
        return_exceptions=False,
    )

    labels = ["Redis     ", "Milvus    ", "DashScope ", "Qwen API  "]
    all_ok = True
    for label, (ok, msg) in zip(labels, checks):
        status = "✓" if ok else "✗"
        print(f"  {status} {label}: {msg}")
        if not ok and "SKIPPED" not in msg:
            all_ok = False

    print("=" * 50)
    if all_ok:
        print("  All services OK - ready to start!")
        sys.exit(0)
    else:
        print("  Some services failed - check configuration")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
