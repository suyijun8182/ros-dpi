# RouterOS 配置说明

下文以容器主机 IP `192.168.88.10`、路由器 LAN `192.168.88.1` 为例。命令适用于 RouterOS 7。

## 1. 流量采集（必需）

```routeros
/ip traffic-flow set enabled=yes interfaces=all active-flow-timeout=1m inactive-flow-timeout=15s
/ip traffic-flow target add dst-address=192.168.88.10 port=2055 version=ipfix
```

- `interfaces=all`：上行包在 LAN 口入方向采集，下行包在 WAN 口入方向采集，两者合起来才完整。ROS-DPI 会按 LAN 网段判断方向，并自动丢弃内网互访和路由器自身的流量，不会重复计数。
- `active-flow-timeout=1m`：长连接每分钟上报一次，统计和速率才能接近实时。
- 也可用 `version=9`（NetFlow v9），两者都支持。

**FastTrack**：被 FastTrack 的连接可能不经过 Traffic Flow，导致统计偏少。对比概览页的“WAN 实时速率”（来自接口计数）和“采集速率”可以判断。如果差距明显，可以缩小 FastTrack 范围，或者关闭它（会增加 CPU 占用）。

## 2. DNS 嗅探（应用识别，强烈建议）

```routeros
/ip firewall mangle add chain=output  protocol=udp src-port=53 action=sniff-tzsp sniff-target=192.168.88.10 sniff-target-port=37008 comment=ROSDPI-DNS
/ip firewall mangle add chain=forward protocol=udp src-port=53 action=sniff-tzsp sniff-target=192.168.88.10 sniff-target-port=37008 comment=ROSDPI-DNS
```

- `output`：路由器自己作为 DNS 服务器时，发给终端的应答。
- `forward`：终端直连外部 DNS（如 223.5.5.5）时的应答；内网自建 DNS 服务器向上游查询时的应答也走这里。
- 只镜像 DNS 应答，数据量很小。

**作用**：流量记录里只有 IP 和端口。DNS 嗅探记下“这个 IP 是哪个域名解析出来的”，ROS-DPI 才能把发往该 IP 的流量认成抖音、微信等具体应用。它不影响流量字节数统计；没有它时，流量只能按 IP 段、端口识别为 HTTPS / QUIC 等通用协议。

**内网有自己的 DNS 服务器**（例如 AdGuard Home / Pi-hole 在 192.168.88.248，DHCP 下发的 DNS 是它）：

- 终端 → 内网 DNS 在同一网段，走交换机，路由器看不到，这一段嗅探不到。这没关系：ROS-DPI 的“IP → 域名”表是全网共用的，不需要知道是哪台终端查的。
- 内网 DNS → 上游 DNS（如 223.5.5.5）的应答要经过路由器，会被上面的 `forward` 规则嗅探到，效果和终端直接查询一样。
- 前提是内网 DNS 的**上游用普通 DNS（udp/53）**。上游设成 DoH / DoT（AdGuard Home 默认的 `https://dns10.quad9.net/dns-query` 之类）时，路由器只看到加密流量，DNS 应答数会一直是 0。解决方法二选一：把上游改成普通 DNS（如 `223.5.5.5`、`119.29.29.29`）；或者把上游改成路由器地址，并在路由器上开启 `/ip dns set allow-remote-requests=yes`，这样应答由 `output` 规则嗅探。
- 内网 DNS 有缓存，缓存命中时不会再向上游查询。ROS-DPI 会把每条对应关系保留 6 到 48 小时，一般够用。
- 可以在 **系统设置 → DNS 嗅探 → 应答来源** 确认：看到 223.5.5.5 等外网地址（标为“外网”）说明上游应答已经嗅探到了。

提高识别率：

- 在 DHCP 里把 DNS 下发为路由器地址，并开启 `/ip dns set allow-remote-requests=yes`。
- 浏览器 / 系统里的“安全 DNS（DoH）”会绕过嗅探，可以在终端上关闭，或用防火墙拦截常见 DoH 地址。

