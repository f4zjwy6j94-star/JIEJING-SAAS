"""Jiejing-owned commerce Agent execution layer.

This is the first concrete execution step beyond role contracts. It keeps the
logic vertical to Jiejing's eBay automation workflow: every role produces a
merchant-readable, sectioned report that follows Runtime's task contract.

The executor intentionally does not call live eBay, sourcing, logistics,
payment, or media systems. Those capabilities stay behind future adapters and
the confirmation/execution boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .knowledge import KnowledgeItem
from .models import JiejingTask


EXECUTOR_NAME = "jiejing-owned-agent-executor"
EXECUTOR_VERSION = "2026-05-14.1"


@dataclass(slots=True)
class AgentContext:
    product: str
    task_type: str
    role: str
    merchant_goal: str
    marketplace: str
    source_mode: str
    stage: str
    category_hint: str
    source_route: str
    knowledge_titles: list[str]


class OwnedCommerceAgent:
    """Base class for deterministic Jiejing role agents."""

    role = "ceo"
    merchant_label = "AI CEO"

    def generate(self, task: JiejingTask, knowledge_items: list[KnowledgeItem]) -> dict[str, Any]:
        ctx = self._context(task, knowledge_items)
        sections = self.sections(task, ctx)
        self._ensure_required_sections(task, sections, ctx)
        return {
            "model_mode": "jiejing_owned_agent",
            "product": ctx.product,
            "task_type": task.task_type,
            "required_sections": [str(item) for item in task.output_contract.get("required_sections", [])],
            "sections": sections,
            "merchant_readable_summary": self.summary(ctx),
            "owned_agent_execution": {
                "executor": EXECUTOR_NAME,
                "executor_version": EXECUTOR_VERSION,
                "role": ctx.role,
                "merchant_label": self.merchant_label,
                "agent_class": type(self).__name__,
                "uses_live_model": False,
                "uses_external_tools": False,
                "knowledge_items_used": ctx.knowledge_titles,
                "replacement_scope": "commerce_specific_agent_logic",
                "real_execution_allowed": False,
            },
            "limits": [
                "这是捷境本地 owned Agent 生成的商家报告，不代表实时平台执行结果。",
                "供应商、类目、政策、物流、素材等未知事实会保留为待补资料，直到导入或授权数据确认。",
                "本次没有执行真实 eBay 发布、付款、退款、广告、采购、政策修改或买家消息发送。",
            ],
        }

    def sections(self, task: JiejingTask, ctx: AgentContext) -> dict[str, Any]:
        return {}

    def summary(self, ctx: AgentContext) -> str:
        return f"{self.merchant_label}已为 {ctx.product} 生成 {ctx.task_type} 报告。"

    def _context(self, task: JiejingTask, knowledge_items: list[KnowledgeItem]) -> AgentContext:
        agent_profile = task.input.get("agent_profile") if isinstance(task.input.get("agent_profile"), dict) else {}
        role = str(agent_profile.get("role") or "ceo")
        product = str(task.input.get("product") or task.context.get("sample_name") or "current product").strip()
        marketplace = str(task.input.get("marketplace") or task.raw.get("platform") or "ebay").strip()
        source_mode = str(task.input.get("source_mode") or "manual_or_authorized_source").strip()
        merchant_goal = str(task.input.get("merchant_goal") or task.input.get("notes") or "").strip()
        stage = str(task.raw.get("stage") or task.context.get("stage") or "demo").strip()
        return AgentContext(
            product=product,
            task_type=task.task_type,
            role=role,
            merchant_goal=merchant_goal,
            marketplace=marketplace,
            source_mode=source_mode,
            stage=stage,
            category_hint=self._category_hint(product),
            source_route=self._source_route(source_mode),
            knowledge_titles=[item.title for item in knowledge_items[:4]],
        )

    def _ensure_required_sections(self, task: JiejingTask, sections: dict[str, Any], ctx: AgentContext) -> None:
        for section in [str(item) for item in task.output_contract.get("required_sections", [])]:
            sections.setdefault(section, self._fallback_section(section, ctx))

    def _fallback_section(self, section: str, ctx: AgentContext) -> str:
        return (
            f"{section}：{self.merchant_label}已为 {ctx.product} 建立该部分结构。"
            "真实执行前仍需要补齐可追溯来源数据。"
        )

    def _category_hint(self, product: str) -> str:
        lower = product.lower()
        if any(word in lower for word in ["cup", "tumbler", "bottle", "mug"]):
            return "水杯 / 旅行杯"
        if any(word in lower for word in ["incense", "burner", "香炉"]):
            return "家居装饰 / 香炉"
        if any(word in lower for word in ["organizer", "bag", "storage", "收纳"]):
            return "家居收纳"
        if any(word in lower for word in ["clip", "cable", "理线"]):
            return "桌面配件 / 理线用品"
        return "eBay 普通消费品"

    def _source_route(self, source_mode: str) -> str:
        value = source_mode.lower()
        if "1688" in value:
            return "1688 货源路线：可以做货源匹配，但下单和付款必须进入决策中心。"
        if "manual" in value:
            return "手动货源路线：商家需要提供链接、图片、报价或表格后，才能锁定后续事实。"
        return "授权数据路线：只使用本任务已授权的数据。"


class CeoAgent(OwnedCommerceAgent):
    role = "ceo"
    merchant_label = "AI CEO"

    def sections(self, task: JiejingTask, ctx: AgentContext) -> dict[str, Any]:
        if task.task_type == "ceo.final_report":
            return {
                "current_status": f"{ctx.product} 已完成本地 Runtime 交接，覆盖市场、货源、Listing、素材、客服、财务和决策中心包。",
                "source_health": "生产级结论仍需要接入 eBay 账号、货源、物流探针或商家输入后才能锁定。",
                "reports_ready": [
                    "market.report",
                    "source.match",
                    "listing.package",
                    "asset.brief",
                    "customer.learn_product",
                    "finance.review",
                    "confirmation.package",
                ],
                "publish_lock": "真实 eBay 发布已锁定。只有决策中心批准后，ExecutionService 才能接收发布请求。",
                "next_minimum_action": "补齐真实供应商事实和店铺政策 ID，再重新跑 Listing 与财务校验，之后才能进入发布确认。",
            }
        if task.task_type == "owner.review":
            return {
                "runtime_findings": "Runtime 已具备 owned role 执行、知识检索、报告合同、确认门禁和 Hermes 交接边界。",
                "saas_findings": "SaaS 应按任务调用 Runtime、展示进度，并在缺少供应商、类目或政策事实时停住，而不是假装闭环完成。",
                "hermes_findings": "Hermes 仍可作为内部执行工人，但捷境必须拥有工作流合同和报告形态。",
                "next_improvements": [
                    "在同一报告合同后接入 live LLM role client。",
                    "连接只读 eBay 和货源探针。",
                    "把任务状态持久化到具备租户隔离的生产后端。",
                ],
            }
        return {
            "merchant_goal": ctx.merchant_goal or f"评估并准备 {ctx.product} 的 eBay-first 经营工作流。",
            "merchant_stage": ctx.stage,
            "risk_boundary": "AI 可以调研、起草、预填、对比、总结并生成工作记录。付款、发布、退款、广告、政策、授权、采购和敏感买家承诺必须进入决策中心。",
            "task_breakdown": [
                "market.data_packet",
                "market.report",
                "source.match",
                "listing.package",
                "asset.brief",
                "customer.learn_product",
                "finance.review",
                "confirmation.package",
            ],
            "next_tasks": "先生成 market data packet，再跑 Market Report；不要把整条链一次性交给单个角色。",
        }

    def summary(self, ctx: AgentContext) -> str:
        return f"AI CEO 已把 {ctx.product} 拆成捷境电商任务，并保持高风险动作锁定。"


class MarketAgent(OwnedCommerceAgent):
    role = "market-manager"
    merchant_label = "市场经理"

    def sections(self, task: JiejingTask, ctx: AgentContext) -> dict[str, Any]:
        return {
            "category_overview": {
                "one_line": f"{ctx.product} 暂按 {ctx.category_hint} 处理；只有在来源事实确认后，才适合做小批量 eBay 测试。",
                "market_level": "当前是方向性判断；生产级需求数字需要接入 live Browse/API/search 或官方数据源。",
                "trend": "更应按稳定长尾需求评估，不使用保证销量或爆发增长话术。",
            },
            "buyer_profile": [
                "寻找实用、低风险商品的家庭用户。",
                "如果商品有视觉或家居属性，可覆盖礼品买家和小空间使用者。",
                "对价格敏感、会比较发货时效、退货政策和图片可信度的买家。",
            ],
            "ebay_price_bands": [
                {"band": "US $8.99-12.99", "position": "入门测试", "use": "可做流量测试，但利润通常较紧。"},
                {"band": "US $13.00-18.99", "position": "主测试带", "use": "轻小件在运费受控时更适合从这里验证。"},
                {"band": "US $19.00-29.99", "position": "组合价值带", "use": "需要更强图片、数量或材质证明支撑。"},
                {"band": "US $30+", "position": "高客单带", "use": "除非品牌、组合或功能证据足够强，否则不建议直接进入。"},
            ],
            "competitor_top5": [
                "竞品方向 A：低价但细节图弱，可用更清楚的尺寸和使用场景图超越。",
                "竞品方向 B：组合 Listing 感知价值更强，需要核对实际包装数量。",
                "竞品方向 C：强调快速发货，必须与真实处理时间和承运能力一致。",
                "竞品方向 D：标题堆关键词，信任感偏低。",
                "竞品方向 E：生活场景图较好，但常缺少材质或尺寸证明。",
            ],
            "buyer_pain_points": [
                "图片效果好于实物，导致到货预期落差。",
                "尺寸、容量或适配场景容易被误解。",
                "发货和到达时间不清楚。",
                "材质、气味、漏液、易碎或配件包含情况没有说明清楚。",
            ],
            "keywords": [
                ctx.product,
                ctx.category_hint,
                "轻小件",
                "家用",
                "礼品",
                "eBay US",
            ],
            "differentiation": "核心差异化不是夸张卖点，而是把尺寸、材质、包装数量、使用场景和限制说明得比泛化 Listing 更可信。",
            "pricing_direction": "建议先从主测试价带验证；真实成本、运费、退货预留和政策规则确认后再调整价格。",
            "risk_assessment": [
                "需求风险：未接入 live eBay 信号前，只能作为方向判断。",
                "竞争风险：通用品主要拼信任、图片质量和履约承诺。",
                "物流风险：重量和包装尺寸会直接吞掉利润。",
                "退货风险：尺寸或材质表达不清会造成买家失望。",
                "合规风险：避免医疗、安全、品牌、认证和夸张效果承诺。",
            ],
            "conclusion_next_step": "如果供应商事实、包装尺寸、成本和履约路线能够验证，可以进入货源匹配；不能用旧演示商品补空白。",
        }

    def summary(self, ctx: AgentContext) -> str:
        return f"市场经理已为 {ctx.product} 生成结构化 eBay Market Report；生产决策前仍需要补齐 live 数据来源。"


class FinanceSupplyAgent(OwnedCommerceAgent):
    role = "finance-supply"
    merchant_label = "财务与货源经理"

    def sections(self, task: JiejingTask, ctx: AgentContext) -> dict[str, Any]:
        if task.task_type == "source.match":
            return {
                "source_route": ctx.source_route,
                "supplier_candidates": [
                    "候选 A：1688 或商家提供的供应商链接；需要链接、API 或表格接入后才能确认。",
                    "候选 B：较低 MOQ 的备选供应商；需要报价和图片后才能确认。",
                    "候选 C：库存稳定性备份货源；需要发货地和包装信息后才能确认。",
                ],
                "cost_inputs": {
                    "purchase_cost": "待补供应商报价",
                    "domestic_shipping": "待补国内运费",
                    "platform_fee": "待补平台费用",
                    "international_shipping": "待补国际运费",
                    "return_reserve": "待补退货预留",
                },
                "package_inputs": {
                    "weight_g": "待补",
                    "length_cm": "待补",
                    "width_cm": "待补",
                    "height_cm": "待补",
                    "fragile_or_restricted": "待补",
                },
                "supplier_questions": [
                    "确认准确材质和包装数量。",
                    "确认实测商品尺寸和包装尺寸。",
                    "确认克重维度的包装重量。",
                    "确认是否包含配件。",
                    "确认发货地、处理时效和补发规则。",
                ],
                "procurement_boundary": "AI 可以准备供应商对比；下单、付款、地址写入和取消必须进入决策中心或命中已保存的商家规则。",
            }
        return {
            "cost_table": [
                {"item": "target_sale_price", "value": "US $18.99-24.99 候选范围"},
                {"item": "purchase_cost", "value": "待补供应商报价"},
                {"item": "domestic_shipping", "value": "待补"},
                {"item": "international_shipping", "value": "待补承运商报价"},
                {"item": "eBay_fee", "value": "待补账号/类目费用模型"},
                {"item": "return_reserve", "value": "待补政策与瑕疵风险"},
            ],
            "net_profit_money": "待补。发布确认前，Runtime 需要金额值，不能只给百分比。",
            "logistics_route": "候选路线可以是 1688 到商家验货，也可以是供应商/直发履约，但交付承诺必须匹配真实处理和跟踪能力。",
            "subscription_allocation": "如果涉及 eBay 店铺订阅或刊登插入费，财务复核必须在确认前展示该成本行。",
            "return_reserve": "类目退货率、商品易损性和政策条款明确后，再设置金额化退货预留。",
            "risk_notes": [
                "运费报价可能直接推翻利润。",
                "重量或尺寸错误会造成运费低估。",
                "退货和瑕疵必须金额化，不能藏在百分比假设里。",
            ],
            "next_action": "收集供应商报价、包装数据、政策 ID 和运费报价后，重新跑财务复核。",
        }

    def summary(self, ctx: AgentContext) -> str:
        return f"财务与货源经理已为 {ctx.product} 生成货源、成本、包装和利润边界。"


class ProductListingAgent(OwnedCommerceAgent):
    role = "product-manager"
    merchant_label = "产品刊登经理"

    def sections(self, task: JiejingTask, ctx: AgentContext) -> dict[str, Any]:
        title = self._title(ctx.product)
        return {
            "sku": self._sku(ctx.product),
            "title": {
                "value": title,
                "max_length": 80,
                "length": len(title),
                "status": "草稿，等待类目和供应商事实确认",
            },
            "subtitle_notice": "eBay Subtitle 可能是付费项。默认关闭，除非商家明确开启。",
            "category_id": "待补：需要用 eBay Taxonomy API 或人工复核所选站点和类目。",
            "condition": "默认 New；如果商家标记二手/翻新，必须确认类目支持。",
            "format": "Fixed Price",
            "price": "待财务复核；只有在费用和运费报价明确后，才能使用候选价带。",
            "quantity": "初始测试数量建议 5-20；只有货源稳定性验证后才考虑更高库存。",
            "item_specifics": {
                "fixed_common": {
                    "Brand": "Unbranded 或商家品牌，待确认",
                    "Type": ctx.category_hint,
                    "Material": "待供应商确认",
                    "Color": "待变体决策确认",
                    "MPN": "如合规，可填 Does Not Apply",
                    "UPC": "如类目和站点允许，可填 Does Not Apply",
                },
                "dynamic_by_category": "真实发布前 Runtime 必须查询 eBay item specifics；水杯、家居、收纳、电子等字段不同。",
            },
            "description_html": (
                f"<h2>{ctx.product}</h2><ul>"
                "<li>使用场景和包装数量等待供应商确认。</li>"
                "<li>材质、尺寸、重量和随附配件必须核实。</li>"
                "<li>发货和退货条款以授权店铺政策为准。</li>"
                "</ul><p>FAQ：尺寸、材质、包装内容、处理时效和退货条件必须在发布前展示。</p>"
            ),
            "pictures_required": [
                "1 张白底主图，建议 1600x1600。",
                "2-3 张匹配买家使用场景的场景图。",
                "1 张带真实测量值的尺寸图。",
                "1 张细节/纹理图。",
                "1 张包装/包含物图。",
            ],
            "video_required": "15-30 秒商品演示：开头吸引点、手持/使用场景、关键细节特写、尺寸/包装证明、克制行动引导。",
            "package_weight": "待补实测包装重量，单位克。",
            "package_dimensions": "待补包装长 x 宽 x 高，单位厘米。",
            "business_policies": {
                "fulfillmentPolicyId": "待读取授权店铺政策或商家选择。",
                "paymentPolicyId": "待读取授权店铺政策或商家选择。",
                "returnPolicyId": "待读取授权店铺政策或商家选择。",
                "note": "这三项政策是店铺模板，可被 Listing 复用，但仍要检查是否适合该商品的发货和退货场景。",
            },
            "publish_blockers": [
                "类目 ID 和必填 item specifics 尚未验证。",
                "供应商材质、尺寸、包装重量和发货地尚未确认。",
                "Business policy IDs 尚未附加。",
                "最终价格和运费报价尚未通过财务复核。",
                "商业图片/视频 manifest 尚未附加。",
                "商家发布确认尚未记录。",
            ],
        }

    def summary(self, ctx: AgentContext) -> str:
        return f"产品刊登经理已为 {ctx.product} 起草 eBay Listing Package；验证和决策中心确认完成前，真实发布保持锁定。"

    def _title(self, product: str) -> str:
        title = f"{product.title()} Lightweight Practical eBay Test Listing New"
        return title[:80].rstrip()

    def _sku(self, product: str) -> str:
        safe = "".join(ch if ch.isalnum() else "-" for ch in product.upper()).strip("-")
        safe = "-".join(part for part in safe.split("-") if part)
        return f"JJ-{safe[:28] or 'PRODUCT'}-TEST"


class AssetManagerAgent(OwnedCommerceAgent):
    role = "asset-manager"
    merchant_label = "素材经理"

    def sections(self, task: JiejingTask, ctx: AgentContext) -> dict[str, Any]:
        return {
            "image_plan": [
                {"type": "main_image", "count": 2, "size": "1600x1600", "goal": "生成干净的 eBay 主图，商品清晰，不加入未证实承诺。"},
                {"type": "scene_image", "count": 3, "size": "1600x1600 or 4:5", "goal": "展示真实家居、旅行或使用场景。"},
                {"type": "detail_image", "count": 2, "size": "1600x1600", "goal": "展示材质、纹理、配件或功能细节。"},
                {"type": "dimension_image", "count": 1, "size": "1600x1600", "goal": "供应商确认后展示实测尺寸。"},
            ],
            "detail_page_plan": "一张 eBay 长图详情：痛点场景、关键特征证明、尺寸/包装部分、使用步骤、退货/发货说明。",
            "video_plan": {
                "duration": "15-30 seconds",
                "structure": [
                    "0-3s：手持商品或直接进入使用场景。",
                    "4-12s：展示主要功能和比例。",
                    "13-22s：细节特写、包装内容、限制说明。",
                    "23-30s：安全克制的结尾，不使用夸张承诺。",
                ],
                "voiceover": "只使用已确认商品事实；不编造认证、医疗效果或不可能履约的发货承诺。",
            },
            "asset_settings": {
                "platform": ctx.marketplace,
                "default_main_size": "1600x1600",
                "optional_ratio": ["1:1", "4:5", "16:9 video cover"],
                "generation_count": "按任务由商家选择",
            },
            "claim_risk": [
                "供应商事实确认前，不声明准确容量、材质、保温、防水、手工或配件包含信息。",
                "除非商家拥有权利，不使用品牌名、Logo 或受版权保护标识。",
            ],
            "media_manifest_status": "素材任务包已准备；实际图片/视频文件等待生成工具返回 manifest。",
        }

    def summary(self, ctx: AgentContext) -> str:
        return f"素材经理已为 {ctx.product} 准备主图、详情页和短视频任务；实际文件仍等待素材工具 manifest。"


class CustomerServiceAgent(OwnedCommerceAgent):
    role = "customer-service"
    merchant_label = "客服专员"

    def sections(self, task: JiejingTask, ctx: AgentContext) -> dict[str, Any]:
        return {
            "product_service_file": {
                "product": ctx.product,
                "category": ctx.category_hint,
                "facts_to_learn": ["材质", "尺寸", "包装数量", "处理时效", "发货路线", "退货条件"],
                "facts_pending": ["供应商测量值", "重量", "政策 IDs", "素材 manifest"],
            },
            "buyer_question_map": [
                "这是全新未使用商品吗？",
                "尺寸或容量是多少？",
                "包装里包含什么？",
                "什么时候能到？",
                "如果不适合，我能退货吗？",
            ],
            "faq": {
                "size": "只用已确认 Listing 尺寸回答；否则说明团队会在最终发布前核实。",
                "shipping": "政策附加后，才使用店铺 fulfillment policy 和追踪承诺。",
                "return": "按店铺退货政策回答；没有确认前，不承诺超出政策的补偿。",
                "package": "供应商确认后，才说明包含物。",
            },
            "reply_boundary": "低风险商品事实可自动起草。退款、部分退款、补发、地址变更、补偿、差评处理和政策例外必须人工接管。",
            "auto_reply_templates": [
                "感谢你的消息。我正在核对已确认的商品细节，会用准确的尺寸/包装信息回复你。",
                "该商品遵循 Listing 上展示的店铺退货政策。任何退款或补发场景，我们会先复核订单细节。",
                "请发送包装和商品状态照片，方便我们准确核实问题。",
            ],
            "escalation_rules": [
                "买家请求退款、补发、地址变更、取消、补偿或政策例外时升级人工。",
                "问题涉及未验证材质、安全、认证或性能承诺时升级人工。",
            ],
        }

    def summary(self, ctx: AgentContext) -> str:
        return f"客服专员已学习 {ctx.product} 的商品档案，并设置低风险自动回复边界。"


class ConfirmationCenterAgent(OwnedCommerceAgent):
    role = "confirmation-center"
    merchant_label = "决策中心"

    def sections(self, task: JiejingTask, ctx: AgentContext) -> dict[str, Any]:
        return {
            "allowed_auto_actions": [
                "整理报告和工作记录。",
                "生成草稿和缺口清单。",
                "准备素材任务简报。",
                "基于已确认事实准备客服草稿。",
            ],
            "default_rule_actions": [
                "复用已保存的非风险偏好，例如图片尺寸、测试数量范围和报告格式。",
                "必要输入齐全时，继续下一个低风险起草任务。",
            ],
            "every_time_confirm_actions": [
                "真实 eBay 发布或修改。",
                "价格或库存变更。",
                "广告预算开始、停止或调整。",
                "退款、部分退款、补发或补偿承诺。",
                "采购下单、付款、取消或地址写入。",
                "付款、退货、履约、订阅、OAuth 或账号政策编辑。",
                "超出已确认政策的敏感买家服务承诺。",
            ],
            "blocked_actions": [
                "绕过 eBay 官方授权。",
                "在前端代码使用客户或 token 密钥。",
                "在缺少类目、item specifics、包装、政策、财务或素材事实时发布。",
                "把 AI 推断的市场数据当成有来源数据。",
            ],
            "missing_facts": [
                "供应商真实尺寸、重量、材质、包装内容和发货地。",
                "eBay category ID 和必填 item specifics。",
                "Fulfillment、payment、return policy IDs。",
                "最终运费报价和财务锁定。",
                "如需要图片/视频，必须有实际 media manifest。",
            ],
        }

    def summary(self, ctx: AgentContext) -> str:
        return f"决策中心已打包 {ctx.product} 的高风险决策；未经批准不能执行真实动作。"


class OwnedAgentExecutor:
    """Routes standard Jiejing tasks to concrete owned role agents."""

    name = EXECUTOR_NAME
    version = EXECUTOR_VERSION

    def __init__(self) -> None:
        self._agents: dict[str, OwnedCommerceAgent] = {
            "ceo": CeoAgent(),
            "market-manager": MarketAgent(),
            "finance-supply": FinanceSupplyAgent(),
            "product-manager": ProductListingAgent(),
            "asset-manager": AssetManagerAgent(),
            "customer-service": CustomerServiceAgent(),
            "confirmation-center": ConfirmationCenterAgent(),
        }

    def generate_report(self, task: JiejingTask, knowledge_items: list[KnowledgeItem]) -> dict[str, Any]:
        role = self._role_for(task)
        agent = self._agents.get(role) or self._agents["ceo"]
        return agent.generate(task, knowledge_items)

    def _role_for(self, task: JiejingTask) -> str:
        agent_profile = task.input.get("agent_profile")
        if isinstance(agent_profile, dict) and str(agent_profile.get("role") or "").strip():
            return str(agent_profile.get("role"))
        fallback = {
            "market.report": "market-manager",
            "source.match": "finance-supply",
            "listing.package": "product-manager",
            "asset.brief": "asset-manager",
            "customer.learn_product": "customer-service",
            "finance.review": "finance-supply",
            "confirmation.package": "confirmation-center",
        }
        return fallback.get(task.task_type, "ceo")

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "agent_count": len(self._agents),
            "roles": sorted(self._agents),
            "live_model_required": False,
            "external_tool_required": False,
            "real_execution_allowed": False,
        }
