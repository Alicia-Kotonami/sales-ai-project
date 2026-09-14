import os
import redis
import psycopg2
from dotenv import load_dotenv

# 加载 .env 文件
load_dotenv()

def test_pg():
    conn = psycopg2.connect(
        host=os.getenv("POSTGRES_HOST"),
        port=os.getenv("POSTGRES_PORT"),
        user=os.getenv("POSTGRES_USER"),
        password=os.getenv("POSTGRES_PASSWORD"),
        dbname=os.getenv("POSTGRES_DB")
    )
    cur = conn.cursor()
    cur.execute("SELECT version();")
    print("✅ PostgreSQL 连接成功：", cur.fetchone())
    cur.close()
    conn.close()

def test_redis():
    r = redis.Redis(
        host=os.getenv("REDIS_HOST"),
        port=int(os.getenv("REDIS_PORT")),
        password=os.getenv("REDIS_PASSWORD"),
        db=int(os.getenv("REDIS_DB")),
        decode_responses=True
    )
    print("✅ Redis ping 返回：", r.ping())

if __name__ == "__main__":
    test_pg()
    test_redis()
