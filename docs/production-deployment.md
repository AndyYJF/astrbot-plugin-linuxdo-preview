# 生产部署记录

记录日期：2026-08-24

## 当前状态

- AstrBot：4.26.2，Docker 容器 `astrbot-2`
- QQ 适配器：一个已启用的 `aiocqhttp`（OneBot v11）
- 插件目录：`/AstrBot/data/plugins/astrbot_plugin_linuxdo_preview`
- 配置文件：`/AstrBot/data/config/astrbot_plugin_linuxdo_preview_config.json`
- 活跃版本：0.6.0
- 发布包：`astrbot_plugin_linuxdo_preview-0.6.0.tar.gz`
- SHA-256：`f16928e96c143dab7f056a2c07cb0bf90597a9ee38dba4f8e3bce6f1289ede84`
- 本次部署备份：`/AstrBot/data/backups/astrbot_plugin_linuxdo_preview/20260824-f16928e9-v060-r2`
- 上一个稳定版本：0.5.0，保存在本次部署备份的 `previous-plugin` 和 `previous-config-live.json`
- 生效范围：`group_allowlist` 为空，即所有接入该实例的 QQ 群与 QQ 私聊
- 抓取方式：Jina Reader 主题 HTML，经宿主 `172.19.0.1:7890` 代理
- 输出方式：aiocqhttp 正常时发送一个合并转发（首节点长图，后续节点为独立帖子图片）；T2I 失败时仍发送一个合并转发（渲染失败状态、标题/正文纯文本、相同独立帖子图片）；其他 QQ 适配器在 T2I 失败时返回纯文本预览
- 长图图片限制：每帖最多 6 张、单张预览最多 2,000,000 字节、处理后预览合计最多 6,000,000 字节
- 独立原图限制：单张最多 6,000,000 字节、单帖合计最多 12,000,000 字节
- 超时：单张图片 15 秒，最终 T2I 渲染 90 秒

0.6.0 保留 0.5.0 的正常长图与独立原图行为。T2I 超时、返回 503、空地址或无效图片时，不再丢弃已经加载的帖子图片，也不再只返回“长图生成失败”。aiocqhttp 会在同一个转发聊天记录内依次发送渲染失败状态、带标题的首帖纯文本和原有独立原图；非 aiocqhttp 返回带标题与原帖链接的纯文本。

## 部署验证

切换前，固定 SHA 候选在生产 AstrBot 4.26.2 容器内通过：

- 发布包哈希、Pillow 版本、配置 JSON、Python 编译、插件 `initialize()` 与 `terminate()`；
- 归档中存在图片加载器、90 秒 `asyncio.timeout` 和图片/渲染限制配置；
- Reader 真实公开帖抓取到标题、已知楼主正文和 41 张图片引用，未混入已知二楼文本；
- 报告主题 2795372 的“客户端支持”和“使用说明”标题保留，三个空标签锚点均未泄漏；
- 按配置选择并成功加载前 6 张图片，清洗后的正文没有远程图片 URL；
- 使用确定性有效的 960×1601 JPEG 验证正常长图消息分支，不把公共 T2I 上游容量作为部署门禁；
- 私聊和群聊 handler 各返回一个且仅一个 `Nodes`，样例均为 7 个节点（1 张长图 + 6 张独立图片）；
- Reader 同时保留外层 `original/` 原图地址和内层 `optimized/` 预览地址；
- 6 张独立图片的 OneBot 字节总数为 3,089,009，与原图转发载荷精确相等；节点顺序与楼主正文顺序一致；
- 群聊调用一次 `send_group_forward_msg`，私聊调用一次 `send_private_forward_msg`；非 aiocqhttp 回退仍是单个 `Image`；
- Reader 私有/不存在占位被归类为 `restricted`；
- AstrBot 的 aiocqhttp 群聊和私聊分支各生成一次签名有效的 `base64://` OneBot 图片段。
- 强制 T2I 抛出异常后，群聊和私聊各返回一个 8 节点 `Nodes`：1 条渲染失败状态、1 条带标题/原帖链接的正文、6 张独立原图；状态和正文位于图片之前；
- 强制失败路径的 6 张图片仍为 3,089,009 字节，与正常路径的图片数量、顺序、签名和总字节精确一致；非 aiocqhttp 返回含标题和原帖链接的纯文本；

