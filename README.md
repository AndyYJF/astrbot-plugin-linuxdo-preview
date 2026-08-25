# AstrBot LINUX DO 帖子预览

面向 QQ 群聊和私聊消息的 AstrBot 插件。用户发送
`linux.do/t/.../<topic_id>` 或 `linux.do/raw/<topic_id>` 链接后，插件只读取主题首帖。
公开帖优先返回接近 LINUX DO 原生前端的长图；受限帖仅允许显式绑定的 QQ 发送者通过
Discourse 只读 User API Key 获取，并以不经过第三方渲染的文本转发返回。群聊授权默认关闭，
只有开发者同时开启群聊开关并在运行配置中填写发送者 allowlist 时才可触发。

## 当前能力

- 同时监听 QQ 群聊和私聊；`group_allowlist` 只限制群聊，不限制私聊。
- 支持带/不带协议、任意 Discourse slug、`/t/` 与 `/raw/` URL。
- 固定 Linux.do 源站与数字 topic ID，避免 SSRF 和任意 URL 抓取。
- 通过 Jina Reader 请求公开主题 HTML，并用 `#post_1 .cooked` 只选择楼主首帖正文。
- 在同一次 Reader 响应中解析主题标题、分类和首帖，不需要为标题增加第二次请求。
- aiocqhttp 成功时返回一个合并转发：首节点是 JPEG 长图，后续节点按原文顺序各放一张独立帖子原图；其他 QQ 适配器回退为单长图。
- T2I 超时、不可用或返回无效图片时仍只发送一个合并转发：先显示渲染失败状态，再发送标题/首帖纯文本，最后继续发送原顺序、原载荷的独立帖子图片；其他 QQ 适配器返回纯文本预览。
- 清理 Discourse BBCode、HTML、双向文本控制符与 CQ 注入样式文本，并对所有正文进行 HTML 转义。
- 帖子图片按原文顺序内嵌；默认最多加载 6 张，失败、超限和其余图片保留清晰占位/数量提示。
- 图片仅接受 LINUX DO/LDStatic 的 HTTPS 地址；长图使用受限缩略 JPEG，独立节点优先保留验证后的 JPEG/PNG 原始字节，其他格式才高质量转码。
- 顶部品牌与作者图标使用内联 SVG，在长图中保持清晰，不依赖外部图标资源。
- 成功缓存、同会话同帖去重、并发/响应体/正文长度限制；私聊按发送者隔离去重。
- Reader 默认硬限制为 12 请求/分钟，低于本次实测公开窗口的 20 RPM。
- 登录通道默认关闭，且必须同时启用、配置只读 secret 文件并显式填写 QQ sender allowlist；
  群聊默认不会使用登录授权。开发测试可临时允许 allowlist 中的发送者在任意群触发。
- 获准的 QQ 消息每次最多处理一个链接，登录通道独立限制为 3 请求/分钟，认证缓存
  按“QQ + 会话/群”隔离且只保存在内存中。
- 授权消息通过摘要固定的官方 Byparr 3.0.4 InvisiblePlaywright Firefox，在同一浏览器页面中
  请求 Linux.do 固定单楼 JSON；不会导出 Cookie，也不会把受限正文交给 Jina/T2I。
  aiocqhttp 返回“授权状态 + 标题/正文 + 可安全下载的独立图片”合并转发。
- 未绑定的发送者和未开启群聊授权时的群消息仍按公开通道处理；遇到受限帖只返回权限提示。

用户链接里的 `/1`、`/11` 等浏览楼层后缀不会改变输出范围。插件只提取数字 topic ID，
再构造固定主题 URL，最终仍只读取 `#post_1 .cooked`。

## 数据链路与隐私

公开主题的处理链路为：

```text
QQ 消息中的 Linux.do 链接
  -> Jina Reader（公开主题 URL，只选首帖）
  -> 插件分别下载 LINUX DO 缩略图与外层原图并在本地校验
  -> 插件清洗正文并用受限缩略 JPEG 生成本地 HTML
  -> AstrBot 配置的 T2I 服务（公开标题、首帖文本和处理后图片）
  -> QQ 合并转发（长图 + 最多 6 张独立清晰图）
     若 T2I 失败：状态提示 + 标题/正文纯文本 + 同一批独立清晰图
```

绑定 QQ 的授权链路为：

```text
绑定发送者在 QQ 私聊或显式开启的测试群中发送 Linux.do 链接
  -> 固定 Docker 内网 Byparr sidecar（只接受数字 topic ID + bearer token）
  -> 同一 InvisiblePlaywright Firefox 页面完成 CF 后请求
     https://linux.do/posts/by_number/<数字ID>/1.json?include_raw=true
     （只读 User API Key；禁止重定向；只接受楼主首帖）
  -> 插件本地清洗正文；图片只允许 Linux.do/LDStatic HTTPS
  -> QQ 合并转发（授权状态 + 标题/首帖纯文本 + 已安全取得的独立图片）
```

