# AI 技能手册：使用 breakpoint() 进行自主断点调试
---
context_trigger: "When logic errors occur or variable inspection is needed in python（FastAPI server）"
target_files: ["server/app/**/*.py"]
---

## 1. 调试核心原则
当代码表现不如预期，且通过静态分析（阅读代码）无法定位问题时，**严禁盲目猜测**。应优先使用 `breakpoint()` 进入交互式调试模式。

## 2. 调试工作流 (Debug Workflow)

### 第一步：定位嫌疑区域
* **入口文件**: `server/app/main.py`
* 根据 Traceback（堆栈信息）或异常表现，确定报错前的最后一行有效代码。

### 第二步：插入断点
在代码中注入调试锚点。
* **操作**: 在 `server/app/main.py` 或相关逻辑模块中插入 `breakpoint()`。
* **示例**:
    ```python
    # server/app/main.py
    def process_request(data):
        # 嫌疑代码上方插入
        breakpoint() 
        result = transform_data(data)
        return result
    ```

### 第三步：执行与交互
运行程序。当执行流到达该行时，Python 会暂停并提供 `(Pdb)` 交互界面。
AI 应通过模拟/分析以下指令获取状态：
* `p variable_name`: 打印变量当前值。
* `n` (next): 执行下一行。
* `s` (step): 进入函数内部。
* `c` (continue): 继续运行直到下一个断点或结束。
* `l` (list): 查看当前位置前后的代码上下文。

### 第四步：分析与修复
* 对比**实际变量值**与**预期变量值**。
* 修复代码后，**务必删除所有 `breakpoint()` 语句**，确保生产代码整洁。

---

## 3. 针对 Python 3.10 的优化建议
1.  **替代旧语法**: 优先使用 `breakpoint()`，而非 `import pdb; pdb.set_trace()`。
2.  **上下文关联**: 在 `server/app/main.py` 中，如果涉及异步 (FastAPI/AnyIO)，请注意断点可能会阻塞事件循环，建议在同步逻辑块中使用。
3.  **异常捕获调试**: 如果无法确定具体位置，可以在 `try-except` 块中插入：
    ```python
    try:
        main_logic()
    except Exception as e:
        breakpoint()  # 在这里检查异常发生时的现场变量
    ```

## 4. 严禁事项
* 禁止在循环次数超过 10 次的代码块中直接放置断点（除非有条件判断），防止调试器陷入无限停顿。
* 提交代码前必须全局搜索并清理 `breakpoint()` 关键字。