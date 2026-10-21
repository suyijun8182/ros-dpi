# Changelog

## [0.1.2] - 2026-10-22

debug2

- 默认部署方式改为连接用户已有的 MySQL：`docker-compose.yml` 只包含 ROS-DPI 一个服务。
- README 新增“准备数据库”：建库、建账号、授权的 SQL，命令行与图形界面（phpMyAdmin、NAS 数据库管理等）的操作方法，远程连接与 `127.0.0.1` 的注意事项，以及常见连接错误的排查方法。
- 自带 MySQL 的部署方式移到 `docker-compose.with-mysql.yml`，供还没有 MySQL 的用户使用。

## [0.1.1] - 2026-10-22

debug1

- README 与 Docker Hub 页面直接贴出完整的 `docker-compose.yml`；compose 改为自包含，不再需要 `.env` 文件。
- 新增“首次使用”说明：首次打开网页只需设置管理员密码，MySQL 无需手动配置；补充使用已有 MySQL、修改密码、忘记管理员密码的方法。
- 使用外部 MySQL 时，数据库不存在会自动创建（需要账号有建库权限）。
- compose 默认镜像改为 Docker Hub（`suyijun8182/ros-dpi`），GHCR 同步发布。

## [0.1.0] - 2026-10-21

首个版本。

- IPFIX / NetFlow v9 流量采集，TZSP DNS 嗅探识别应用，可选 RouterOS 只读 REST 轮询。
- 内置 100+ 应用、20+ 分类的识别规则库；支持按域名 / IP 段 / 端口自定义规则，“未识别域名 Top”一键归类。
- 按 分钟 / 小时 / 天 汇总写入 MySQL（开发可用 SQLite），保留天数可配置。
- 页面：全网概览、主机监控（含详情）、应用统计（含详情）、流量流向（桑基图）、识别规则、系统设置（含 RouterOS 接入向导）。
- 中英双语，深浅色主题，适配手机。
- Docker 镜像（amd64 / arm64）发布到 GHCR（配置了 Docker Hub 密钥时同时发布到 Docker Hub）。
