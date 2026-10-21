# Changelog

## [0.1.0] - 2026-10-21

首个版本。

- IPFIX / NetFlow v9 流量采集，TZSP DNS 嗅探识别应用，可选 RouterOS 只读 REST 轮询。
- 内置 100+ 应用、20+ 分类的识别规则库；支持按域名 / IP 段 / 端口自定义规则，“未识别域名 Top”一键归类。
- 按 分钟 / 小时 / 天 汇总写入 MySQL（开发可用 SQLite），保留天数可配置。
- 页面：全网概览、主机监控（含详情）、应用统计（含详情）、流量流向（桑基图）、识别规则、系统设置（含 RouterOS 接入向导）。
- 中英双语，深浅色主题，适配手机。
- Docker 镜像（amd64 / arm64）发布到 GHCR（配置了 Docker Hub 密钥时同时发布到 Docker Hub）。
