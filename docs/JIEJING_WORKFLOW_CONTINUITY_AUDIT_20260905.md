# 捷境工作流与续接审查（2026-09-05）

本文件是一次有界审查证据，不是新的当前执行索引。当前动作与部署状态以 `JIEJING_CURRENT_EXECUTION_STATE.md` 为入口。

## 范围、结论与限制

- 审查源码 HEAD：`66032b3`；商家生产上次部署为 `4c26ebc`，独立 ops 补丁未部署。三项原有用户修改未动。
- 本次检查 AI CEO、调研/事实/Listing/素材/确认的衔接，商家可达导航与反馈，以及上下文恢复和测试证据的防漂移机制；不重复上轮权限、收费、退款、席位验证。
- 方向仍符合 eBay-first：无货源给调研建议、商家自行找货；有货源导入资料；普通 Listing 在捷境内生成、编辑、审核、通过 eBay API 保存/发布。没有证据要求重建产品或更换技术栈。
- 初次审查发现下列具体缺口，不能再称所有链路无问题。W1–W3 起初有真实函数回放，随后经用户批准进行本地修复；W4 又在真实临时库确认了历史删除行为，W5/W6 仍为可达源码检查。没有生产业务写入，不证明线上已发生这些错误。
- 当前 CUA 只列出空的内置浏览器，没有 Chrome。本次没有登录后工作流截图，不能称完成 Product Design 视觉审查、响应式验收或可访问性验收。未重装、未重复登录/OAuth，也未用旧截图冒充当前页面。
- 初次审查未改业务代码；后续获准的 W1/W2/W3 修复见下方收口记录，尚未提交、未部署。完整 211/211 证据仍只属于前一轮 `4c26ebc`，不属于本批新增修复。

## 工作流发现

| ID | 等级 | 可验证问题 | 证据与最小处理方向 |
| --- | --- | --- | --- |
| W1 | P1 | Listing 生成期间切换店铺/项目，旧请求返回后可以覆盖当前编辑区 | `app.js:32880` 的 `generateSaasListingDraftFromCurrentProject` 在 await 后 `32948` 无条件写全局草稿；`45599` 店铺切换不拦截在途请求。回放 A 请求→切 B→A 回包，当前店铺 B 而草稿 A。后端仍归 A；未证实跨租户泄露或真实误发布。回包必须核对公司/店铺/项目/请求上下文，不能写到新页面。 |
| W2 | P2 | 有旧图片识别和较新 Listing 时，跨设备/无本机草稿恢复会显示空买家文案 | `app.js:15138` 恢复函数中 `15360` 先处理 vision，`15411` 清空字段、`15436` 返回，`15443` 才选择 Listing。回放旧图片事实＋新 Listing，标题/描述为空且 model_generated=false。数据库报告没有被删除。先选同项目最新有效 Listing，再叠加事实；没有 Listing 时才建立空文案草稿。 |
| W3 | P2 | 其他任务变多后，旧项目状态可能误判“没有证据” | `jiejing_saas/merchant_project_status.py:63` 先取店铺最近500任务、公司最近500报告/确认/执行及200素材，再按项目过滤。回放同一旧任务存在，499新任务时调研完成，500时 project_evidence_missing。先按公司/店铺/项目限定查询，再限量/分页；不能拿窗口外等于不存在。 |
| W4 | P1 | 更早 AI CEO 对话不仅无法浏览，账户同步还会删除超过50条的旧记录 | 初次源码检查发现前端固定请求/合并最近30条。后续真实临时库复现：`repository.py` 的 `sync_ai_ceo_chat_history` 对 `retained_rows[50:]` 执行 DELETE；依次同步1、30、20条不同 assistant_id，共51条后，第一条行数从1变0、账户总数50。没有检查或删除生产聊天。下一批先区分模型上下文窗口与商家历史档案，停止隐式清理并实现真实分页；已发生的历史缺失需要另查可恢复来源，不能承诺自动找回。 |
| W5 | P2 | 批量页面“还没有货源”有按钮外观但没有动作 | `app.html:2117` 无 data-bulk-action，`app.js:45225` 只处理带该属性的按钮；空候选生成 `38809` 仅让商家返回 AI CEO。应接到带筛选条件的调研入口，不增加代找/采购货源服务。 |
| W6 | P2 | Settings 仍有商家无法执行的运维式失败提示 | 设置→AI与素材的渲染入口 `app.js:43016` / `28200`，操作反馈 `32363` / `32389` 含 live 模型证明、请查看后端日志。改为说明是否保存、下一步怎样重试/联系支持；内部诊断归 ops。不能只改表面标题，需检查同类失败分支。 |

