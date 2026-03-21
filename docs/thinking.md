## 主流LLM厂商Thinking模式开关

### Qwen（Completion）

官方文档：https://bailian.console.aliyun.com/cn-beijing/?tab=doc#/doc/?type=model&url=2870973

```python
completion = client.chat.completions.create(
    model="qwen-plus", # 选择模型
    messages=[{"role": "user", "content": "你是谁"}],    
    # 由于 enable_thinking 非 OpenAI 标准参数，需要通过 extra_body 传入
    extra_body={"enable_thinking":True},
    # 流式输出方式调用
    stream=True,
    # 使流式返回的最后一个数据包包含Token消耗信息
    stream_options={
        "include_usage": True
    }
)
```

说明：通过`extra_body={"enable_thinking": true|false}`控制

### Doubao（Completion & Response）

1. Completion协议：https://www.volcengine.com/docs/82379/1449737?lang=zh

```python
import os
from openai import OpenAI

client = OpenAI(
    # 从环境变量中读取方舟API Key
    api_key=os.environ.get("ARK_API_KEY"), 
    base_url="https://ark.cn-beijing.volces.com/api/v3",
    # 深度思考耗时更长，避免连接超时导致失败，请设置更大的超时限制，推荐为1800 秒及以上
    timeout=1800,
    )
completion = client.chat.completions.create(
    # Replace with Model ID
    model = "doubao-seed-2-0-lite-260215",
    messages=[
        {
            "role": "user",
            "content": "我要研究深度思考模型与非深度思考模型区别的课题，体现出我的专业性",
        }
    ],
    extra_body={
        "thinking": {
            "type": "disabled",  # 不使用深度思考能力
            # "type": "enabled", # 使用深度思考能力
            # "type": "auto", # 模型自行判断是否使用深度思考能力
        }
    },
)
```
说明：通过`exgtra_body.thinking.type = enabled | disabled | auto`控制

2. Response协议：https://www.volcengine.com/docs/82379/1956279?lang=zh

```
curl https://ark.cn-beijing.volces.com/api/v3/responses \
  -H "Authorization: Bearer $ARK_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
      "model": "doubao-seed-2-0-lite-260215",
      "input": "常见的十字花科植物有哪些？",
      "thinking":{"type": "enabled"},
      "stream": true
  }'
```
可以看到，是通过`thinking.type=enabled|disabled|auto`控制

### MiniMax

官方文档：https://platform.minimaxi.com/docs/api-reference/text-anthropic-api

说明：我看的没错的话，是通过`thinking`字段控制

### Claude（Anthropic）

1. Extended Thinking模式：https://platform.claude.com/docs/en/build-with-claude/extended-thinking
```python
import anthropic

client = anthropic.Anthropic()

response = client.messages.create(
    model="claude-sonnet-4-6",
    max_tokens=16000,
    thinking={"type": "enabled", "budget_tokens": 10000},
    messages=[
        {
            "role": "user",
            "content": "Are there an infinite number of prime numbers such that n mod 4 == 3?",
        }
    ],
)

# The response contains summarized thinking blocks and text blocks
for block in response.content:
    if block.type == "thinking":
        print(f"\nThinking summary: {block.thinking}")
    elif block.type == "text":
        print(f"\nResponse: {block.text}")
```
在Extended Thinking模式下（通过thinking.type = enabled控制）还要配置额外的budget_tokens参数（default to 10000）

2. Adaptive Thinking模式：https://platform.claude.com/docs/en/build-with-claude/adaptive-thinking
```python
import anthropic

client = anthropic.Anthropic()

response = client.messages.create(
    model="claude-opus-4-6",
    max_tokens=16000,
    thinking={"type": "adaptive"},
    output_config={"effort": "medium"},
    messages=[{"role": "user", "content": "What is the capital of France?"}],
)

print(response.content[0].text)
```
在Adaptive Thinking模式下（通过thinking.type = adaptive控制），还要额外配置effort = max、high(default)、medium、low字段

### ChatGPT（Response）

