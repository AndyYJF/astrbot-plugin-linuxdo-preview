# V7 受限帖绑定 QQ 预览

日期：2026-08-25

状态：0.8.0 隔离浏览器会话候选正在验证，生产登录通道保持关闭。用户已授权仅用测试账号
验证受限帖 `2810055`，范围固定为标题与楼主首帖、单消息一个链接、每分钟三次、不抓回复、
不批量获取；QQ sender 只写运行配置，并允许在私有测试群中验收。

2026-08-25 生产探针确认 `/user-api-key/new` 宣告 Auth API v4 与设备码支持，但匿名创建
`read` 设备授权时由 Discourse 返回 JSON `invalid_access`（HTTP 403），没有 CF challenge。
按当前 Discourse 上游实现，这表示站点允许的 User API scope 或已注册客户端 scope 不接受
本次 `read` 请求。用户随后明确授权了隔离浏览器会话方案：登录材料只在回环 noVNC 页面由
用户本人输入，侧车保存过滤后的 Linux.do Playwright storage state。这个方案不把 Cookie
粘贴进聊天/配置，也不增加任意 URL、Cookie 导出或浏览器控制 HTTP 接口。

## 安全边界

- 不收集或保存 Linux.do 用户名、密码或 MFA；不接受用户复制粘贴 Cookie。
- 支持 Discourse 官方 `read` User API Key（v1）或用户明确授权的隔离浏览器会话（v2）。
  v2 storage state 是账号凭据，只能保存在独立 `0600` 文件，不得进入聊天、Git、普通配置或日志。
- 默认只有 allowlist 中的 QQ sender_id 且消息为私聊时才进入认证通道。开发测试可显式开启
  群聊，但仍只有 allowlist 中的发送者可触发，缓存键同时包含 QQ 与群号；正文会对群成员可见。
- 每条获准 QQ 消息最多处理一个 Linux.do 链接，每分钟最多三次认证请求。
- 请求目标由数字 topic ID 构造，固定为 Linux.do HTTPS 首帖 JSON；禁止跟随重定向。
- 响应只接受 `post_number == 1` 的 `raw`，403/404 视为账号无权访问，不尝试绕过。
- 认证正文和认证材料不经过 Jina Reader。0.9.0 起授权帖与公开帖一样经本 AstrBot 配置的
  T2I 渲染长图（用户明确要求）；T2I 失败时在同一合并转发中回退纯文本。
  可安全取得的帖子图片仍以独立 QQ 图片节点发送。
- 公开缓存与认证缓存完全分离；认证缓存键包含 QQ 主体，重启即清空。

## Secret 文件

AstrBot 普通配置只记录 secret 文件的绝对路径，不记录密钥。生产文件建议放在：

```text
/AstrBot/data/secrets/astrbot_plugin_linuxdo_preview.json
```

内容格式：

```json
{
  "version": 1,
  "site": "https://linux.do",
  "user_api_key": "由授权流程直接写入，禁止粘贴到聊天或 Git",
  "user_api_client_id": "授权客户端生成的稳定随机 ID",
  "sidecar_token": "授权工具同时生成的随机 Docker 内网 bearer token"
}
```

当站点拒绝新的 `read` User API 客户端、且用户明确授权隔离会话时，使用 version 2：

```json
{
  "version": 2,
  "site": "https://linux.do",
  "auth_mode": "browser_session",
  "sidecar_token": "由部署端随机生成的 32–128 位 URL-safe bearer token",
  "browser_seed": 123456789
}
```

version 2 secret 不允许出现 `user_api_key` 或 `user_api_client_id`。它与真正的浏览器会话
文件分离；插件进程只读取 bearer token，不读取 storage state。侧车通过
`LINUXDO_SESSION_STATE_FILE=/run/session/linuxdo-storage-state.json` 读取会话文件。

Linux 生产文件权限必须为 `0600`。运行时拒绝相对路径、符号链接、非普通文件、
超大/无效 JSON、错误站点、格式异常的 key/seed，以及任何组/其他用户可读写权限。
storage state 同样要求绝对路径、普通文件、非符号链接、最大 512 KiB 和 `0600`；只保留
`linux.do` Cookie 与 `https://linux.do` localStorage，第三方登录域数据不会写入最终文件。