不计为本次问题：批量能力没有删除，入口仍在选品与上架顶部；当前聊天 DOM 在前、任务上下文在后，最终 CSS 桌面68/32、平板单列（`styles.css:30970`）。这证明已有布局意图，不能替代当前截图验收。隐藏的项目完成度区域与不可达旧“查看报告”按钮未误报为当前商家缺陷。

## 防漂移发现

| ID | 等级 | 缺口 | 处理方向 |
| --- | --- | --- | --- |
| C1 | P2 | 门禁结果与发布候选尚未由程序绑定 | `tools/jiejing_precloud_deployment_gate.py:281` 结果缺源提交/源码指纹/时间；`jiejing_prepare_public_staging_bundle.py:66` manifest 与 `jiejing_production_deploy.py:75` 未校验同版本门禁证明。现有打包/部署严格验证提交和文件 hash，但仍可能错误引用其他版本的测试结果。将门禁源版本、测试清单摘要及结果摘要绑定到候选，缺失/不符拒绝部署；不重做已完成发布。 |
| C2 | P2 | 门禁自动“下一步”输出已过时甚至冲突的建议 | `tools/jiejing_precloud_deployment_gate.py:322` 的 `_next_external_steps` 仍固定建议旧 agentuser SSH、准备托管数据库、Vault/KMS。纯函数回放确认；与已完成事项、GitHub-only staging 和不买付费 KMS 的决定冲突。移除固定路线，指向当前执行索引与环境证据，不让工具输出成为旧指令复活源。 |

已有保护继续使用：AGENTS 强制压缩/重启后读当前索引、核对 Git；已完成/未部署/未通过 UI 验收明确区分；最新用户决定优先于旧技能与参考库。没有必要再装一个第三方记忆后台或复制整段历史到更多文件。

## 本轮只读线上核对

2026-09-05 采用浏览器式 User-Agent，只输出状态、布尔及公开资产版本：

- `/health` 200 / ok；`/health/deep` 200，数据库/队列/worker ready。
- `/readiness/product-saas` 的 production_ready、beta_ready、can_accept_real_customers 为 true；billing.public_charging_allowed、charge_now_allowed 为 true。
- real_platform_writes_enabled=false 是全面写入标志，本次未重新探测受控草稿/发布通道，不能据此说所有受控 eBay 操作关闭。
- `ops.jiejing.shop` 200，仍引用 `20260828-ops-performance-v2`；`app.jiejing.shop/ops.html` 404。
- 没有退款端到端或本商品真实 eBay 发布的新证明；独立 ops 同版发布的既有权限阻断仍在。

## 获准修复收口：W1/W2/W3（本地，未部署）

2026-09-05，基于 `66032b3` 的工作区补丁；未提交、未部署，三项原有用户修改未动。该批未进行真实调研、模型/FAL调用、支付/退款、eBay OAuth或平台写入，没有造商家验收记录。

- **W1**：生成请求绑定公司、用户、店铺、项目、来源候选及请求代次；切走再切回不能复活旧响应。成功、失败和收尾都不能改写其他请求的草稿、缓存、错误或忙碌态。同商品只切换模块仍保留结果。生成期间的新标题/资料不被覆盖；重复调用在当前页面生命周期内只发一个在途请求，未宣称新增跨页面/后端幂等。成功提示改为“保存到当前商品”。
- **W2**：同项目最新有效 Listing 优先于旧图片识别草稿，按时间合并事实快照；验证依赖完整后端生成合同，不能凭 report_type。明确清空不复活，来源/冲突保留；更新事实会要求重新校验。现有商家文案不被刷新覆盖，更不能用另一设备较新 Listing 的事实给本机旧文案重新授信。没有有效 Listing 时仍保留待确认图片建议和空买家文案。
- **W3**：六类证据先限定公司/店铺/项目/cutoff再取窗口；项目身份顺序与既有 reducer 一致，次级旧身份和未经兼容许可的 legacy 不得挤占窗口。父任务/确认单按受限主键补回，同一商品累积500个版本也能精确补回源调研及其任务；显式其他项目/来源/候选不能借精确引用混入。完整身份、账号受限和真实执行证据仍由原状态计算校验，未打开写入开关。

保留的红灯包括：换店覆盖、离开返回覆盖、商家编辑被覆盖、重复生成；旧vision令标题为空、清空后旧condition复活、旧资料抹掉新材质、混合公司输入抢占、跨设备错配验证；全局500任务/报告挤走当前证据、同项目500版本丢源调研、次级身份挤占、精确源引用混入其他项目。以上均为本地测试，不推断生产已发生。

