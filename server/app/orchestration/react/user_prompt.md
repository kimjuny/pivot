## 4. 可用工具
```json
{{tools_description}}
```
- 名称、参数等必须严格匹配

## 5. Session-Memory
- short-term：仅当前 recursion
- session-memory：跨对话轮次持久化
- 仅在ANSWER时可提交修改

以下为真实注入的session-memory
```json
{{session_memory}}
```

## 6. Related Skills

- Skills如有注入，请仔细阅读，**并立即采取`action = RE_PLAN`仔细制定策划执行计划**，在step的`specific_description`中讲计划用哪些tools/functions

```json
{{skills}}
```