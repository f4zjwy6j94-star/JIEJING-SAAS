# Listing 手改云端保存与跨设备恢复

日期：2026-09-06。状态：用户已将本次已推荐最小范围的方案选择与推进交给主理人；本文件记录落实合同，不重新发起同范围泛泛审批。未部署，不含收费、额度变更或 eBay 写入。

## 目的与非目标

商家在现有 Listing 编辑器手改文案后，不应只存在本机 localStorage。改完自动云端保存，刷新/另设备/最近任务恢复同一项目的编辑；空字符串是明确清空，慢回包、断网、两设备竞争均不得静默丢掉编辑。

本批不改导航、产品结构、视觉风格、套餐、角色、模型或平台写入权限，不增加实时协同编辑器、版本历史导航或货源服务，不把演练参数变成真实事实。已有 8 个可见编辑控件不增加；后台既有 10 字段中的 keywords/risk_notes 也完整保留。

方案选择：采用自动保存及版本冲突保护。手动保存按钮容易漏点；实时多人协同增加不必要基础设施与复杂度，不适合当前 MVP。

## 已查证接缝

- app.js `setSaasListingDraftField` 的真实输入带 merchantEdited；当前250ms快照只写 localStorage。普通 capture 不能因此新建云版本。
- `restoreSaasListingComposerDraftFromBackendReports`、`openSaasRecentProductTask` 先恢复报告/本机缓存，再协调云版本；原AI报告不变。
- 后端只支持现有 GET/POST handlers；沿用店铺归属和 create_task 编辑权限、查看权限，不新增角色或要求付费才能保存已有文字。
- 来源通过 company/store/完整 listing_project_identity 精确匹配；同名商品、猜测旧key、全局最近报告窗口都不是身份依据。
- PostgreSQL原4份迁移不可改写，新增005并接入启动manifest/后置校验。

## HTTP 小合同

GET/POST `/stores/{store_id}/listing-drafts/{project_key}/checkpoint`。

GET query：source_report_id、candidate_id；身份的值允许与现有结构一致的空锚字段，但key必须存在，三字段必须明确、规范且与原始报告逐项匹配，不能把缺字段当通配符。company/user仅取已认证身份。

POST JSON：

```json
{
  "contract_version": "listing_merchant_edit_v1",
  "listing_project_identity": {"key": "listing-project-example", "source_report_id": "report_source", "candidate_id": "candidate_1"},
  "base_report_id": "report_base",
  "expected_revision": 0,
  "mutation_id": "client-generated-uuid",
  "fields": {"title":"", "selling_points":"", "description":"", "category":"", "item_specifics":"", "keywords":"", "price":"", "images":"", "logistics":"", "risk_notes":""},
  "merchant_edited_fields": ["title"]
}
```

字段只接受上述完整十项字符串，缺key/null/额外字段拒绝；空值保留，不用旧值填回。selling_points/description最多1400，其余800字符，与既有编辑器一致。不接受客户端审核、model_generated、ready、商品事实、原始snapshot或秘密样式内容；安全错误不回显原值。expected_revision为非负整数（不接受bool），mutation_id为8–160安全字符。

GET 返回 `status:saved|empty`、checkpoint或null、current_revision、current_base_report_id、current_base_report（同已有安全报告envelope）及base_changed。

checkpoint包含 checkpoint_id、revision、mutation_id、company_id、store_id、listing_project_identity、base_report_id、fields、merchant_edited_fields、saved_at、source:merchant_edit。新POST返回201，精确重试200，回执checkpoint为该次持久化版本而不是随后被别人更新的head；同时标识idempotent_replay/model_called:false/usage_consumed:false/real_platform_writes_enabled:false/secret_exposed:false。

409错误码区分 listing_draft_revision_conflict、listing_draft_mutation_conflict、listing_draft_base_conflict；返回仅当前授权scope的current_revision/latest_checkpoint/current_base_report_id/current_base_report。所有冲突保留本机副本，不自动覆盖任一方。

## 存储、来源与并发

新增专用项目版本头和不可变编辑版本表；不是每次按键创建任务或AI报告。避免挤占现有报告窗口或把素材队列变成重复任务。head按company/store/project_key唯一，持久化完整identity，mutation去重按同项目scope+ID，含payload指纹与精确receipt；保存版本、CAS head和审计同一事务。

顺序固定：认证与完整scope→精确mutation重放/同ID异payload拒绝→最新base检查→revision CAS→版本与审计提交。A→B→A是三次编辑，不按内容回到第一次A的旧时间。并发首次保存用显式ON CONFLICT/条件更新，不依赖进程内锁。

base只取同项目saved的 listing.package/product.listing/merchant.product_facts，按created_at+report_id取最新；无这三类时才取完整身份匹配的 ai_ceo.market_research。checkpoint本身不能成为base。

生成/事实另有事务，现有SELECT不能保证与新报告写入全部串行；本批不宣称这点。GET每次重算current_base_report_id/base_changed，前端只有checkpoint.base等于当前base且无未同步冲突才应用；新生成报告不会被旧云稿无声遮盖。旧编辑仍在不可变版本中。

## 前端协调与体验

编辑即先保留本机、约1秒静止后自动保存，状态只在编辑器显示“正在保存/已云端保存/仅保留本机/有更新待核对”。回执到达才称已云端保存，捕获表单、打开任务或单纯刷新不创建云版本。失败可重试，超时重试复用mutation，后续新编辑用新mutation。

本地同步元数据按company/user/store/完整identity隔离，窄白名单持久化；不加入任何凭证或可信度标记。每scope单飞，编辑代次区分提交后的新修改，项目/账号/刷新代次拒绝迟到旧回包。切页不要求取消已经到达后端的保存。

首次云GET与在途输入竞争时保留新输入。跨设备GET应用云稿必须匹配完整身份和base；本地未同步与云端新版冲突时显示两者并让商家明确选择，不做静默last-write-wins。选择云稿前保留本机副本，选择本机后以最新revision提交，遇到再次竞争仍409。

云保存只是保留编辑，不授予任何事实/素材/发布许可。手改或云恢复的文案必须沿用现有事实审核与确认入口边界，不伪装为新AI生成成功；模型调用不应成为保存文字的前提。

## 验收与停止点

1. 同一项目十字段及显式清空经真实HTTP保存，在干净第二浏览器恢复；可见8控件实际输入，其余2键走DTO保留测试。
2. 刷新、最近任务、切项目/账号、A→B→A不串数据；迟到保存/GET不覆盖新编辑或清除新pending。
3. 断网/401/5xx/超时保留副本；同mutation精确重试返回原版本，同ID不同payload拒绝。
4. 两客户端CAS、一致事务失败回滚、生成/事实新base交错；未有真实PostgreSQL并发证据时明确写未验，不用SQLite或假驱动替代。
5. tenant/store/project/source/candidate/角色隔离、额外字段/秘密样式拒绝、零模型/计费/eBay请求；报告任务数量不因autosave增加。
6. 原事实保存/生成/项目恢复/素材/发布边界回归不削弱，最小界面状态桌面与平板可读。

本批先提交可验证代码与专项证据，再准备新的完整门禁和部署候选；225/225旧门禁只属于93f7a41，不复用为本批证明。正式部署需要本批确认及dry-run，不碰旧ops或原有三项用户修改。