```python
from openai import OpenAI

client = OpenAI()

prompt = """
Write a bash script that takes a matrix represented as a string with 
format '[1,2],[3,4],[5,6]' and prints the transpose in the same format.
"""

response = client.responses.create(
    model="gpt-5.4",
    reasoning={"effort": "low"},
    input=[
        {
            "role": "user", 
            "content": prompt
        }
    ]
)

print(response.output_text)
```
通过`reasoning.effort`控制，还要额外配置none、low、medium、high、xhigh值

### GLM（Copmletion）

官方文档：https://docs.bigmodel.cn/cn/guide/capabilities/thinking#python-sdk
```
curl --location 'https://open.bigmodel.cn/api/paas/v4/chat/completions' \
--header 'Authorization: Bearer YOUR_API_KEY' \
--header 'Content-Type: application/json' \
--data '{
    "model": "glm-5",
    "messages": [
        {
            "role": "user",
            "content": "详细解释量子计算的基本原理，并分析其在密码学领域的潜在影响"
        }
    ],
    "thinking": {
        "type": "enabled"
    },
    "max_tokens": 4096,
    "temperature": 1.0
}'
```
可以看到是通过`thinking.type = enabled|disabled`控制。

### MiMo（Completion & Anthropic）

1. Completion：https://platform.xiaomimimo.com/#/docs/api/chat/openai-api
```
curl --location --request POST 'https://api.xiaomimimo.com/v1/chat/completions' \
--header "api-key: $MIMO_API_KEY" \
--header "Content-Type: application/json" \
--data-raw '{
    "model": "mimo-v2-pro",
    "messages": [
        {
            "role": "system",
            "content": "You are MiMo, an AI assistant developed by Xiaomi. Today is date: Tuesday, December 16, 2025. Your knowledge cutoff date is December 2024."
        },
        {
            "role": "user",
            "content": "please introduce yourself"
        }
    ],
    "max_completion_tokens": 1024,
    "temperature": 1.0,
    "top_p": 0.95,
    "stream": false,
    "stop": null,
    "frequency_penalty": 0,
    "presence_penalty": 0,
    "thinking": {
        "type": "disabled"
    }
}'
```
可以看到是通过`thinking.type=enabled|disabled`两个值来控制的

2. Anthropic：https://platform.xiaomimimo.com/#/docs/api/chat/anthropic-api
```
curl --location --request POST 'https://api.xiaomimimo.com/anthropic/v1/messages' \
--header "api-key: $MIMO_API_KEY" \
--header "Content-Type: application/json" \
--data-raw '{
    "model": "mimo-v2-pro",
    "max_tokens": 1024,
    "system": "You are MiMo, an AI assistant developed by Xiaomi. Today is date: Tuesday, December 16, 2025. Your knowledge cutoff date is December 2024.",
    "messages": [
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": "please introduce yourself"
                }
            ]
        }
    ],
    "top_p": 0.95,
    "stream": false,
    "temperature": 1.0,
    "stop_sequences": null,
    "thinking": {
        "type": "disabled"
    }
}'
```
可以看到是通过`thinking.type=enabled|disabled`两个值来控制的

### Kimi（Completion）

官方文档：https://platform.moonshot.cn/docs/guide/kimi-k2-5-quickstart#%E5%8F%82%E6%95%B0%E5%8F%98%E5%8A%A8%E8%AF%B4%E6%98%8E
```
$ curl https://api.moonshot.cn/v1/chat/completions \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer $MOONSHOT_API_KEY" \
    -d '{
        "model": "kimi-k2.5",
        "messages": [
            {"role": "user", "content": "你好"}
        ],
        "thinking": {"type": "disabled"}
   }'
```
可见是通过`thinking.type=enabled|disabled`控制

### DeepSeek（Completion）

官方文档：https://api-docs.deepseek.com/zh-cn/guides/thinking_mode
```python
response = client.chat.completions.create(
  model="deepseek-chat",
  # ...
  extra_body={"thinking": {"type": "enabled"}}
)
```
可见是通过`thinking.type=enabled|disabled`控制

