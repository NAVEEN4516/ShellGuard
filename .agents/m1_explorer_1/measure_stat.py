import os
import time
from pathlib import Path

# Measure os.stat latency on Windows
def measure_stat_latency():
    cwd = os.getcwd()
    head_path = os.path.join(cwd, ".git", "HEAD")
    assert os.path.isfile(head_path)

    N = 5000
    t0 = time.perf_counter()
    for _ in range(N):
        mtime = os.stat(head_path).st_mtime
    elapsed = time.perf_counter() - t0
    avg_ms = (elapsed / N) * 1000
    print(f"Single os.stat latency: {avg_ms:.6f}ms ({avg_ms * 1000:.2f} microseconds)")

if __name__ == "__main__":
    measure_stat_latency()
