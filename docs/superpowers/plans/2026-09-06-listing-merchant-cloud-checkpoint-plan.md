# Listing 云保存实施计划

依据：[已确定小合同](../specs/2026-09-06-listing-merchant-cloud-checkpoint-design.md)。用户已委托在推荐范围推进，不重复索取同范围批准。writing-plans技能未安装，采用已安装make-plan的发现/分段/验证结构；不为此安装新技能。

## Phase 0 — 发现（已完成）

已读AGENTS/当前执行索引/专业审查playbook，核对Git和原3脏文件。主线程与独立发现覆盖 app.js editable setter/snapshot/backend restore/recent task，repository saved reports/onboarding CAS/chat idempotency，GET/POST handlers、SQL migrations及现有测试模式。

允许接口：现有GET/POST、saasFetch、same-scope原始report、显式DB条件更新/RETURNING。不得假设PUT handler、全局最新报告即当前项目、内容去重即编辑幂等、postcommit GET即精确回执。完整JSON以spec为准。

## Phase 1 — 后端保存垂直切片

负责：后端子任务。新增独立checkpoint验证模块、repository薄挂接/专用两表/005PG迁移，接入现有store权限与HTTP。先写HTTP save→GET失败用例，再实现至绿；再逐一加显式清空、跨租户/店铺/identity、CAS、mutation重试、base交错、审计回滚。

参考：repository get_report_for_company、onboarding条件UPDATE与chat request fingerprint仅借鉴底层模式；不复制其事后GET或事实内容去重。部署清单、数据库manifest/关键列后置校验随新文件更新。只在临时库执行，不碰生产DB。

## Phase 2 — 前端自动保存与恢复

负责：主线程。先由前端测试子任务写一个真实输入→云POST→新客户端恢复的失败用例，再实现app.js内边界明确的checkpoint helper群；不改页面结构/CSS风格或引新框架。

参考：setSaasListingDraftField merchantEdited、saasListingAiGenerationContextKey六段scope、已有facts epoch、防抖local snapshot、restore/recent最终恢复接缝。窄同步metadata持久化、单飞、确定回执、pending代次与冲突保留；修title/category的空值fallback，避免清空后旧标题复活。

## Phase 3 — 回归与独立审查

前端测试负责tools内新专项/相关已有fixture最窄调整；零业务API旧断言仅允许精确checkpoint GET/POST，其余模型/eBay/资金仍为零。测试通过UI和真实新HTTP endpoint，不凭虚假业务回执称线上通过。

逐项核对spec 6组验收。执行原相关Listing生成/事实/最近任务/backend restore/media/prefill/tenant/schema专项，node语法、秘密扫描、diff检查。独立审查源码+测试是否只在授权scope，无旧用户改动进入commit。

## Phase 4 — 收口和后续部署边界

更新唯一当前执行索引并记录精确代码/测试/缺口。只提交显式本批文件；本批未授权正式部署，不用旧225结果冒充新候选，也不重新跑已完成93f7a41发布。可在新候选确定后跑新的完整门禁/CI/dry-run并请求本批部署确认。真实账号AI与来源缺口仍是后续旅程独立条件，不能通过保存功能伪造解决。
