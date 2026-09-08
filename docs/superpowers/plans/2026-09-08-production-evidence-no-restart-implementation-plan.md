# 生产证据刷新不重启：实施计划

用户已确认设计：`../specs/2026-09-08-production-evidence-no-restart-design.md`。本计划只实施这项修缮；不重新设计产品，不部署，不调用真实业务 provider。

## 分工与顺序

1. **证据读写最小纵切片。** 新 `runtime_evidence.py` 只接收六项证据；新 snapshot CLI 使用同一验证器，原子导出。先以旧进程环境固定不变的合成证据更新测试得到 RED，再接入 `backup_plan.py` / `monitoring.py` 得到 GREEN。非法、缺失和权限错误必须失败关闭，不回落旧 env。
2. **定时任务。** 保留探针、结果合同、镜像/路径信任、锁和 env drift 守卫。探针前证明 API/Worker 支持协议且只读挂载正确；探针后发布快照，核验同容器同镜像与健康，不再例行重建。逐项保留失败短路、部分成功和安全开关保护。
3. **首次迁移与回滚。** Compose 注入固定新路径和目录只读挂载；在候选启动前以候选精确镜像从真实已有 env 证据初始化。dry-run 不创建目录/快照，初始化失败不切换。保留旧 env 证据和回滚数据。两文件双写失败不得标整轮成功。
4. **端到端隔离验收与独立审查。** 同进程真实请求保持完整响应，证据替换后真实备份/监控看到新值，旧/未来证据仍被拒绝。覆盖坏 schema、重复键、未知字段、大小限制、符号链接、权限、原子失败、模式误配置和持有中的请求。只使用合成数据与本次自建进程，不在生产制造中断。
5. **发布前本地收口。** 专项、部署锁/回滚/runner合同、秘密扫描、JS语法和新的完整门禁。冻结时排除原3用户dirty，上一轮文案修复保留；未通过不打包/申请正式apply。完成后更新当前执行索引，报告“本地通过”与“生产未变”的边界。

## 文件所有权

- Core 子任务：新运行时证据模块、CLI、专项；备份与监控两个消费者。
- Timer 子任务：刷新脚本、对应守卫测试。
- 主代理：Compose、release apply、发布工具/合同、门禁登记、集成验收、文档。
- 禁止修改：当前用户 dirty 的 `readiness.py`、`test_jiejing_phase2_response_boundary_hardening.py`、`test_jiejing_platform_trial_activation_guard.py`。

## 协议

- `JIEJING_RUNTIME_EVIDENCE_FILE=/run/jiejing-production-evidence/current.json`；完全未设置时兼容旧 env，显式设置后的错误不可 fallback。
- JSON 精确 `{version:1,evidence:{六项}}`；摄取标志为 boolean，其余为带时区 ISO 时间。上限16KiB，无秘密、云ID、业务权限。
- writer：`python tools/jiejing_runtime_evidence_snapshot.py --env-file <trusted-absolute> --output-dir <trusted-absolute>`；成功输出固定结构、协议版本和证据SHA，不输出值。`--check-capability` 只校验协议代码存在，零读取/零写入。
- 生产目录 root:root 0755，current.json root:root 0644，可信父路径无symlink/不允许组或其他用户写入。仅读者不修改 env。

## 完成定义

新同源测试支持：日常刷新证据无需重启；失效证据不假绿；首次迁移、失败与回滚安全。它不等于生产零停机，也不等于所有历史502、模型可用性、客服自动回复或真实eBay发布均已解决。

## 本地实施结果

1–4已实现并完成独立复核；时区极值转换溢出和递归解析异常均经真实负例修复。最终运行时专项19/19（含真实在途HTTP与writer）、定时维护守卫、部署channel、四项runner/staging/cloud合同、前端版本合同、JS语法与秘密扫描通过。尚需干净冻结候选的新完整228项门禁与之后发布确认；未部署。

权限专项必须实际运行在隔离POSIX root环境，不能跳过后显示通过。Windows入口使用本机已有WSL以空白白名单环境运行同源测试，并只创建其自有/root临时目录；缺少该前提时明确失败，不下载依赖、不降低目录信任约束。Linux非root调用同样明确失败。
