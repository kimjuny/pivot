## 两段式输出

同一轮里允许模型输出：
一个很短、可解析的 JSON（只包含元信息 + 校验字段）
紧随其后一个“原样 payload 区块”（不要求 JSON 转义）

示例（概念）：
```
JSON 里只写：action=write_file, path, encoding, payload_format, payload_sha256
payload 放在 JSON 之后，用明确的哨兵标记包起来（例如 <<<PAYLOAD>>> ... <<<END_PAYLOAD>>>）
```

执行器流程：
- 先只 parse 第一段 JSON
- 再按标记提取 payload 原文
- 对 payload 做 hash 校验（对上 JSON 里的 sha256 才执行写文件）

优势
- JSON 永远短，闭合概率极高
- payload 无需转义，HTML5 再乱也不影响 JSON
- hash 校验能防“提取错段/截断”
> 这其实就是“结构化控制面（JSON） + 非结构化数据面（payload）”的分离。


4) 执行器层：做“自动修复 + 安全重试”兜底

你可以在解析失败时做两层兜底：

兜底 1：JSON repair（确定性修复）

常见修复：

补齐缺失的 "、}、]

去掉尾随逗号

把非法控制字符转义

截断到最后一个完整的 }

这层要小心：只能做语法修复，不要改语义。修复后还要 schema 校验。

兜底 2：让模型“只修复 JSON，不改内容”

重试提示固定成：

“下面是你上一次输出的文本，请仅输出一个可解析 JSON，保持字段和值语义不变，不要新增解释。”

这种“修复回合”通常成功率很高。