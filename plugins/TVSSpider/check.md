
单聊时，发送VTS 绿皮书，日志记录：

2025-05-19 15:41:56 xxxbot-pad  | 2025-05-19 15:41:56 | INFO     | utils/xybot:486 | 开始异步更新发送者联系人信息: qinxiaoqiang2002
2025-05-19 15:41:56 xxxbot-pad  | 2025-05-19 15:41:56 | INFO     | utils/xybot:490 | 完成发送者联系人信息更新: qinxiaoqiang2002, 状态: success
2025-05-19 15:41:56 xxxbot-pad  | 2025-05-19 15:41:56 | INFO     | utils/xybot:579 | 收到文本消息: 消息ID:2085968759 来自:qinxiaoqiang2002 发送人:qinxiaoqiang2002 @:[] 内容:TVS 绿皮书
2025-05-19 15:41:56 xxxbot-pad  | 2025-05-19 15:41:56 | INFO     | plugins/FastGPT/main:357 | Calling FastGPT API for text query. ChatId: qinxiaoqiang2002_default_text 


群聊时，发送后，日志记录
2025-05-19 15:43:36 xxxbot-pad  | 2025-05-19 15:43:36 | INFO     | utils/xybot:478 | 开始异步更新群聊信息: 34448299803@chatroom
2025-05-19 15:43:36 xxxbot-pad  | 2025-05-19 15:43:36 | INFO     | utils/xybot:482 | 完成群聊信息更新: 34448299803@chatroom, 状态: success
2025-05-19 15:43:36 xxxbot-pad  | 2025-05-19 15:43:36 | INFO     | utils/xybot:579 | 收到文本消息: 消息ID:1891091921 来自:34448299803@chatroom 发送人:qinxiaoqiang2002 @:[] 内容:TVS 绿皮书
2025-05-19 15:43:39 xxxbot-pad  | 2025-05-19 15:43:39 | INFO     | utils/xybot:478 | 开始异步更新群聊信息: 34448299803@chatroom
2025-05-19 15:43:39 xxxbot-pad  | 2025-05-19 15:43:39 | INFO     | utils/xybot:482 | 完成群聊信息更新: 34448299803@chatroom, 状态: success
2025-05-19 15:43:39 xxxbot-pad  | 2025-05-19 15:43:39 | INFO     | utils/xybot:579 | 收到文本消息: 消息ID:1995942690 来自:34448299803@chatroom 发送人:wxid_v4cr5q0cdqiu22 @:['qinxiaoqiang2002'] 内容:@晓强 🔍 找到 6 条与"绿皮书"相关的内容

注意下日志的顺序，看起utils/xybot:579收到了不同的格式，内容。

单聊时，发送天气触发词，可以响应
2025-05-19 15:44:54 xxxbot-pad  | 2025-05-19 15:44:54 | INFO     | utils/xybot:482 | 完成群聊信息更新: 34448299803@chatroom, 状态: success
2025-05-19 15:44:54 xxxbot-pad  | 2025-05-19 15:44:54 | INFO     | utils/xybot:579 | 收到文本消息: 消息ID:591863116 来自:34448299803@chatroom 发送人:wxid_v4cr5q0cdqiu22 @:['qinxiaoqiang2002'] 内容:@晓强 

utils/xybot:579的处理内容，和格式相似，有回复。看起来，单聊时的格式可能有差异，会不会这里需要调整，参考群聊格式改造一下。