- 不会把 QQ 身份、群消息全文、Cookie、账号或登录材料发送给 Reader/T2I。
- Reader 和 T2I 都会接触公开帖的标题与首帖正文；T2I 还会收到处理后的公开帖子图片。若不能接受第三方处理，请勿启用本插件。
- 缓存只在插件进程内存中，重载后清空；渲染文件由 AstrBot 临时文件机制管理。
- 日志只记录 topic ID、错误类型和处理来源，不记录帖子正文。
- 登录态、等级帖正文和任何认证材料都不会交给 Jina Reader 或第三方 T2I。
- 不接受 Cookie、用户名或密码配置。User API Key 必须位于生产机绝对路径的独立 secret
  文件中，不能写入 AstrBot 普通配置、Git、聊天或日志。

## 配置建议

生产环境使用以下配置：

```json
{
  "enabled": true,
  "group_allowlist": [],
  "proxy_url": "http://172.19.0.1:7890",
  "max_links_per_message": 2,
  "cache_ttl_seconds": 1800,
  "dedup_ttl_seconds": 300,
  "reader_timeout_seconds": 45,
  "reader_requests_per_minute": 12,
  "authenticated_enabled": false,
  "authenticated_sender_allowlist": [],
  "authenticated_allow_group_messages": false,
  "authenticated_secret_file": "/AstrBot/data/secrets/astrbot_plugin_linuxdo_preview.json",
  "authenticated_timeout_seconds": 45,
  "authenticated_requests_per_minute": 3,
  "authenticated_cache_ttl_seconds": 120,
  "max_content_chars": 12000,
  "image_quality": 88,
  "max_images_per_topic": 6,
  "max_image_bytes": 2000000,
  "max_total_image_bytes": 6000000,
  "max_forward_image_bytes": 6000000,
  "max_total_forward_image_bytes": 12000000,
  "image_timeout_seconds": 15,
  "render_timeout_seconds": 90,
  "reply_on_error": true
}
```

`proxy_url` 用于 Reader 和帖子图片请求。`max_images_per_topic` 可设为 `0` 完全关闭图片下载，
有效范围为 0–12。长图由 AstrBot 的 T2I 配置生成；生产部署前必须验证 AstrBot 容器可以访问
该渲染端点。`render_timeout_seconds` 会在 T2I 不响应时终止本次渲染，并自动使用上述纯文本合并转发回退。

认证配置的 secret 格式、授权边界、Cloudflare 兼容性和启用前检查见
[V7 受限帖绑定 QQ 预览](docs/v7-authenticated-private-preview.md)。当前生产网络的普通 HTTP
请求会收到 Cloudflare challenge；Byparr 同浏览器固定首帖请求已经候选验证通过，但在只读
User API Key、绑定 QQ 和等级帖端到端验收前，生产配置仍应保持 `authenticated_enabled: false`。
不要向 Issue、聊天或普通配置粘贴 Cookie。

## 安装

把本项目中的插件运行文件复制到：

```text
AstrBot/data/plugins/astrbot_plugin_linuxdo_preview/
```

最小运行文件：

```text
main.py
metadata.yaml
_conf_schema.json
requirements.txt
linuxdo_preview/
```

随后在 AstrBot WebUI 重载插件，或重启 AstrBot 容器。重载/重启前应先备份目标插件目录
及对应配置文件。

本次生产状态、精确路径和无删除回滚步骤见
[生产部署记录](docs/production-deployment.md)。

## 测试

```bash
python -m pytest -q
python -m ruff check .
```

公开样例：

```text
https://linux.do/t/topic/2045356
```

图片下载/压缩/上限见 [V3 图片支持设计](docs/v3-image-support.md)，高清独立原图见
[V5 原图转发设计](docs/v5-original-forward-images.md)，基础长图版式见
[V2 长图设计](docs/v2-long-image-design.md)。受限帖子方案见
[登录/等级权限帖子抓取调研](docs/authenticated-posts-research.md)。标题方案的演进记录见
[标题获取调研](docs/title-research.md)。空标签标题锚点的根因和回归覆盖见
[Markdown 跳转链接显示修复](docs/markdown-link-fix.md)。
合并转发与独立清晰图片的节点布局见
[V4 合并转发图片设计](docs/v4-forward-images.md)，T2I 失败回退见
[V6 T2I 纯文本回退设计](docs/v6-t2i-text-fallback.md)，绑定 QQ 授权实现见
[V7 受限帖绑定 QQ 预览](docs/v7-authenticated-private-preview.md)。

## Byparr sidecar 许可

`sidecar/` 适配层导入并扩展 GPL-3.0 的 Byparr，按 `GPL-3.0-only` 分发；固定上游版本、
镜像 digest、源码地址和完整许可证见
[`sidecar/BYPARR-NOTICE.md`](sidecar/BYPARR-NOTICE.md)。插件其余部分通过窄 HTTP 接口与
sidecar 分离，本声明不改变其许可状态。
