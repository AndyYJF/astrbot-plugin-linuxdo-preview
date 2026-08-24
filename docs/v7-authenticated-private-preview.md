# V7 受限帖绑定 QQ 预览

日期：2026-08-24

状态：0.7.0 本地候选已实现，生产登录通道保持关闭。旧会话已撤销；当前用独立 LV1
测试账号验证授权链路和等级不足提示，LV3 正向等级帖仍需在候选通过后单次验证。

## 安全边界

- 不收集或保存 Linux.do 用户名、密码、Cookie、`_forum_session` 或 `cf_clearance`。
- 只接受 Discourse 官方、用户明确批准且可撤销的 `read` User API Key。
- 默认只有 allowlist 中的 QQ sender_id 且消息为私聊时才进入认证通道。开发测试可显式开启
  群聊，但仍只有 allowlist 中的发送者可触发，缓存键同时包含 QQ 与群号；正文会对群成员可见。
- 每条获准 QQ 消息最多处理一个 Linux.do 链接，每分钟最多三次认证请求。
- 请求目标由数字 topic ID 构造，固定为 Linux.do HTTPS 首帖 JSON；禁止跟随重定向。
- 响应只接受 `post_number == 1` 的 `raw`，403/404 视为账号无权访问，不尝试绕过。
- 认证正文和认证材料不经过 Jina Reader 或第三方 T2I。输出固定为 QQ 文本合并转发，
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

Linux 生产文件权限必须为 `0600`。运行时拒绝相对路径、符号链接、非普通文件、
超大/无效 JSON、错误站点、格式异常的 key，以及任何组/其他用户可读写权限。

## 处理流程

1. handler 用 QQ sender_id、group_id 与群聊开关做 fail-closed 授权判定。
2. 获准 QQ 消息绕过公开 Reader，直接进入认证 fetcher；未获准会话保持公开链路。
3. fetcher 从独立文件读取 key，使用固定请求头和固定数字 ID URL，且禁止重定向。
4. service 清洗首帖并写入包含 QQ sender_id 与私聊/群号的认证内存缓存，不写公开缓存。
5. handler 不调用 T2I，只构造授权状态、文本分片和已验证独立图片的合并转发。

## Cloudflare 现状

生产出口对 `/about.json` 和 `/user-api-key/new` 的匿名普通 HTTP 探针均返回
Cloudflare 403 managed challenge。这说明 User API Key 只解决 Discourse 身份，不能被假设为
自动解决 Cloudflare。

上线顺序必须是：

1. 用户在自己的已登录浏览器中批准只读 User API Key；密钥通过授权工具直接落到生产
   secret 文件，不经过聊天和普通配置。
2. 用一个用户明确指定的等级测试帖，在生产固定出口做不发 QQ 的单次 keyed probe。
3. 若仍为 challenge，保持插件认证开关关闭，改用自托管 Playwright/Chromium sidecar。
4. sidecar 只暴露“数字 topic ID -> 首帖 JSON”的内网窄接口，不暴露 Cookie 导出、
   任意 URL、写请求或批量接口；清除论坛 session Cookie，仅保留 CF clearance 并继续用
   read User API Key 做 Discourse 身份。
5. 候选通过后再通过运行配置绑定 QQ sender_id。群聊测试必须额外开启群聊开关，并确认
   测试群只有预期成员；完成后立即关闭。QQ 号不得写入源码、默认配置、测试或 Git。

## 用户需要提供的非敏感信息

- 一个测试账号能打开的受限帖 URL；LV1 可验证权限不足，LV3 用于最终正向验证；
- 允许触发认证抓取的 QQ sender_id；
- 明确确认是否允许该 QQ 在群聊触发；群聊默认关闭；
- 确认已撤销曾粘贴到聊天的旧 Linux.do 会话并重新登录；
- 同意在浏览器里批准只含 `read` scope 的 User API Key。

不需要也不能提供 Cookie、密码、短信/MFA 验证码或明文 User API Key。

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

把生成的 `device-request.json` 通过文件传输放入 sidecar 的 `runtime/bootstrap/`，不要粘贴到
聊天。启动一次性浏览器容器：

```bash
docker compose -f sidecar/compose.example.yml --profile bootstrap \
  run --service-ports --rm linuxdo-auth-bootstrap
```

noVNC 只绑定 `127.0.0.1:6080`。远程主机应通过 SSH 隧道访问
`http://127.0.0.1:6080/vnc.html`；只完成 CF 校验，不在 sidecar 中登录 Linux.do。容器使用
同一浏览器上下文发送固定 JSON，成功后写出 `device-response.json`，不在日志打印设备码。

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
docker compose -f sidecar/compose.example.yml --profile bootstrap \
  run --service-ports --rm \
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
启用登录通道。常驻 sidecar 的 `8787` 不映射到主机，只加入 AstrBot Docker 网络；noVNC
只绑定 loopback。公开 Reader 链路和当前稳定插件在整个授权阶段保持不变。

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
secret。随后在 Linux.do 撤销对应 User API Key，保留候选/旧版本目录以便恢复。缓存仅在
进程内存中，重载后清空。