| 检查 | 证据与限度 |
| --- | --- |
| Listing生成 browser | 16类场景，1440桌面及1024平板；本地真实app与隔离后端，模型响应受控。包含可见“最近任务→继续草稿”；旧隐藏店铺选择器使用原生change事件，不冒充可见点击验收。页面无未捕获错误、无横向溢出，完成态截图已目视检查。 |
| Listing恢复 browser | 7组，真实app恢复/渲染函数；旧vision/新Listing、身份与合同变体、清空、来源冲突、商家编辑、跨设备旧文案及二次刷新。 |
| 相邻前端 | 商品事实UI18/18、发布预填11/11、路由/供应商HTTP30/30、frontend resilience；项目进度browser含桌面/平板/手机及模块切换。 |
| 项目证据 | `test_jiejing_listing_single_progress.py` 新增9组真实临时SQLite/原生类型契约回放及既有状态断言；500任务/报告/确认/执行、200素材、当前仍保留聊天、身份/cutoff微秒与时区、精确来源。 |
| 安全/兼容 | Listing grounding与concrete product门槛、backend MVP、SQLite→PostgreSQL导出演练、PG schema/cutover专项、secret scan、语法与diff；不等于真实PostgreSQL查询执行/性能/并发验收。 |

新增恢复专项已接入预云门禁（清单现212项），**本批未跑完整212项**，不得沿用旧211/211给新补丁背书。`app.html`/`index.html`只刷新资产引用，family=`20260905-workflow-recovery-v1`，app=`2c04c1daa279`、styles=`9e2a50d2359c`；没有改首页布局或业务导航。生产仍是前一轮发布，未使用这些本地修复。

上段为W1/W2/W3冻结时证据，W4随后修复见下节；W5无货源入口、W6商家反馈文案尚未修复。C1/C2仍须在下一次发布准备前落成，独立ops发布阻断未解除。下一步不重新选品，不重跑已完成授权或资金证明。

## 获准继续：W4历史保留与真实分页（本地，未部署）

仍基于`66032b3`工作区补丁，保留前批修复及三项用户原有修改。未提交、未部署，没有生产账号操作。改动沿用现有历史表、API和聊天顶部按钮；没有新增导航、改首页布局或增加模型上下文。

- 后端同步移除50条清理分支；旧turn更新不改变创建时间，按创建时间与主键稳定分页。游标须在当前公司/用户范围内定位锚点，非法/其他账号统一400。兼容旧`list_ai_ceo_chat_history()`与SYNC响应字段，默认30、最多50条。
- 聊天版本检查改为总数聚合及最多50条最近更新的正文，不再一次读全部档案JSON。历史条目更新仍改变revision。总数聚合与排序不等于恒定延迟；未实测真实PostgreSQL查询性能。
- 页面将近期30条同步缓存与内存显示归档分开，模型仍只取最近8轮。历史按需分页、去重，不调用模型、FAL或平台。加载失败保留已显示内容和游标，可重试；单飞和滚动位置保护不另加UI面板。
- 账号/请求代次同时保护历史读取、同步、分页和首次工作台历史载入；A→B或A→B→A的旧成功/失败不可写入新页面与缓存。共享fetch的可选有效性检查在响应、续期重试和错误处理前阻断过期请求；旧401不得续期、登出新账号或把旧POST重放给新身份。
- 跨设备大量新消息形成无重叠最新窗口时重新锚定抓取游标，但保留已显示归档；经过重复页仍能继续。旧分页请求在途遇新游标，只合并有效条目、不覆盖较新游标；等待期间商家移动阅读位置也保留。

红→绿证据：51条首条被删除→保留；原无游标方法→71条完整分页；旧turn更新移动创建时间→固定；revision一次读91正文→最多50；75轮页面只显示30→完整；初始0/10轮增长到76后无更早入口→可完整查询；已加载76再新增70只显示106→146齐全；旧分页回包覆盖重锚游标→保留新游标。独立复核亦复现HEAD旧A回包写B缓存、当前同场景拒绝。所有数据都是本地隔离测试。

| 检查 | 本批结果与限度 |
| --- | --- |
| 后端档案/HTTP | `test_jiejing_ai_ceo_cross_device_history.py`新增7组通过；含SQLite实际分页与PG原生datetime/JSONB适配器回放，以及旧完整HTTP流程扩至76条。非法/跨账号游标400，空同步不删除，更新旧记录revision变化。最后独立复核的UTC转换越界日期先复现两项OverflowError，再包入现有服务器时间回退，主线程7组复跑通过。 |
| 浏览器控件 | `codex_jiejing_ai_ceo_history_pagination_browser_smoke.js`桌面1440×1000、平板1024×1000各20场景；75→76→146轮、初始短历史增长、分页失败/重试/单飞、空过滤页、账号切换/ABA/旧401、游标并发。所有页面阻断非本地请求。 |
| 界面证据 | 实际聊天函数与styles.css的隔离测试页面，首条可见，截图已目视，无溢出/覆盖；不是完整工作流UI或生产账号验收。临时截图：`C:\Users\57249\AppData\Local\Temp\jiejing-ai-ceo-history-1788618492381.png`及`jiejing-ai-ceo-history-1788618550268.png`，不进入部署包。 |
| 相邻兼容 | 旧frontend resilience、历史刷新/分页/滚动、租户缓存、rotating-browser会话控件与浏览器回归、backend MVP、PG schema15/15、PG cutover、W3聊天/原生类型相邻2项、eBay账号删除合规回归通过。未运行真实PG或平台/资金操作。 |
| 防漏接线 | 历史browser runner及W2恢复runner均接入门禁、bundle白名单、Node检查；漏任一项的合同先红后绿。staging patch、GitHub deploy/runner、local-first四合同通过；没有改变部署权限/执行通道。 |

