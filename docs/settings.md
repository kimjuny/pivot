## 全局设置

1. 慢速重试

在stream模式下，在token返回速度慢于一定阈值时，当做本次为bad request，马上挂掉链接重试