### 双层 NAT（路由器下面又挂了爱快等二级路由）

二级路由的 WAN 口在 ROS-DPI 看来是一台“终端”，它后面的客户端全部藏在二次 NAT 后面：这些客户端的 DNS 查询被二级路由代理，路由器侧看不到，它们的流量只能按 IP 段归成「国内网络 / 未识别」。两步解决：

1. 让下级客户端的查询落到一台有记录的 DNS 服务器上：在二级路由的 DHCP 里把 DNS 指向下级网络自己的 DNS 服务器（如 AdGuard Home），不要用二级路由自带的 DNS 代理。
2. 在 **系统设置 → 外部数据源 → AdGuard Home** 填下级那台 DNS 服务器的地址和密码，ROS-DPI 从它的查询日志读取“谁查了哪个域名、解析出哪些 IP”，补全被 NAT 藏掉的域名。

注意：下级 DNS 服务器的上游也要用普通 DNS（udp/53），上游设成 DoH 时查询日志里仍能看到域名和结果，但应答延迟和拦截行为会不同。浏览器的“安全 DNS”同样会绕过下级 DNS，需要在下级网络里拦截常见 DoH 地址。

## 3. SNI 识别（推荐）

```routeros
/ip firewall mangle add chain=forward protocol=tcp dst-port=443 connection-bytes=0-4000 action=sniff-tzsp sniff-target=192.168.88.10 sniff-target-port=37008 comment=ROSDPI-SNI
/ip firewall mangle add chain=forward protocol=udp dst-port=443 connection-bytes=0-4000 action=sniff-tzsp sniff-target=192.168.88.10 sniff-target-port=37008 comment=ROSDPI-SNI
```

**作用**：每条 HTTPS 连接开头，终端发出的 TLS ClientHello 里带着明文的目标域名（SNI）。HTTP/3（QUIC，udp/443）的握手包虽然加密了，但密钥由包头推导、算法公开，ROS-DPI 能解开。和 DNS 嗅探相比：

- **按连接识别**：知道的是“这一条连接”访问的域名，而不是“这个 IP 最近被解析成哪个域名”。同一个 CDN IP 同时服务很多网站时（很常见），不会认错。
- **不怕加密 DNS**：终端开了 DoH / DoT，或内网 DNS 的上游用 DoH 时，DNS 嗅探失效，SNI 依然可用。
- 启用了 ECH（加密 ClientHello）的连接只能看到外层的公共名字（例如 `cloudflare-ech.com`），目前只有少数网站使用。

**开销**：`connection-bytes=0-4000` 只镜像每条连接最开始约 4KB 内客户端发出的包（通常 2 到 4 个），不会把整条连接镜像过来。连接很多时会增加一些路由器 CPU 占用，可以在 **系统设置 → 运行状态** 看 SNI 握手的数量。

**FastTrack**：被 FastTrack 的连接不经过 mangle。如果开了 FastTrack，而 SNI 握手数一直为 0，可以让 FastTrack 在连接传输一定字节之后才生效，例如：

```routeros
/ip firewall filter set [find action=fasttrack-connection] connection-bytes=10000-0
```

这样每条连接的前 10KB 走正常路径（会被嗅探），之后照常 FastTrack。

IPv6 也开了 FastTrack（ROS 7.18 起支持）时同样处理：

```routeros
/ipv6 firewall filter set [find action=fasttrack-connection] connection-bytes=10000-0
```

### IPv6（路由器开了 IPv6 时必须做）

国内宽带默认下发 IPv6，抖音、B 站、淘宝等大流量应用会优先走 IPv6。IPv6 的 DNS 应答和 HTTPS / QUIC 握手只经过 `/ipv6 firewall mangle`，只配 IPv4 规则时这部分流量只能按 IP 归类（大多落进「国内网络」）。在 IPv6 下再加一份同样的 4 条规则：

