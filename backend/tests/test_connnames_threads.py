import threading
import time
from concurrent.futures import ThreadPoolExecutor

from app.dnsmap import ConnNames


def test_connnames_concurrent_reads_writes_and_purge():
    names = ConnNames(max_conn=100, max_pair=100)
    stop = threading.Event()
    start = threading.Barrier(5)

    def writer(client):
        start.wait(timeout=2)
        for i in range(5000):
            names.add_conn(client, i % 200, "8.8.8.8", "example.com", now=1)
            names.add_conn_only(client, i % 200, "8.8.8.8", "example.com", now=1)
            names.add_pair(client, "8.8.8.8", "example.com", None, now=1)
            names.lookup(client, i % 200, "8.8.8.8")

    def purge():
        start.wait(timeout=2)
        while not stop.wait(.001):
            names.purge(now=100000)

    deadline = time.monotonic() + 2
    with ThreadPoolExecutor(max_workers=5) as pool:
        cleaner = pool.submit(purge)
        futures = [pool.submit(writer, str(i)) for i in range(4)]
        try:
            for future in futures:
                future.result(timeout=max(.001, deadline - time.monotonic()))
        finally:
            stop.set()
            cleaner.result(timeout=2)
    assert time.monotonic() < deadline
    names.purge(now=100000)
    assert not names.conn and not names.pair
