# 生产部署记录

记录日期：2026-08-23

## 当前状态

- AstrBot：4.26.2，Docker 容器 `astrbot-2`
- QQ 适配器：一个已启用的 `aiocqhttp`（OneBot v11）
- 插件目录：`/AstrBot/data/plugins/astrbot_plugin_linuxdo_preview`
- 配置文件：`/AstrBot/data/config/astrbot_plugin_linuxdo_preview_config.json`
- 活跃版本：0.4.0
- 发布包：`astrbot_plugin_linuxdo_preview-0.4.0.tar.gz`
- SHA-256：`cf8cad43581dab3b6b2af3d4fd2576ffde7689ed1e1db93841f75e2acbb5121c`
- 本次部署备份：`/AstrBot/data/backups/astrbot_plugin_linuxdo_preview/20260824-cf8cad43-v040`
- 上一个稳定版本：0.3.1，保存在本次部署备份的 `previous-plugin` 和 `previous-config-live.json`
- 生效范围：`group_allowlist` 为空，即所有接入该实例的 QQ 群与 QQ 私聊
- 抓取方式：Jina Reader 主题 HTML，经宿主 `172.19.0.1:7890` 代理
- 输出方式：aiocqhttp 成功时发送一个合并转发（首节点长图，后续节点为独立帖子图片）；其他 QQ 适配器回退为单长图，错误仍返回短文本
- 图片限制：每帖最多 6 张、单张响应最多 2,000,000 字节、处理后图片合计最多 6,000,000 字节
- 超时：单张图片 15 秒，最终 T2I 渲染 90 秒

0.4.0 在保留 0.3.1 链接修复和 T2I 文件头校验的基础上，把成功响应改为一个 OneBot 合并转发。长图位于第一节点，已安全处理的帖子图片按楼主原文顺序各占一个后续节点，不再从 T2I 长图中裁切或二次缩放。

## 部署验证

切换前，固定 SHA 候选在生产 AstrBot 4.26.2 容器内通过：

- 发布包哈希、Pillow 版本、配置 JSON、Python 编译、插件 `initialize()` 与 `terminate()`；
- 归档中存在图片加载器、90 秒 `asyncio.timeout` 和图片/渲染限制配置；
- Reader 真实公开帖抓取到标题、已知楼主正文和 41 张图片引用，未混入已知二楼文本；
- 报告主题 2795372 的“客户端支持”和“使用说明”标题保留，三个空标签锚点均未泄漏；
- 按配置选择并成功加载前 6 张图片，清洗后的正文没有远程图片 URL；
- T2I 生成 960×4400 JPEG 长图；
- 私聊和群聊 handler 各返回一个且仅一个 `Nodes`，样例均为 7 个节点（1 张长图 + 6 张独立图片）；
- 6 张独立图片的 OneBot JPEG 字节总数为 113,283，与加载器输出精确相等；节点顺序与楼主正文顺序一致；
- 群聊调用一次 `send_group_forward_msg`，私聊调用一次 `send_private_forward_msg`；非 aiocqhttp 回退仍是单个 `Image`；
- Reader 私有/不存在占位被归类为 `restricted`；
- AstrBot 的 aiocqhttp 群聊和私聊分支各生成一次可解码 JPEG 的 `base64://` OneBot 图片段。

随后备份 0.3.1 插件与配置，切换 0.4.0 并重启。切换后的独立结果：

- legacy 与 v1 插件 API 均报告目标插件已加载；
- 两个 failed-plugin API 均未报告该插件；
- 容器运行，restart count 为 0；
- WebUI HTTP 200；
- 活跃 metadata 版本为 0.4.0；
- 从活跃插件目录重新执行全部真实 Reader、6 图、T2I、群聊/私聊 handler 和 OneBot 合并转发冒烟，再次全部通过。

部署脚本在切换后捕获 `ERR`、`HUP`、`INT`、`TERM` 并自动恢复 0.2.0；候选和活跃真实冒烟各有 210 秒外层限时，插件内的 T2I 渲染限时为 90 秒。

自动冒烟使用捕获客户端，不会向真实 QQ 账号或群发送测试消息。需要人工观察 QQ 客户端外观时，可分别在机器人私聊和任意测试群发送：

```text
https://linux.do/t/topic/2045356
```

预期两处都只收到一个转发的聊天记录：第一条是带标题的长图，后续最多 6 条各是一张独立清晰图片；不出现二楼正文或图片 CDN 地址。

## 回滚到 0.3.1

以下命令全部使用精确字面路径且不删除文件。只有需要撤回 0.4.0 时才执行：

```bash
docker exec astrbot-2 mv /AstrBot/data/plugins/astrbot_plugin_linuxdo_preview /AstrBot/data/backups/astrbot_plugin_linuxdo_preview/20260824-cf8cad43-v040/disabled-v040-plugin
docker exec astrbot-2 mv /AstrBot/data/config/astrbot_plugin_linuxdo_preview_config.json /AstrBot/data/backups/astrbot_plugin_linuxdo_preview/20260824-cf8cad43-v040/disabled-v040-config.json
docker exec astrbot-2 mv /AstrBot/data/backups/astrbot_plugin_linuxdo_preview/20260824-cf8cad43-v040/previous-plugin /AstrBot/data/plugins/astrbot_plugin_linuxdo_preview
docker exec astrbot-2 mv /AstrBot/data/backups/astrbot_plugin_linuxdo_preview/20260824-cf8cad43-v040/previous-config-live.json /AstrBot/data/config/astrbot_plugin_linuxdo_preview_config.json
docker restart astrbot-2
```

回滚后应验证：容器运行、WebUI 返回 200、插件 loaded=true/failed=false、metadata 版本为 0.3.1。

## 回滚后的恢复

仅在上述 0.4.0 → 0.3.1 回滚已经完整执行后使用：

```bash
docker exec astrbot-2 mv /AstrBot/data/plugins/astrbot_plugin_linuxdo_preview /AstrBot/data/backups/astrbot_plugin_linuxdo_preview/20260824-cf8cad43-v040/previous-plugin
docker exec astrbot-2 mv /AstrBot/data/config/astrbot_plugin_linuxdo_preview_config.json /AstrBot/data/backups/astrbot_plugin_linuxdo_preview/20260824-cf8cad43-v040/previous-config-live.json
docker exec astrbot-2 mv /AstrBot/data/backups/astrbot_plugin_linuxdo_preview/20260824-cf8cad43-v040/disabled-v040-plugin /AstrBot/data/plugins/astrbot_plugin_linuxdo_preview
docker exec astrbot-2 mv /AstrBot/data/backups/astrbot_plugin_linuxdo_preview/20260824-cf8cad43-v040/disabled-v040-config.json /AstrBot/data/config/astrbot_plugin_linuxdo_preview_config.json
docker restart astrbot-2
```

恢复后重新运行 loaded/failed 插件 API、WebUI 和非发送 handler 冒烟。
