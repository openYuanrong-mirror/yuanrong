import yr


@yr.instance
class Counter:
    def get(self):
        return 1
conf = yr.Config()
conf.log_level="DEBUG"
conf.in_cluster = False
yr.init(conf)
#yr.init()

import time
from datetime import datetime

for i in range(10):
    t1 = datetime.now()
    c = Counter.invoke()
    yr.get(c.get.invoke())
    t2 = datetime.now()

    diff_ms = (t2 - t1).total_seconds() * 1000
    print(f"create elapsed: {diff_ms:.1f} ms")

    t1 = datetime.now()
    yr.get(c.get.invoke())
    t2 = datetime.now()

    diff_ms = (t2 - t1).total_seconds() * 1000
    print(f"invoke elapsed: {diff_ms:.1f} ms")
    c.terminate()

