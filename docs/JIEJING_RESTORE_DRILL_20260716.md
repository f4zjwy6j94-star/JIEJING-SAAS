# 捷境生产备份与隔离恢复演练证据（2026-07-16）

## 结论

- 演练状态：通过
- 演练编号：`20260716-120659`
- 数据源：生产预备环境 PostgreSQL 14
- 备份大小：`9,494,965` 字节
- 备份 SHA256：`06de57c20d04f906e34bd27b16e729c293f23ddf5bd27a4ab38a44f11c122330`
- 恢复方式：无网络、临时内存文件系统、无端口、无持久卷的一次性 PostgreSQL 14 容器
- 恢复结果：37 张 public 表恢复成功；11 张核心表逐表计数完全一致
- 云端副本：37 个有序加密分片（256 KiB，末片除外）与加密清单上传成功
- 云端全量回读：通过；重组后的 SHA256 与源备份一致
- 真实平台写入：关闭

## 核心表计数核对

| 表 | 源库 | 恢复库 |
|---|---:|---:|
| audit_logs | 13,772 | 13,772 |
| companies | 1,397 | 1,397 |
| confirmations | 92 | 92 |
| platform_connections | 1,138 | 1,138 |
| platform_data_packets | 47 | 47 |
| reports | 436 | 436 |
| secret_refs | 6 | 6 |
| stores | 1,310 | 1,310 |
| tasks | 881 | 881 |
| users | 1,397 | 1,397 |
| queue_jobs | 64 | 64 |

## 安全边界

- 主机私有备份目录权限为 700，备份文件权限为 600。
- 恢复容器使用 `--network none` 和临时内存数据目录；演练后已销毁。
- 云端副本启用服务端 AES256 加密，每个分片均有 SHA256 元数据。
- 本证据不记录数据库连接串、云端桶名、对象键、密码、Token、Secret、API Key、证书私钥或原始业务行。
- 未触发 eBay OAuth、真实 eBay 写入、付款、退款、广告、采购、改价、库存或政策修改。

## 上线门禁影响

- `backup_ready_for_paid_launch=true`
- 备份/恢复正式门禁全部通过。
- 这只证明备份与恢复能力，不代表正式公开收费已经获批。
- `production_ready=false`、`can_accept_real_customers=false`、`public_charging_allowed=false` 继续保持。
