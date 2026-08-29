# 生产部署指南

更新日期：2026-08-29，对应插件 0.9.6。

## 当前生产状态

- AstrBot：4.26.2，Docker 容器 `astrbot-2`
- QQ 适配器：一个已启用的 `aiocqhttp`（OneBot v11）
- 插件目录：`/AstrBot/data/plugins/astrbot_plugin_linuxdo_preview`
- 配置文件：`/AstrBot/data/config/astrbot_plugin_linuxdo_preview_config.json`
- 认证 sidecar：`linuxdo-auth-sidecar`（Byparr 3.0.4 同浏览器 Firefox，与 AstrBot 同一 Docker 网络，无端口发布）
- 认证材料：v2 浏览器会话 secret（0600）+ 隔离登录取得的 storage state（0600）

## 全新部署：第一层（公开帖预览）

1. 从 GitHub 获取发布包，或用 `scripts/build_package.sh` 本地打包；解压到
   `data/plugins/astrbot_plugin_linuxdo_preview/`，重启 AstrBot 或在 WebUI 重载插件。
2. 配置只保留九项；公开帖只需要：

   ```json
   {
     "enabled": true,
     "group_allowlist": [],
     "proxy_url": "http://<代理地址>:7890",
     "max_links_per_message": 2,
     "reply_on_error": true
   }
   ```

   `proxy_url` 需要能访问 Jina Reader 与 linux.do/LDStatic 图片 CDN。Jina 对机房 IP
   做信誉封锁，出口被标记时匿名请求会返回 401，需要更换出口节点或后续使用 API key。
3. 验证：向机器人发送一条公开帖链接，应收到一个合并转发（长图 + 独立原图节点）。

到这一步受限帖只会返回权限提示，不会出错。

## 全新部署：第二层（受限帖通道，可选）

前置：sidecar 与 AstrBot 容器同一 Docker 网络；宿主机有可用代理。

1. **构建 sidecar 镜像**：`docker build --target runtime -f sidecar/Dockerfile .`。
   基础镜像为指纹钉死的官方 Byparr 3.0.4；GeoIP MMDB 须提前下载并核对 SHA-256 后只读
   挂载，否则上游启动会卡在固定的 60 秒 GeoIP 下载超时。
2. **生成 v2 secret**（纯本地，不进 Git/聊天/日志）：JSON 含 `site`、
   `version: 2`、`auth_mode: "browser_session"`、随机 `sidecar_token`（32–128 位
   base64url）与随机整数 `browser_seed`；0600 存放在 AstrBot 数据目录的 `secrets/` 下。
3. **一次性登录引导**：用 `sidecar/compose.example.yml` 的 `session-login` profile 启动
   noVNC 容器（只绑宿主机 `127.0.0.1`），打开
   `http://127.0.0.1:16080/vnc.html?autoconnect=1&resize=scale`，由账号本人完成
   登录/MFA。程序检测到登录后把过滤后的 storage state 以 0600 原子写入会话目录并退出，
   引导容器即弃。登录检测接受 `payload.current_user.id` 或 `payload.id` 两种响应形状。
4. **启动运行 sidecar**：使用 compose 的 `linuxdo-auth-sidecar` 服务：UID 1000、
   cap-drop ALL、no-new-privileges、无端口发布、GeoIP/secret 只读挂载、会话目录读写挂载。
   插件通过固定主机名 `linuxdo-auth-sidecar:8787` + bearer token 调用，接口只接受数字
   topic ID。
5. **插件侧启用**：配置 `authenticated_enabled: true` 并在
   `authenticated_sender_allowlist` 中显式填写绑定 QQ；群聊触发需另开
   `authenticated_allow_group_messages`。QQ 号只写入运行配置，不进源码与 Git。
6. **验证**：绑定 QQ 私聊发送一条该账号有权查看的受限帖链接，应收到「授权状态 + 长图 +
   独立原图」合并转发。

## 运维要点

- **会话续期**：`_t` Cookie 约两月有效；sidecar 每次认证请求后自动刷新 storage state。
  过期只会返回 `session_expired` 提示，重跑一次登录引导即可。
- **回滚**：每次部署把旧版插件与配置整体保留在
  `data/backups/astrbot_plugin_linuxdo_preview/<日期>-<哈希>-<版本>/`。回滚即将目录换名
  恢复并重启 AstrBot，随后验证插件 loaded=true/failed=false 与 WebUI 200。
- **部署流程惯例**：新包先解压到隐藏候选目录做候选冒烟（真实 Reader 抓取 + 确定性渲染 +
  OneBot 序列化），通过后备份切换，健康门失败自动回滚。
- **凭证红线**：Cookie、storage state、secret 内容不进聊天、Git、普通配置与日志；
  QQ 号只存在于运行配置。

## 历史部署记录

0.6.0 及更早版本的部署验证细节与回滚命令见 Git 历史（`git log -- docs/production-deployment.md`）。
