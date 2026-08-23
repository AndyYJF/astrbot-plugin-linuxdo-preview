# 登录/等级权限帖子抓取调研

调研日期：2026-08-23

状态：仅调研，当前插件没有实现或启用任何登录抓取。

## 结论

技术上可行，但不能把“机器人账号看得到”直接等价为“QQ群所有成员都有权看到”。推荐路线是：

1. 使用 Discourse 官方的 **User API Key** 授权流程，只申请 `read` scope；不收集 Linux.do 用户名和密码，不使用管理员 API Key。
2. 通过固定源站的 JSON API 读取首帖 `raw` 字段；API Key 只能继承关联用户已有权限，不能提升信任等级或绕过站点权限。
3. Cloudflare 仍须独立处理。优先测试 API Key 请求能否直接通过；若仍被 challenge，则使用生产内网中的自托管浏览器 sidecar，由用户手动登录/授权并维护同源会话。
4. 登录态、Cookie、User API Key 永远不得发送给 Jina Reader、FlareSolverr 公共实例或其他第三方抓取服务。
5. 在定义 QQ 侧授权模型前，不应上线“群内被动自动转发受限帖”。一个高等级论坛账号向低权限 QQ 成员广播正文，会形成访问控制泄漏。

## 推荐认证方案

Discourse 的 User API Key 是面向桌面、移动和第三方应用的正式授权机制：客户端生成 RSA 密钥对，将用户带到 `/user-api-key/new`，用户登录并明确批准 scope，站点再把 API Key 加密返回。后续请求使用 `User-Api-Key` 请求头。Key 可由用户撤销，长期未使用也会被自动撤销。

本插件的未来版本应只申请 `read`，并将私钥/API Key 放在 Docker Secret、系统凭据存储或单独的加密 secret 文件中；不得放进 AstrBot 普通 JSON 配置、项目文件或日志。

Linux.do 是否启用了所需 User API Key scope、允许怎样的 `auth_redirect`，仍需在已登录浏览器中做一次授权兼容性验证。这不是当前匿名探针能够确认的事项。

## 推荐取数路径

授权后优先验证以下同源 GET 请求：

```text
GET https://linux.do/t/<topic_id>/posts.json?post_number=1&include_raw=true
User-Api-Key: <secret>
User-Api-Client-Id: <stable-random-client-id>
```

Discourse 当前源码在 topic posts API 中把 `include_raw` 传给 `TopicViewPostsSerializer`，同时仍通过 Guardian 检查用户是否能看见 topic/post。响应必须再次校验：

- 固定 `linux.do` HTTPS 源站和数字 topic ID；
- 只接受 `post_number == 1`；
- 只读取 `raw`，不执行正文中的任何指令、HTML 或脚本；
- 401 解释为登录材料无效/已撤销；
- 403/404 解释为账号无权访问或站点隐藏资源，绝不尝试绕过；
- `cf-mitigated: challenge` 单独归类为传输问题，不能误判成等级不足。

`/t/<topic_id>.json?include_raw=true` 可作为兼容候选，但上线前必须用 Linux.do 实例实测响应结构；不能假设所有 Discourse 版本行为完全一致。

## Cloudflare 设计

User API Key 解决的是 Discourse 身份，不自动解决 Cloudflare。当前生产网络通过直连或宿主 Clash 请求 Linux.do 都会遇到 managed challenge。因此未来设计建议分两步：

1. 先用 User API Key + 固定 User-Agent 的普通 HTTPS 客户端测试 JSON API。若 Cloudflare 对此路径放行，保持纯 HTTP 实现。
2. 若仍被 challenge，部署仅在生产内网可访问的 Playwright/Chromium sidecar。由管理员在可视浏览器中手动完成 Linux.do 登录、MFA 和 challenge；sidecar 保存受限权限的浏览器 profile，并只提供“给定数字 topic ID，返回首帖 raw”的窄接口。

sidecar 必须限制出站主机为 `linux.do`，限制入站为 AstrBot 容器网络，限制响应大小/并发/频率，且不暴露 Cookie 导出接口。浏览器 Cookie 和 `cf_clearance` 可能与 User-Agent、IP、时间窗口绑定，需要把过期视为正常运维事件。

不建议把 FlareSolverr 作为唯一链路：它适合尝试匿名 clearance，但上游对新 Cloudflare challenge 的稳定性仍有公开问题，也不适合作为登录凭据保险库。Jina Reader 只保留给当前公开帖路径。

## QQ 侧访问控制

受限正文一旦发到群里，就脱离了 Linux.do 原有的 Guardian/信任等级控制。因此未来实现至少需要选择一种明确模型：

- 最安全：每个 QQ 用户绑定自己的 Linux.do User API Key，只在私聊返回其本人有权查看的内容；
- 次选：仅允许受控 QQ 群和管理员显式命令触发，并确认群成员均具有相同访问资格；
- 不接受：使用一个高等级共享账号，在所有群被动监听并自动广播受限正文。

登录内容不得跨用户、跨群共享缓存。建议仅内存短缓存、缓存键包含授权主体、正文不落日志，停用/撤销后立即清空。

## 方案对比

| 方案 | 结论 | 主要原因 |
|---|---|---|
| Discourse User API Key（read） | 首选 | 官方授权、可撤销、可限制 scope、不需要保存密码 |
| 管理员 API Key | 拒绝 | 权限过大，泄漏影响远超只读首帖需求 |
| 直接保存用户名/密码并调用 `/session` | 不推荐 | 涉及 CSRF、MFA、登录风控和密码保管，维护/安全成本高 |
| 浏览器持久会话 sidecar | CF 必要时采用 | 能由用户手动处理 challenge/MFA，但资源和运维成本较高 |
| FlareSolverr | 仅可选实验 | 当前挑战兼容性不稳定，不能承担登录 secret 管理 |
| Jina Reader | 仅公开帖 | 第三方服务，不得接收任何认证材料或受限内容 URL 请求上下文 |

## 实施前阻断项

1. 在 Linux.do 已登录浏览器中确认 User API Key 授权页面、允许 scope 和回调限制。
2. 确认 Linux.do 站点规则是否允许此类自动化，以及受限内容能否被带出站点。
3. 决定 QQ 用户/群与 Linux.do 权限主体的绑定模型。
4. 从生产固定出口验证带 User API Key 的 JSON API 是否仍被 Cloudflare challenge。
5. 定义 secret 轮换、撤销、MFA/clearance 过期和应急停用流程。

上述五项未完成前，不建议在当前公开预览插件中加入 Cookie 或登录配置项。

## 一手资料

- [Discourse User API keys specification](https://meta.discourse.org/t/user-api-keys-specification/48536)
- [Discourse API key scope and permission model](https://meta.discourse.org/t/create-and-configure-an-api-key/230124)
- [Discourse topic posts controller (`include_raw`)](https://github.com/discourse/discourse/blob/main/app/controllers/topics_controller.rb)
- [Discourse post serializer raw visibility](https://github.com/discourse/discourse/blob/main/app/serializers/post_serializer.rb)
- [Discourse security/CSRF model](https://github.com/discourse/discourse/blob/main/docs/SECURITY.md)
- [Official Discourse MCP client and User API Key flow](https://github.com/discourse/discourse-mcp)