## 处理流程

1. handler 用 QQ sender_id、group_id 与群聊开关做 fail-closed 授权判定。
2. 获准 QQ 消息绕过公开 Reader，直接进入认证 fetcher；未获准会话保持公开链路。
3. fetcher 从独立文件读取认证模式，并把数字 topic ID 交给内网 sidecar；sidecar 在同一个
   Byparr Firefox 页面内构造固定首帖 URL。v1 添加固定 User API 请求头，v2 使用已验证的
   Linux.do 浏览器会话；两者都禁止重定向。
4. service 清洗首帖并写入包含 QQ sender_id 与私聊/群号的认证内存缓存，不写公开缓存。
5. handler 复用公开通道的缓存键隔离渲染管线构造合并转发：授权状态 + T2I 长图 + 已验证独立图片；
   T2I 失败时在同一转发中回退为授权状态 + 文本分片 + 同一批独立图片。

## 隔离浏览器会话引导

会话引导是单独的 compose profile 与 Docker build target，正常运行镜像不会安装/发布
noVNC。引导容器的 noVNC 只绑定宿主机 `127.0.0.1`，Firefox 页面流量全部走与运行侧车相同
的代理出口；HTTP sidecar 在整个登录过程中仍未启动。

准备仅用户 1000 可写的目录、version 2 secret 和固定 GeoIP 后运行：

```bash
LINUXDO_GEOIP_MMDB_FILE=/absolute/path/geoip-aio-all-2026.08.19.mmdb docker compose -f sidecar/compose.example.yml --profile session-login run --rm --service-ports linuxdo-session-login
```

只从本机或受控 SSH 隧道打开：

```text
http://127.0.0.1:16080/vnc.html?autoconnect=1&resize=scale
```

用户在该页面自行完成登录、MFA 和 CF 验证。程序只对固定
`https://linux.do/session/current.json` 做登录状态检查，不读取用户名，不打印响应；确认已
登录后过滤 storage state、以 `0600` 原子写入并退出，noVNC 随容器一起关闭。运行侧车每次
固定首帖请求前再次确认会话仍登录；过期只返回 `session_expired`，不会降级到公开 Reader。

## Cloudflare 与 Byparr 现状

生产出口对 `/about.json` 和 `/user-api-key/new` 的匿名普通 HTTP 探针均返回
Cloudflare 403 managed challenge。这说明 User API Key 只解决 Discourse 身份，不能被假设为
自动解决 Cloudflare。

已验证普通 HTTP 客户端即使重放 Byparr 浏览器取得的 UA 与 CF Cookie，仍会返回 403；因此
不能导出 Cookie 给 `aiohttp`。候选改用 Byparr 3.0.4 的同浏览器模式：Byparr 在 Firefox
页面内完成 challenge，之后仍由这个页面执行固定的 Discourse 请求。公开验证中，固定首帖
接口 `/posts/by_number/2795372/1.json?include_raw=true` 已取得 HTTP 200 与首帖 raw。

上线顺序必须是：

1. 优先尝试用户批准的只读 User API Key；若站点像当前实测一样返回 `invalid_access`，
   只有在用户明确授权后才创建 version 2 隔离会话。
2. 用一个用户明确指定的等级测试帖，在生产固定出口做不发 QQ 的单次候选 probe。
3. 保持插件认证开关关闭，由固定版本 Byparr sidecar 在同一浏览器页面中完成挑战与请求。
4. sidecar 只暴露“数字 topic ID -> 首帖 JSON”的内网窄接口，不暴露 Cookie、浏览器控制面、
   任意 URL、任意方法或批量接口；身份只能来自 `read` User API Key 或过滤后的隔离会话。
5. 候选通过后再通过运行配置绑定 QQ sender_id。群聊测试必须额外开启群聊开关，并确认
   测试群只有预期成员；完成后立即关闭。QQ 号不得写入源码、默认配置、测试或 Git。

