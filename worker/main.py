import os
from redis import Redis
from rq import Queue

redis_conn = Redis(host=os.getenv("REDIS_HOST"), port=os.getenv("REDIS_PORT"))
queue = Queue("messages", connection=redis_conn)

def test_job(name):
    print(f"Processing job: {name}")

if __name__ == "__main__":
    # пример добавления тестовой задачи
    job = queue.enqueue(test_job, "Hello World")
    print(f"Job queued: {job.id}")
