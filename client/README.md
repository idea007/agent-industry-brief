# Industry Brief Web

行业新闻简报的 Web 客户端。

主要页面同时承载：

- 行业新闻卡片信息流。
- 关注行业与来源管理。
- AI 摘要、重要度和可信度。
- Markdown 新闻详情与原始来源。
- 扫描状态和辅助运行信息。
- 服务端不可用时明确显示未连接空态，不生成模拟新闻。

完整启动和测试说明见[项目 README](../README.md)。

## 环境变量

| 变量 | 默认值 | 作用 |
| --- | --- | --- |
| `RADAR_API_URL` | `http://127.0.0.1:8000` | Next.js 转发同源 `/api` 请求的目标。在开发启动或生产构建时设置 |
| `NEXT_PUBLIC_API_BASE_URL` | 空（同源 `/api`） | 在构建时设置，使浏览器直连 FastAPI 地址。跨源时需配置服务端 CORS |

## 常用命令

```bash
npm ci
npm run dev
npm run build
npm start
npm run lan
npm test
npm run lint
```

`npm run lan` 会构建并启动局域网模式，手机与电脑连接同一 Wi-Fi 后可直接打开
终端显示的 `http://局域网IP/`。按 `Ctrl+C` 同时停止页面、API 和局域网入口。

要求 Node.js 22.13 或更高版本。