## 用户需要提供的非敏感信息

- 一个测试账号能打开的受限帖 URL；LV1 可验证权限不足，LV3 用于最终正向验证；
- 允许触发认证抓取的 QQ sender_id；
- 明确确认是否允许该 QQ 在群聊触发；群聊默认关闭；
- 确认已撤销曾粘贴到聊天的旧 Linux.do 会话并重新登录；
- 同意在浏览器里批准只含 `read` scope 的 User API Key。

不需要也不能提供 Cookie、密码、短信/MFA 验证码或明文 User API Key；隔离会话模式由用户
直接在回环浏览器页面输入登录材料。

## 首选：设备码只读授权助手

最新 Discourse 提供设备授权端点：客户端生成设备请求，用户只在已登录浏览器中核对并
批准，客户端再轮询取得 RSA/OAEP 加密结果。它不需要自定义回调，也不需要复制 Key：

```bash
python -m tools.user_api_device_authorize start \
  --work-dir "C:/Users/<you>/AppData/Local/astrbot-linuxdo-auth"
```

打开助手显示的固定 Linux.do 授权地址，确认核对码和页面只包含 `read`，批准后运行：

```bash
python -m tools.user_api_device_authorize poll \
  --session-dir "C:/.../device-xxxxxxxxxxxxxxxx" \
  --output "C:/.../astrbot_plugin_linuxdo_preview.json"
```

若 `start` 返回 404/405，说明 Linux.do 部署版本尚不支持设备授权，可使用下面的旧版 RSA
流程。若返回 Cloudflare challenge，不要添加 Cookie，也不要用 HTML 表单替代：当前 Discourse
设备入口强制要求 JSON MIME，普通表单会返回 `invalid_access`。使用下面的 sidecar 引导。

### Cloudflare 下的无 Key URL 引导

先只在本机生成一次性 RSA 材料；私钥不会离开本机：

```bash
python -m tools.user_api_device_authorize prepare-browser \
  --work-dir "C:/Users/<you>/AppData/Local/astrbot-linuxdo-auth"
```

先下载并校验 Byparr 要求的 GeoIP MMDB，放到只有管理员可修改的位置。当前已验证的文件是
`geoip-aio-all-2026.08.19.mmdb`，SHA-256 为
`8fcea16cf10f54b8a70930eb51cd3ee8c5fd949e7b469d44c155964a156952d4`。把绝对路径写入
`LINUXDO_GEOIP_MMDB_FILE`，compose 会只读挂载它；缺少该变量时直接拒绝启动。

把生成的 `device-request.json` 通过文件传输放入 sidecar 的 `runtime/bootstrap/`，不要粘贴到
聊天。启动一次性 Byparr 容器：

```bash
LINUXDO_GEOIP_MMDB_FILE=/absolute/path/geoip-aio-all-2026.08.19.mmdb \
  docker compose -f sidecar/compose.example.yml --profile bootstrap \
  run --rm linuxdo-auth-bootstrap
```

容器使用 Byparr 的 InvisiblePlaywright Firefox 自动处理 challenge，并在同一页面内向固定
设备接口发送 JSON。成功后只写出 `device-response.json`，不在日志打印设备码或响应正文。
它不发布 noVNC、CDP、HTTP 或其他主机端口，也不提供通用浏览器代理。

`PROXY_SERVER` 是 Firefox 的显式代理；compose 示例同时设置 `HTTP_PROXY` 与
`HTTPS_PROXY`，仅 `localhost/127.0.0.1` 直连。因此页面和子资源使用同一个代理出口。
基础镜像固定为 `ghcr.io/thephaseless/byparr:3.0.4` 的多架构 digest
`sha256:874f719518f617d03a60e03411fc5d090647e1a877041e81f8dc965927c7deb6`，不会在运行时漂移。

把响应文件下载回同一授权会话目录并记录：

```bash
python -m tools.user_api_device_authorize record-browser \
  --session-dir "C:/.../device-browser-xxxxxxxxxxxxxxxx" \
  --response-file "C:/.../device-browser-xxxxxxxxxxxxxxxx/device-response.json"
```