```routeros
/ipv6 firewall mangle add chain=output protocol=udp src-port=53 action=sniff-tzsp sniff-target=192.168.88.10 sniff-target-port=37008 comment=ROSDPI-DNS
/ipv6 firewall mangle add chain=forward protocol=udp src-port=53 action=sniff-tzsp sniff-target=192.168.88.10 sniff-target-port=37008 comment=ROSDPI-DNS
/ipv6 firewall mangle add chain=forward protocol=tcp dst-port=443 connection-bytes=0-4000 action=sniff-tzsp sniff-target=192.168.88.10 sniff-target-port=37008 comment=ROSDPI-SNI
/ipv6 firewall mangle add chain=forward protocol=udp dst-port=443 connection-bytes=0-4000 action=sniff-tzsp sniff-target=192.168.88.10 sniff-target-port=37008 comment=ROSDPI-SNI
```

- 镜像包可以照样发到 ROS-DPI 的 **IPv4 地址**，ROS-DPI 不需要 IPv6 地址；ROS 提示 `sniff-target` 无效时改填 ROS-DPI 的 IPv6 地址（接收端口同时监听 IPv4 / IPv6）。
- 流量采集不用另配：`/ip traffic-flow` 同时导出 IPv4 和 IPv6 的流。
- LAN 的 IPv6 前缀：配了只读 API 会自动加入；没配时在 系统设置 → 网络 手动填写。
- **系统设置 → 接入自检** 会检查：路由器有 IPv6 公网地址却没有 IPv6 嗅探规则、IPv4 / IPv6 的 FastTrack 没有限定 connection-bytes，都会提示并给出要执行的命令。

## 4. 只读 API 账号（可选）

```routeros
/user group add name=rosdpi policy=read,rest-api,api,!write,!policy,!sensitive
/user add name=rosdpi group=rosdpi password=<强密码> address=192.168.88.10
/ip service set www-ssl disabled=no   # REST API 走 HTTPS（或用 www 的 HTTP）
```

然后在 `.env` 设置：

```
ROS_URL=https://192.168.88.1
ROS_USER=rosdpi
ROS_PASSWORD=<强密码>
```

用于：DHCP 主机名和租约、地址池使用率、WAN 线路状态（PPPoE / DHCP 客户端）、ARP / IPv6 邻居（IP↔MAC）、WAN 口实时速率、路由器 CPU / 内存，以及自动发现 LAN 的 IPv6 公网前缀。ROS-DPI 只发 GET 请求，不会修改路由器配置。

> 修改了这个用户组的权限后，已登录的会话仍沿用旧权限，需要重启容器或执行 `/user active request-logout [find name=rosdpi]`。

## 5. LAN 网段

ROS-DPI 用 LAN 网段判断哪一端是终端。默认是三个私网段，以下情况需要手动修改（`.env` 的 `LAN_CIDRS`，或 **系统设置 → 网络**）：

- **双 NAT**（WAN 口也是 192.168.x.x 等私网地址）：只填内网实际网段，否则 WAN 侧地址会被当成终端。
- **IPv6**：配置了 ROS API 时会自动加入 LAN 接口上的公网前缀；否则需要手动填写。

## 排错

**系统设置 → 运行状态** 会显示：

| 现象 | 检查 |
|---|---|
| 流量采集一直“等待数据” | 容器的 udp/2055 是否映射；主机防火墙；`/ip traffic-flow target print` |
| 已处理流很多，但全部“丢弃” | LAN 网段填错 |
| DNS 应答为 0 | mangle 规则是否命中（`/ip firewall mangle print stats`）；udp/37008 是否映射；内网 DNS 的上游是否用了 DoH |
| SNI 握手为 0 | ROSDPI-SNI 规则是否命中；是否被 FastTrack 绕过（见上文） |
| 域名来源里“全网 IP 表”占比高 | 开启 SNI 识别；同一 CDN IP 上的多个网站会因此分得更准 |
| 识别率低 | 终端是否在用 DoH；在 **识别规则 → 未识别域名 Top** 里补规则 |
| 统计明显偏少 | FastTrack，见上文 |
