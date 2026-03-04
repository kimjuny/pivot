

模式1：

system_prompt中明确要求LLM返回5种action，其中包含了action_type = CALL_TOOL，同时要求LLM在CALL_TOOL时直接在content中返回要调用的函数。

问题：部分大模型如果想要调用tool，有时候会直接返回成action_type = {tool_name}，本质的缺陷来源于tool call发生在content中不如在native tool call的槽位中稳定。

加强办法：兼容action_type = {tool_name}的不规则但可理解的情形。

模式2：

system_prompt中明确要求LLM返回5种action，但action_type = CALL_TOOL时要求LLM必须调用native tool call而不是在content中返回要调用的对象（事实上也把content中如何调用tool的说明从prompt中去掉了）。

问题：有时部分模型会发生，action_type = CALL_TOOL，但是却不返回native tool call

办法1：加强action_type = CALL_TOOL时必须返回native tool call的提示词作为缓解。本质上是双轨（content & tool）生成不同步的问题。
✅办法2：去掉action_type = CALL_TOOL。提示词中讲明，要么就选一个action_type = XXX去作答，要么就去native tool call。

模式3：

全部function化，让agent的所有返回只能是native tool call，content中只放observe → thought细节信息，而所有的action中需要LLM输出的内容，都可以写在tool的parameter中（比如param_plan = "具体计划"）