门禁清单213项且名称无重复，**本批未跑完整213项**，更未用旧211/211作为新补丁证明。工具没有`--list`分支，未直接运行这个参数，使用只读import统计。7处前端引用更新为family=`20260905-chat-history-archive-v1`、app=`d8b1c8c284bf`、styles=`9e2a50d2359c`；资产合同通过，首页内容/样式不改。未打包、未执行生产dry-run/apply。

最终安全检查：`jiejing_secret_scan.py`通过；app及新增/关联JS的Node语法、变更Python编译、Git Bash对apply脚本的`bash -n`、`git diff --check`通过。没有暂存或提交，三项原有用户文件的差异仍为29/0、1/0、10/1行，未被本批编辑。

### W4b：后续必须处理的归档失败边界

独立实函数回放：连续31条完成对话、历史SYNC不可用，页面显示31，`loadSaasAiCeoThread()`及`saasAiCeoThreadForBackendSync()`均为30，最早条目只在内存archive。关页再开可能缺这一条聊天档案。本批没有新增持久outbox，也不将“已停止服务器清理”夸大为任何网络故障下零丢失。

后端`api_server.py`的`send_chat_payload()`在终响应前调用`finalize_ai_ceo_chat_request()`，任务保存脱敏响应，普通模型路径另有`task.output.ai_ceo_chat`；所以不能说后台答案全部消失。但账户聊天表目前仍依赖浏览器SYNC，任务留痕不等于聊天页面可读。下一批优先设计并测试最小可靠归档/补同步路径，再做W5/W6；不因此添加RAG、记忆插件或扩大模型输入。旧生产历史是否被删、能否恢复需要另查，未作恢复承诺。

## UI 改进依据与边界

参考是设计原则，不导入其他产品的品牌、套餐或业务规则：

