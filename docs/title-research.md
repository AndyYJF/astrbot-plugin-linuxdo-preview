# LINUX DO 帖子标题获取调研

调研日期：2026-08-23

状态：0.2.0 已实现。

## 结论

旧版固定使用的 `/raw/<topic_id>/1` 只表示首帖正文，不提供可靠的主题标题；Jina Reader 包装该地址时返回的 `Title:` 也是空值。不能从用户链接里的 slug 推断标题，因为 slug 可能是通用的 `topic`、已经过时或被省略。

0.2.0 改为让 Reader 读取规范化主题 HTML，并用 `X-Target-Selector: #post_1 .cooked` 只选择首帖正文。Reader 包装响应的 `Title:` 在同一次请求中提供可靠主题标题，所以标题与首帖不再需要两次请求。公开样例验证了标题非空、楼主标记存在、已知二楼标记不存在。

## 候选方案

| 方案 | 准确性 | 本次实测/代价 | 结论 |
|---|---:|---|---|
| 从原始 URL slug 推断 | 低 | 无额外请求，但 `topic`/旧 slug 很常见 | 不采用 |
| Reader 读取主题 HTML + 首帖选择器 | 高 | 一次请求同时返回标题和首帖，公开样例约 11.4k 原始字符 | 0.2.0 已采用 |
| Reader 读取 `/t/<id>.json` | 高、结构化 | 公共样本约 142.5k 字符，包含 20 个 `post_number` 条目 | 过重，不建议作为单独标题请求 |
| 自托管同源元数据 sidecar | 高 | 可只返回经过长度限制的标题，但需要先解决 CF 会话与运维 | 登录/自托管阶段再评估 |

## 当前实现边界

当前标题与正文共用 topic ID 缓存，并满足：

- 只允许 `linux.do` 固定源站和数字 topic ID；
- 标题和正文共用同一次请求的超时、速率和响应体上限；
- 只解析一个有长度上限的纯文本标题，不转发主题页的其他内容；
- 标题缺失时使用“LINUX DO 主题 #ID”兜底，不让标题成为预览单点故障；
- 私有/等级帖继续在标题和正文进入格式化器之前停止处理。

## 资料来源

- [Discourse 官方 API 客户端的 topic 请求](https://github.com/discourse/discourse_api/blob/main/lib/discourse_api/api/topics.rb)
- [Discourse Meta：单个主题 JSON 与 post stream](https://meta.discourse.org/t/fetch-all-posts-from-a-topic-using-the-api/260886)
- [Discourse Meta：raw 数据语义](https://meta.discourse.org/t/get-back-the-real-raw-data-that-created-a-post/189183)
