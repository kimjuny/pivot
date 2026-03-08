## 全局设置

1. 慢速重试

在stream模式下，在token返回速度慢于一定阈值时，当做本次为bad request，马上挂掉链接重试

2. 临时文件

- expire_minutes: 对话过程中的临时文件默认过期时间。
- max_size: 上传文件的最大大小（bytes）。