- [Shopify 布局指南](https://shopify.dev/docs/apps/design/layout)：按任务选择布局，保持同页信息密度一致，编辑/预览可双列，单个卡片至多一个主操作。
- [Atlassian 消息设计](https://atlassian.design/foundations/content/designing-messages)：错误告诉用户下一步；局部问题就地说明，系统级横幅只承载关键系统提醒。

应用到捷境的建议：保留已批准首页和色彩；先收口 AI CEO/Listing 这一个商品工作区。聊天为主，商品进度紧凑且可收起；清晰显示当前商品与下一步；批量入口可发现；业务记录留在业务页面，不恢复运行记录主导航。先取得当前桌面/平板、已有项目/空状态截图，再定一个小范围视觉方案，确认后实施，不凭记忆再改全站。

## 有终点的处理顺序

1. **W1/W2/W3及后续W4本地修复已收口**：在途切换不串页，重新打开不丢已生成文案，旧项目不随其他任务增多倒退，聊天不按50条清理且可真实分页。失败回放保留为回归，不扩张为 UI 重做。
2. 先补W4b同步失败关页的可靠归档边界，再收口W5/W6；C1/C2在下一次发布准备前落成。独立ops发布走既有获准路径；本次没有获得SSH例外授权。
3. 通过获准部署后接续同一平板支架项目，不重新选品、不造数据、不重复 OAuth/支付/退款；通过捷境页面核对聊天、报告、资料、Listing、素材和审核记录。满足真实资料与账号条件再保存/发布，遇真实资格阻断停在明确一步。
4. 本批结束条件是具体回归场景通过及对应页面验收，不是追加新模块、无止境审美重构或任意“99%”。新发现超出当前批次的问题先记录、排序，不静默扩张范围。

## 上下文压缩说明

压缩用于减少上下文体积并保留后续所需状态，不应把它当逐字永久记忆或零偏航保证。项目方向、禁止事项、版本、已完成动作和下一步必须在当前索引中可核对；长日志只按关键词/日期查，独立审查返回有限证据，避免反复把全部历史塞回上下文。

官方依据：[Compaction](https://developers.openai.com/api/docs/guides/compaction)、[AGENTS.md](https://learn.chatgpt.com/docs/agent-configuration/agents-md)。本次没有修改 Codex 模型、压缩设置、权限或永久记忆，也没有把 API compaction 参数当成桌面设置照搬。

## 自主推进批次：W4b / W5 / W6 / C1 / C2（2026-09-05，进行中）

最新用户授权主理人自主做常规方案选择并持续实施；不再逐项问通用批准问题。有限交付目标是可靠性与入口修复、当前页面有界设计改进、干净候选验证，而不是新模块或全站改版。正式部署与真实资金/平台动作仍保留既有边界。

- W4b已冻结：新协议请求的终态和聊天档案同事务提交，失败共同回滚；claim/replay校验company/store/user；服务端终态行不接受客户端SYNC覆盖（含先读旧行、final提交、晚SYNC竞争窗口）。浏览器先确定canonical ID，archive_pending不SYNC，丢final仅按精确ID恢复，缺WebCrypto不发送；旧客户端和旧冻结请求保持旧协议，纯本地时钟快捷回答仍旧同步。后端15组+HTTP、桌面/平板各26场景及幂等/resilience/分页通过。独立7组、12并发同键仅1claim、10并发伪造SYNC不覆盖通过，真实provider调用0；不等于真实PG进程锁/生产UI证明。
- W5：批量“还没有货源”能带入10/20/50与筛选偏好，进入AI CEO编辑后由商家发送；不自动调用AI、不清现有项目。输入事件和原DOM绑定作用域保存内存草稿，账号切换/登出清除、店铺分别保留、明确空串与已提交内容不复活。关浏览器不承诺保留未发送文字。
- W6已冻结：设置中的“回填商家记忆”改为“更新经营记录”，报告与记录刷新反馈用商家语言。先复现200空/未知结果误报成功、切换账号后旧失败覆盖新反馈/忙碌、迟到401让新会话跳登录，再修结果校验与company/user/store/API+epoch+request owner+refreshGeneration守卫。报告须completed且明确空blockers，计数须非负安全整数；明确0可用，空值不冒充0。两动作重复点击不重发，A→B→A旧包无效，finally不释放新忙碌。W5/W6实际本地浏览器17组通过；相邻商家文案/Settings/批量合同通过，未发生真实模型或业务操作。
- C1/C2：完整门禁绑定HEAD/tree、开始/结束的干净状态与检查有序清单、结果；脏目录或途中变化保留诊断但exit1/handoff=false。新包及生产部署前校验拒绝缺失/错源/少测证明，旧回滚路径不变。独立复核又复现Git assume-unchanged/skip-worktree隐藏未提交内容伪装clean，现开始/结束及打包/部署守卫均拒绝，正常CRLF保留。16组证据专项、微型包和生产部署含回滚合同通过；尚未完整跑215项。证明不等于数字签名或线上能力证明。

### 当前页面截图驱动的有界UI修复

实际使用Product Design审查、捷境设计系统及前端调试验证。仅从本地Awesome DESIGN.md参考库的Slack条目借鉴“明确排印层级、按断点收缩”的原则；不采纳它的品牌色、专属字体、套餐、脚本或无依据无障碍声明。

1. Chrome仍不可接管（`Browser is not available: chrome`），未重复登录/重装。使用可用Codex内置浏览器只读查看公开官网；已登录生产工作流未验收。
2. 本次公开桌面1440×1000、平板1024×900截图确认hero中文92px/行高0.96、过度负字距造成挤压与语义断行。最小改为桌面上限76px、1.12行高、按完整短语分三行；手机36–48px。圆形AI CEO图、六板块、套餐、CTA和业务逻辑保留。
3. 本地候选390×844真实点击“进入AI CEO工作台”后，登录页仍使用280px侧栏，账号输入宽度约32px，标题/关闭按钮被挤出视口。根因是`body.is-auth-mode .entry-auth-shell`优先级覆盖普通移动单栏规则，另有绝对定位居中导致长表单顶部丢失。已有测试仅查表单出现，漏查可操作布局。
4. 追加320×568、390×460、390×844、680×700、681×700、720×900、768×900、1024×900的登录输入宽度/可达标题与关闭按钮、实际填写/关闭、无POST回归。修复手机为单栏、隐藏重复侧栏说明、固定视口内顶部对齐并可滚动；681/720原输入135/147px进一步改为账号与密码上下排列（<=1120），变283/307px。8组全部通过，首页桌面/平板/手机/减少动态、触屏/键盘/无JS/失效会话也通过；没有修改认证、账号、套餐或授权逻辑。
5. 首页浏览器此前未接完整门禁，现接`browser_homepage_maturity`并补部署白名单/Node语法，静态合同以AST校验精确CHECKS；删门禁/错runner/删白名单/删Node四变异均拒绝。当前清单216唯一，本批还没有完整门禁证据。
6. 用当前app.html/app.js/styles及隔离页面数据捕获AI CEO空/项目状态1440/1024共4图；桌面聊天746px、任务351px，主次合理。平板空状态composer底790.83而chat底769.53裁切，已有项目230×80.5收起摘要遮首条消息。修复仅取消平板空stream最小占位、收起摘要参与布局并保留聊天剩余高度；桌面收起态同因遮挡一起修，展开比例保留。4个实际app布局case、项目两次按钮切换、输入下沿hit-test及原26历史场景通过。主线程已看失败图和同状态结果；不是生产账户操作或从头跑商品。

本次截图位于忽略的`output/jiejing-ui-audit-20260905/`，不进入Git/部署包。当前证据：`04-public-hero-desktop.png`与`06-local-hero-desktop-phrases.png`同视口前后对照；`01-public-hero-tablet.png`/`07-local-hero-tablet-after.png`；`08-local-hero-mobile-after.png`；失败`09-local-login-mobile.png`与成功`10-local-login-mobile-after.png`同视口对照，`11-local-login-small-tablet-after.png`。工作台`ai-ceo-{empty,project}-{1440,1024}.png`已刷新为最终结果，修复前另存`*-1024-before.png`。截图是本次实页/本地候选，不是登录后商家旅程证明。浏览器回归隔离数据与本地只读素材，不发生真实模型、FAL、支付、退款或eBay操作。

2026-09-06凌晨本批冻结：LF归一化内容hash app=`d2dcc7345056`、styles=`885b316fada8`，family=`20260905-workflow-reliability-v1`。资产/生产部署合同、W5/W6组合17、租户缓存、当前状态、语法/秘密扫描通过。首页8断点及AI CEO4布局回归均纳入同一216项门禁清单。三项原有用户修改不入候选；没有正式部署或高风险业务动作。

### 首轮完整门禁及回归适配（2026-09-06）

首轮提交`f2ce76032c6460bd959cc4fc469740c304be7258`，在独立干净目录`C:\Users\57249\Documents\Codex\2026-09-06\jiejing-release-workflow`执行完整216项，结果214通过/2失败，耗时1463.71秒。`source_stable=true`、`release_eligible=false`；run_id=`311d697180db43999defadb602a5e8d5`。证据保留于该目录`output/jiejing-precloud-deployment-gate/latest.json`；该版本不得打包或部署，不能复用214项结果替代下一候选完整验证。

- `merchant_surface_guard`旧匹配把h1子span间的可见空格当作内容变化。改为校验唯一h1的批准文案，接受语义分行，但其他标题、正文冒充标题或“自动发布”替代“自动推进”仍拒绝。该专项与homepage_maturity通过，未改实际首页。
- `ai_ceo_phase0_contracts`完整21项原19通过/2失败；两项在行为断言前缺`saasAiCeoHistoryRequestContext`，不是已复现的产品503失败。fixture从真实app抽取scope/epoch/canonical rekey/去重依赖，保留原Listing不回填、503三句反馈断言，并新增必须进入`blocked_before_model_chat`和缺归档元数据仍`archive_pending=true`。Windows命令长度改用Node标准输入，不删真实依赖。完整21项、stream_error8项、streaming合同与历史browser26+4布局通过；未改生产JS。
- 实际完整检查24分24秒已接近GitHub preflight原25分钟，另有依赖安装等准备步骤。这是预算不足风险，不是观察到GitHub超时。仅将此完整检查job上限有界调整为45分钟并增加合同，其他专项workflow、runner、权限、分支与发布命令不变；不触发CI。

以上后续修订须另提交新候选重跑完整216项，成功后才允许打包和生产dry-run。正式apply以及独立ops发布权限边界不变。

### 第二候选完整验证与发布准备（2026-09-06，未正式部署）

修订提交`0250ce60af4d1a957bdd79f295c67bae14423262`在独立干净目录`C:\Users\57249\Documents\Codex\2026-09-06\jiejing-release-workflow-r2`完成216/216，失败0，1445.32秒；source稳定、release_eligible=true、secret_exposed=false。run_id=`0bbaca06fb64436fadb4c0e3996cb9cc`，tree=`5e5900cb14eef85fc9743f24ac813e16120dd06a`。证据是此目录`output/jiejing-precloud-deployment-gate/latest.json`，不是首轮214/216报告。

发布包457文件，`output/jiejing-public-staging-bundle/jiejing-public-staging-20260905-170914.zip`及同名manifest；包SHA=`4d9549f2acac2efc3aef221b2476cc6f7daa328411a6a414c22eb5eb36210f87`，manifest SHA=`60f44d5fbc05a3f33c98246cf3ec9eda4ff0f4e4446c2eb325ba019f8a9c6a26`。主生产通道dry_run通过，候选未永久落入release root、active未切换、私有配置未规范化或修改。脱敏实际输出副本位于候选`output/jiejing-production-deploy/dry-run-20260905-170914.json`。

本批完成的是有版本依据的本地修复候选、桌面/平板/手机针对性验收和生产dry_run，不是已上线、GitHub CI通过、生产商家全流程、退款运营完整可用或真实eBay发布证明。GitHub CLI本轮未认证，旧ops尚待同版发布；正式部署仍需当前候选确认及发布前验证。用户无需重新提供已知商品/重做OAuth或支付；后续仍从同一平板支架项目续接，缺真实事实/图片权利/账号资格时如实停在具体条件。

### 部署获准后的真实CI发现与修复（2026-09-06）

用户已批准继续本批主站部署。只读复核候选/包/216项/dry_run未漂移；生产仍`4c26ebc`。虽gh CLI未认证，应用GitHub连接与Git非交互凭据可用，无需用户重新登录。对`d809cfb..0250ce6`的177提交、1019个唯一新增文本blob（含大文件及删除版本）扫描无秘密规则/禁止路径命中后，已将0250ce6推至私有仓库codex分支，未改main或staging。

普通CI run `33982650298`（精确SHA0250ce6）失败于旧`test_jiejing_new_ebay_account_low_risk_runbook.py`要求已删除的内部新账号演练面板。历史d2158a6按商家/运营隔离主动删除它，而现行商家隔离测试禁止恢复；本地复现相同失败，不是Linux差异。测试现改为禁止5个旧内部标记回流到3个商家模块、保留3个当前店铺证据hook；15注入/3缺失负例及跨模块移动正例通过。独立AST比较确认checker调用及其后32条语句未改，OAuth、禁止静默同步/重新授权、写入与动作确认规则保留；专项/商家隔离/OAuth UI通过。

发现另8个普通CI专项未入本地216清单（其中上述失败1项，其余7项隔离复跑通过）。全部补入CHECKS后为224项且名称唯一，26个普通CI Python脚本全部覆盖；既有部署合同直接解析CI实际run脚本并比较CHECKS，覆盖inline/block/folded/quoted形式，排除名称/注释/env伪匹配，有逐项漏接及非Python反例。部署四专项、版本绑定证据16/16、语法/diff通过。部署白名单及编译本来已有这8项，未改脚本。

只改3个测试/门禁文件与本批证据文档；app.js/CSS/后端/生产配置未变，不扩大已批准产品内容。下一步冻结新提交并在第三个干净目录完整224项、精确SHA GitHub CI；旧216通过不能替代，旧0250ce6包不得apply。独立ops未获SSH例外，生产用户UI及真实平台/资金操作未进行。

### 第三候选正式发布与验收收口（2026-09-06）

`1550105b53825a65f876808bff059a4e6d0c0a8a`在r3干净目录完整224/224通过、失败0、1468.03秒；run_id=`33a289f802b64f8bb668e7cc0738fd3f`，源稳定且release_eligible=true。普通[GitHub CI 33983427176](https://github.com/f4zjwy6j94-star/JIEJING-SAAS/actions/runs/33983427176)对应同一SHA，15步骤success。457文件包及manifest独立逐条hash/源blob/证明核对通过，相对0250包仅3个验证工具成员变化；没有混入3项原有用户修改。

包为r3的`output/jiejing-public-staging-bundle/jiejing-public-staging-20260905-183707.zip`及同名manifest；包SHA=`ebe782eed7dd2df8819a5f51b99a9ed2c5ed0e85a0993b8c88fa0159402d3e99`，manifest SHA=`d37a70eec570a2fa628548cf70024a36b6110dafb6f099613c69168b3df6b795`。dry_run与获准apply均成功，正式release=`20260905T184522Z-1550105b5382`，上版=`20260905T113551Z-4c26ebc487dd`。实际脱敏回执及读回在r3的`output/jiejing-production-deploy/`，对应`dry-run/apply/readback-20260905-183707.json`。不再重复部署。

验收结果：

| 范围 | 当前证据 |
| --- | --- |
| 源与运行版本 | active/manifest两个SHA/四服务Compose标签一致；API image `5f8f0623…b5e80`健康，Worker image `df91875a…0b500`运行；两个旧镜像hold逐个匹配上版。 |
| 证据与私有边界 | 首次oneshot与timer安装验收成功；service success/0、timer enabled/active、有下次时间，无drop-in。安装三文件等于包字节。private原路径/root权限/无symlink保持，未读秘密。 |
| 线上可用性 | health/deep=200及ok/ready；production/beta/customer/public charging/paid launch=true，blocker/warning=0。eBay全面写入=false，受控保存/既有草稿发布=true；不是具体商品真实发布证明。 |
| 公开资源 | app.js/styles.css实际LF hash匹配；HTML仅Cloudflare注入统计脚本不同，去掉唯一该行后与候选一致。app.html未带start=app时按既有规则转首页，并非部署错误。 |
| 页面身份/内容/错误 | Codex内置浏览器在正式域实页；非空、无框架错误遮罩；控制台未见相关error/warn。Chrome仍不可用，不重装、不冒充已登录账户。 |
| 可见交互与截图 | 桌面1440×1000/平板1024×900标题与圆形图；链接#workflow与05素材演示切换；手机390×844入口→登录表单→测试邮箱填写/清空→关闭。输入328.8px，标题/关闭在视口，截图已实际查看；未提交登录或注册。 |

这次修订发现并解决的是过时面板测试与CI/本地清单漏接，保留负向回归防复发；此前W1–W6/C1/C2/UI随本次首次上线。另两个只读验收脚本初始假设已纠正：无Health属性的Worker不能按API模板读取；HTML须区分入口重定向和Cloudflare统计注入。这是检查方式调整，不是修改生产行为。

仍未完成：独立旧ops前后端/退款运营路径同版更新；已登录账号的同一平板支架项目续接、FAL/图片权利及发布前核对。没有新真实收费/退款/eBay写入，没有以任意完成百分比或本地全绿冒充全站成熟和业务闭环。旧ops规范外SSH仍需明确窄范围例外授权；正常手动GitHub通道的main/runner及广泛更新范围不能静默替代该授权。

### 旧运营后台窄范围同步收口（2026-09-06，后续已获准）

用户明确“允许”，批准仅旧ops前端/代理/API的SSH例外，不包含主站、Worker、Vault、Cloudflared、DNS、私有配置、共享数据库变更或真实资金。上述“旧ops未授权/未同步”为本批之前的历史状态，现已完成代码同步。复用同一1550105的457文件包/224项/精确SHA CI证据，不重打包或部署主站，不混入三项原有用户修改。

只读前检以既有API后端连接、显式READ ONLY事务验证16条受信迁移/checksum、45表、52关键列、4索引、5约束全部匹配；没有依赖默认启动替我们补schema。API有效环境211项、前端6项与原Compose和候选镜像合并结果完全相同，未输出环境原值。两SVG已相同，无需覆盖；现场proxy与历史版仅行尾差异，候选只增两个精确location（退款GET列表及POST review/execute/query），不扩大域名、端口或owner通配范围。

旧五文件脚本缺API/镜像回滚并硬编码旧资产，广泛staging脚本又会更新Worker/Vault，因此使用仅本批的receipt辅助流程。它固定五文件、两服务、源SHA、实际镜像、原Compose、schema时效和非目标容器，先验证备份再覆盖。独立审查曾用Binds数组逆序复现“误判配置漂移且回滚被同一检查堵住”，在真实切换前修正无语义顺序规范化和恢复前scope/恢复后完整配置检查；14/14故障回放及独立原例复跑通过。schema前检脚本17个隔离回放通过。此类本地模拟不等于实际掉电恢复或真实资金测试。

正式dry-run通过；此前一次schema证明过期被安全拒绝，刷新实际只读查询后继续，没有放宽守卫。apply会话76472已exit0/status=success，未触发实际回滚。旧host新API image为`sha256:f9e867784ae0500006d3523a0b4a07d7fd63ad93b90fc12ee4fc22ad0e4912dd`；前端沿用原`sha256:65645c7bb6a0661892a8b03b89d0743208a18dd2f3f17a54ef4b76fb8e2f2a10`。发布后API150源码/依赖文件与包逐字节相同，5目标文件匹配，配置、挂载、端口、网络及三个非目标容器不变。实际Compose增加该release的`.ops-switch/apply.json`镜像覆盖文件；原Compose未改，未来不能遗漏override而退回旧API。

独立公网GET（2026-09-06T03:11:14Z）：ops200，HTML/CSS/JS/panels/两SVG共6/6精确匹配冻结ZIP；列表401、3动作GET405、其他owner路径404；app域ops.html/panels/退款路径404。无扩展名/ops=200只是主站首页fallback，没有ops内容。主站health/deep=200与ok/ready，数据库/队列/worker.ready=true；`readiness.provider_status.billing`的public_charging_allowed、charge_now_allowed、billing_ready_for_paid_launch三项仍true，没有关闭公开收费。

完整脱敏证据与辅助脚本保留于`output/ops-narrow-20260906/`；精确容器ID、脚本SHA、主机release、原镜像hold和五文件恢复路径见当前执行索引的本次收口。没有修改或恢复数据库、导出/回显秘密、真实POST支付/退款或订单query、OAuth、FAL、eBay或生产商家工作流操作。内部登录GET200与实际运营退款流程尚未验收；旧ops运行时live_api/refund仍false，代码同版不能被汇报成退款执行已可用。下一项需要针对现有后端微信执行配置对齐的明确许可，不重复本次代码同步。
