## 主流LLM厂商缓存策略

① claude：显式
- 说明：https://platform.claude.com/docs/en/build-with-claude/prompt-caching
- 机制：ahthropic-protocol cache-control
- 策略名：anthropic-auto-cache（仅在anthropic compatible协议下可选）
    - 请在system、messages同等位置上，增加一个cache_control = {"type": "ephemeral"}，参考如下官方代码：
```python
import anthropic

client = anthropic.Anthropic()

response = client.messages.create(
    model="claude-opus-4-6",
    max_tokens=1024,
    cache_control={"type": "ephemeral"}, # 在这里增加cache_control，将自动全局缓存
    system="You are a helpful assistant that remembers our conversation.",
    messages=[
        {"role": "user", "content": "My name is Alex. I work on machine learning."},
        {
            "role": "assistant",
            "content": "Nice to meet you, Alex! How can I help with your ML work today?",
        },
        {"role": "user", "content": "What did I say I work on?"},
    ],
)
print(response.usage.model_dump_json())
```

② openai：隐式 guarantee
- 说明：https://developers.openai.com/api/reference/resources/responses/methods/create#responses-create-prompt_cache_key
- 机制：openai-response-protocol with `prompt_cache_key`
- 策略名：openai-response-prompt-cache-key（仅在openai response协议下可选）
    - 请在input、model同等位置上，增加一个prompt_cache_key = "${task-id}"
    - ${task-id}是动态字段，也就是ReAct下多次递归访问LLM的对应的任务的task-id

③ doubao：显式 叠加式（session缓存）
- 说明：https://www.volcengine.com/docs/82379/1602228?lang=zh
- 机制：openai-response-protocol（`previous_response_id`匹配，累加式），在累加式中为了避免cache到malformed json还需要实现支持malformed json时delete缓存的机制。
- 策略名：doubao-response-previous-id（仅在openai response协议下可选）
    - 每一轮的访问中在model、input同等位置上，增加一个caching={"type": "enabled"}表示开启缓存
    - 从第二轮访问开始，可以传入上一轮的返回id，放在访问参数的previous_response_id=xxx下。这个参数与model、input、caching等参数属于同等位置上。
    - **特别：**，该策略下，不需要你再全量输入messages，而是仅塞入增量的部分messages。
    - 示例代码如下：
```python
import os
from volcenginesdkarkruntime import Ark
 
client = Ark(
    base_url='https://ark.cn-beijing.volces.com/api/v3',
    api_key=os.getenv('ARK_API_KEY'),
)
input_text = "你是一名文学分析助手，回答需简洁明了，请根据下面内容分析《麦琪的礼物》相关问题。<麦琪的礼物小说内容>"
response = client.responses.create(
    model="doubao-seed-1-6-251015",
    input=[
        {
            "role": "system", 
            "content": input_text
        },
        {
            "role": "user",
            "content":"用5个简短的要点总结核心情节。"
        }
    ],
    caching={"type": "enabled"},
    thinking={"type": "disabled"},
)
print(response)
print(response.usage.model_dump_json())

# 在后续请求中输入缓存信息
second_response = client.responses.create(
    model="doubao-seed-1-6-251015",
    previous_response_id=response.id,
    input=[{"role": "user", "content": "以 Della 的视角写一篇日记，描述其卖掉长发前的心情。"}],
    caching={"type": "enabled"},
    thinking={"type": "disabled"},
)

print(second_response)
print(second_response.usage.model_dump_json())

third_response = client.responses.create(
    model="doubao-seed-1-6-251015",
    previous_response_id=second_response.id,
    input=[{"role": "user", "content": "根据原文节选和 Della 刚写的日记，想象 Jame 读到这篇日记时会有怎样的感受。"}],
    caching={"type": "enabled"},
    thinking={"type": "disabled"},
)
print(third_response)
print(third_response.usage.model_dump_json())
```

④ minimax：显式
- 说明：https://platform.minimaxi.com/docs/api-reference/anthropic-api-compatible-cache
- 机制：anthropic-protocol cache-control
- 策略名：anthropic-block-cache（仅在anthropic compatible协议下可选）
    - 请在system或messages中，在最后一个block下添加cache_control = {"type": "ephemeral"}，参考如下官方代码格式。当然，因为我们是ReAct的累加message机制，所以你始终只在最后一块加cache_control就可以，因为前面的message是不会变的：
```python
import anthropic

client = anthropic.Anthropic(
  base_url="https://api.minimaxi.com/anthropic",
  api_key="<your api key>"  # 替换为您的 MiniMax API Key
)

response = client.messages.create(
    model="MiniMax-M2.5",
    max_tokens=1024,
    system=[
      {
        "type": "text",
        "text": "You are an AI assistant tasked with analyzing literary works. Your goal is to provide insightful commentary on themes, characters, and writing style.\n",
      },
      {
        "type": "text",
        "text": "<the entire contents of 'Pride and Prejudice'>",
        "cache_control": {"type": "ephemeral"}
      }
    ],
    messages=[{"role": "user", "content": "Analyze the major themes in 'Pride and Prejudice'."}],
)
print(response.usage.model_dump_json())

# 使用相同的缓存内容再次调用
# 只需要更改用户消息
response = client.messages.create(.....)
print(response.usage.model_dump_json())
```

⑤ qwen：显式
- 说明：https://bailian.console.aliyun.com/cn-beijing/?#/doc/?type=model&url=2862577
- 机制：openai-completion-protocol block-cache-control
- 策略名：qwen-completion-block-cache（仅在openai completion协议下可选）
    - 与anthropic-block-cache机制一样，在最后一个block中稳定创建"cache_control": {"type": "ephemeral"}就可以

⑥ kimi：隐式 best-effort
- 说明：https://platform.moonshot.cn/docs/api/chat#字段说明
- 机制：openai-completion-protocol 通过`prompt_cache_key`可以一定程度上优化路由，提升缓存命中率 
- 策略名：kimi-completion-prompt-cache-key（仅在openai completion协议下可选）
    - 与策略②类似，默认每轮访问增加prompt_cache_key = "${task_id}"


❌glm：隐式 best-effort

❌grok：隐式 best-effort

❌gemini：隐式best effort + 显式预声明式
https://ai.google.dev/gemini-api/docs/caching?hl=zh-cn