随后备份 0.5.0 插件与配置，切换 0.6.0 并重启。切换后的独立结果：

- legacy 与 v1 插件 API 均报告目标插件已加载；
- 两个 failed-plugin API 均未报告该插件；
- 容器运行，restart count 为 0；
- WebUI HTTP 200；
- 活跃 metadata 版本为 0.6.0；
- 从活跃插件目录重新执行真实 Reader、6 图、确定性正常渲染、强制 T2I 失败、群聊/私聊 handler 和 OneBot 合并转发冒烟，再次全部通过。

部署脚本在切换后捕获 `ERR`、`HUP`、`INT`、`TERM` 并自动恢复 0.5.0；候选和活跃冒烟各有 240 秒外层限时，插件内的 T2I 渲染限时为 90 秒。R1 候选因冒烟临时文件过早清理而在切换前停止，生产当时保持 0.5.0；修正后的 R2 使用全新候选和备份路径完成部署。

自动冒烟使用捕获客户端，不会向真实 QQ 账号或群发送测试消息。需要人工观察 QQ 客户端外观时，可分别在机器人私聊和任意测试群发送：

```text
https://linux.do/t/topic/2045356
```

预期两处都只收到一个转发的聊天记录：T2I 正常时第一条是带标题的长图，后续最多 6 条各是一张独立清晰图片；T2I 失败时第一条明确提示已切换纯文本，随后是带标题的首帖正文和同一批独立清晰图片。不出现二楼正文或图片 CDN 地址。

## 回滚到 0.5.0

以下命令全部使用精确字面路径且不删除文件。只有需要撤回 0.6.0 时才执行：

```bash
docker exec astrbot-2 mv /AstrBot/data/plugins/astrbot_plugin_linuxdo_preview /AstrBot/data/backups/astrbot_plugin_linuxdo_preview/20260824-f16928e9-v060-r2/disabled-v060-plugin
docker exec astrbot-2 mv /AstrBot/data/config/astrbot_plugin_linuxdo_preview_config.json /AstrBot/data/backups/astrbot_plugin_linuxdo_preview/20260824-f16928e9-v060-r2/disabled-v060-config.json
docker exec astrbot-2 mv /AstrBot/data/backups/astrbot_plugin_linuxdo_preview/20260824-f16928e9-v060-r2/previous-plugin /AstrBot/data/plugins/astrbot_plugin_linuxdo_preview
docker exec astrbot-2 mv /AstrBot/data/backups/astrbot_plugin_linuxdo_preview/20260824-f16928e9-v060-r2/previous-config-live.json /AstrBot/data/config/astrbot_plugin_linuxdo_preview_config.json
docker restart astrbot-2
```

回滚后应验证：容器运行、WebUI 返回 200、插件 loaded=true/failed=false、metadata 版本为 0.5.0。

## 回滚后的恢复

仅在上述 0.6.0 → 0.5.0 回滚已经完整执行后使用：

```bash
docker exec astrbot-2 mv /AstrBot/data/plugins/astrbot_plugin_linuxdo_preview /AstrBot/data/backups/astrbot_plugin_linuxdo_preview/20260824-f16928e9-v060-r2/previous-plugin
docker exec astrbot-2 mv /AstrBot/data/config/astrbot_plugin_linuxdo_preview_config.json /AstrBot/data/backups/astrbot_plugin_linuxdo_preview/20260824-f16928e9-v060-r2/previous-config-live.json
docker exec astrbot-2 mv /AstrBot/data/backups/astrbot_plugin_linuxdo_preview/20260824-f16928e9-v060-r2/disabled-v060-plugin /AstrBot/data/plugins/astrbot_plugin_linuxdo_preview
docker exec astrbot-2 mv /AstrBot/data/backups/astrbot_plugin_linuxdo_preview/20260824-f16928e9-v060-r2/disabled-v060-config.json /AstrBot/data/config/astrbot_plugin_linuxdo_preview_config.json
docker restart astrbot-2
```

恢复后重新运行 loaded/failed 插件 API、WebUI 和非发送 handler 冒烟。
