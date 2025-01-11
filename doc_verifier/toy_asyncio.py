from urllib.parse import urlparse
import asyncio
from doc_verifier.logging_utils import setup_logging
from doc_verifier.utils import is_url, get_filename_from_url
import time
import json


# 模拟同步处理单页的函数
def process_page_sync(file_path: str, page_number: int):
    time.sleep(page_number)  # 模拟每页处理时间不同
    return {"page_number": page_number, "text": f"{time.time():.2f}这是第 {page_number} 页的内容"}


# 改进后的文档处理器
async def document_processor(queue, file_path, max_concurrent_tasks: int):
    total_pages = 6  # 假设文档有 6 页

    # 创建信号量来限制并发任务数量
    semaphore = asyncio.Semaphore(max_concurrent_tasks)

    async def process_page(page_number):
        async with semaphore:  # 限制并发任务数量
            result = await asyncio.to_thread(process_page_sync, file_path, page_number)
            await queue.put(result)

    # 并发启动所有任务
    tasks = [process_page(page) for page in range(1, total_pages + 1)]
    await asyncio.gather(*tasks)  # 等待所有任务完成
    await queue.put(None)  # 发送结束信号


async def send_single_file_result(queue: asyncio.Queue):
    next_page = 1
    results_buffer = {}
    while True:
        result = await queue.get()
        if not result:
            break
        page_number = result["page_number"]
        results_buffer[page_number] = result

        # 按顺序发送结果
        while next_page in results_buffer:
            yield f"data: {time.time():.2f}:{json.dumps(results_buffer.pop(next_page), ensure_ascii=False)}\n\n"
            next_page += 1


async def process_single_file(file_path: str, max_concurrent_tasks: int):
    queue = asyncio.Queue()
    producer_task = asyncio.create_task(
        document_processor(queue, file_path, max_concurrent_tasks)
    )

    async for result in send_single_file_result(queue):
        yield result

    await producer_task


# 测试 yield 版本
async def main_yield(file_path, max_concurrent_tasks):
    async for result in process_single_file(file_path, max_concurrent_tasks):
        print(f"{time.time():.2f}: {result}")


file_path = "/home/ubuntu/data/CWE-PQ-023AWeldingPQReport_test.pdf"
max_concurrent_tasks = 2  # 设置最大并发数为 2
asyncio.run(main_yield(file_path, max_concurrent_tasks))
