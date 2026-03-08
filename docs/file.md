## 核心环节

- upload：接收用户上传的文件（这个文件有可能来源于本地文件，也可能来源于Clipboard API粘贴进来的）
- verify：
    - 如果是图片，则利用pillow对上传的图片进行校验，包括图片格式（目前支持jpg/jpeg/png/webp格式）、图片大小（不得超过2M，参数化`max_image_size`到config.py中）。
    - 如果是文件，则需要借助docling这个外部框架实现类型识别（目前仅支持 pdf / word / ppt / excel / md等格式）、文件大小（不得超过10M，参数化`max_file_size`到config.py中）。编码探测、页数/大小统计、是否可直接文本提取、是否疑似扫描件等
- save：对校验通过后进行本地存储（原文件存储 + 结构化信息存储）。默认到这一步就等于图片的前置流程都结束了，前端的用户应当在交互上知晓了。
- preprocess：
    - 如果哦是图片，当用户点击发送信息时，将图片进行预处理，从原图片变成base64编码。
    - 如果是文件，需要通过docling把文件转成markdown格式。
- assemble：
    - 如果是图片：将base64编码好图片，塞入LLM的参数中（completion / response / anthropic三种协议都要实现），并进行正常问答环节。
    - 如果是文件：同样地，塞入LLM的参数中（completion / response / anthropic三种协议都要实现），主要塞入到text环节就行，与用户的提问进行拼接。
- prune：每隔一段时间，服务器应当把上传并保存的文件，但是没有实际用到的文件都清理掉。

## 框架

图片处理使用了pillow，文件处理使用了docling。