# 模式：嵌套调用

该模式有助于子任务的并发。它的工作原理是通过远程自动调用嵌套任务，使嵌套任务并发。

嵌套的任务在运行时也会消耗一定的资源，包括需要增加主节点对agent的管理负载以及agent对函数实例的运行和管理负载。在任务和运行性能之间应该做出取舍，过于细粒度的任务，会降低运行的速度。

## 代码示例

```python
# demo.py
import yr
  
yr.init()

@yr.invoke
def recursive_process(data_list):
    # 递归终止条件
    if len(data_list) <= 10:
        return sum(data_list)

    # 将任务拆分为两个子任务（分治）
    mid = len(data_list) // 2
    left_part = data_list[:mid]
    right_part = data_list[mid:]

    # 动态提交子任务：这就是“嵌套并行”
    left_ref = recursive_process.invoke(left_part)
    right_ref = recursive_process.invoke(right_part)

    # 等待子任务结果并合并
    # 注意：在大型应用中，这里配合使用 yr.wait 可以进一步优化内存
    results = yr.get([left_ref, right_ref])
    return sum(results)

# 启动顶层任务
data = list(range(100))
final_result = yr.get(recursive_process.invoke(data))
print(f"最终计算结果: {final_result}")

yr.finalize()
```