为保持浏览器地址不带公钥或请求 token，打开普通
`https://linux.do/user-api-key/activate`，手动输入工具在本机显示的核对码，确认页面只有
`read` 后批准。随后把工具生成的 `poll-request.json` 传给同一 sidecar profile：

```bash
LINUXDO_GEOIP_MMDB_FILE=/absolute/path/geoip-aio-all-2026.08.19.mmdb \
  docker compose -f sidecar/compose.example.yml --profile bootstrap \
  run --rm \
  -e LINUXDO_DEVICE_MODE=poll \
  -e LINUXDO_DEVICE_REQUEST_FILE=/run/bootstrap/poll-request.json \
  -e LINUXDO_DEVICE_RESPONSE_FILE=/run/bootstrap/poll-response.json \
  linuxdo-auth-bootstrap
```

下载 `poll-response.json` 回授权会话目录，完成解密：

```bash
python -m tools.user_api_device_authorize complete-browser \
  --session-dir "C:/.../device-browser-xxxxxxxxxxxxxxxx" \
  --response-file "C:/.../device-browser-xxxxxxxxxxxxxxxx/poll-response.json" \
  --output "C:/.../astrbot_plugin_linuxdo_preview.json"
```

最后才把生成的 secret 以 `0600` 放入生产机 secret 目录，启动常驻 sidecar，并在候选配置中
启用登录通道。常驻 sidecar 的 `8787` 不映射到主机，只加入 AstrBot Docker 网络。
公开 Reader 链路和当前稳定插件在整个授权阶段保持不变。

实现与排障依据：

- [Byparr v3.0.4 发布页](https://github.com/ThePhaseless/Byparr/releases/tag/v3.0.4)
- [Byparr 固定 GET 入口实现](https://github.com/ThePhaseless/Byparr/blob/v3.0.4/src/endpoints.py)
- [Byparr 浏览器启动与 GeoIP 配置](https://github.com/ThePhaseless/Byparr/blob/v3.0.4/src/utils.py)
- [Byparr challenge 检测与处理](https://github.com/ThePhaseless/Byparr/blob/v3.0.4/src/challenge.py)

## 后备：旧版 RSA 回调助手

`tools/user_api_authorize.py` 实现旧版官方 RSA/OAEP 授权回调。它分两步运行，避免把明文 Key
放进命令行、终端输出或聊天：

```bash
python tools/user_api_authorize.py start \
  --work-dir "C:/Users/<you>/AppData/Local/astrbot-linuxdo-auth"
```

助手生成 4096 位临时 RSA 密钥和只申请 `read` 的授权链接。用已经重新登录 Linux.do 的
浏览器打开 `authorize.url.txt`，确认页面只显示读取权限，再批准。Linux.do 默认可能只允许
`discourse://auth_redirect`；浏览器显示该加密回调后，不要发到聊天，直接在同一台电脑运行：

```bash
python tools/user_api_authorize.py complete \
  --session-dir "C:/.../pending-xxxxxxxxxxxxxxxx" \
  --output "C:/.../astrbot_plugin_linuxdo_preview.json"
```

随后在程序提示里粘贴完整加密回调。助手会验证回调目标和 nonce、解密 payload、以私有权限
写出插件 secret，并删除临时私钥和明文 payload；它只输出文件路径和 Key 指纹，不输出 Key。
如果 Linux.do 拒绝授权参数或浏览器无法取得完整加密回调，应立即停止并记录无敏感信息的
错误现象，不得改用 Cookie。

## 回滚与停用

任何异常都先把 `authenticated_enabled` 设为 `false` 并重载插件；公开帖链路不依赖认证
secret。v1 随后在 Linux.do 撤销对应 User API Key；v2 先停止 sidecar，再由管理员删除明确的
`linuxdo-storage-state.json` 并从 Linux.do 安全设置撤销对应会话。保留候选/旧版本目录以便
恢复；缓存仅在进程内存中，重载后清空。
