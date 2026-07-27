"""Model client boundaries for Jiejing Agent Runtime.

The MVP keeps model execution local and deterministic. A production model
client can later implement the same interface without changing Runtime.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from urllib.parse import urlparse
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from typing import Any, Callable

from .models import JiejingTask


def _env_truthy(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, *, default: int, minimum: int, maximum: int) -> int:
    raw = os.environ.get(name)
    try:
        value = int(str(raw).strip()) if raw not in {None, ""} else default
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def _bounded_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


class ModelClient(ABC):
    name = "model-client"
    version = "0.0.0"

    @abstractmethod
    def generate_report(self, task: JiejingTask) -> dict[str, Any]:
        """Generate a structured report body for a task."""

    def generate_text(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.2,
        max_output_tokens: int | None = None,
        timeout_seconds: int | None = None,
        on_text_delta: Callable[[str], None] | None = None,
    ) -> dict[str, Any]:
        """Generate a merchant-facing plain-text answer.

        Chat is used only after the SaaS backend resolves a BYOK secret ref.
        The default implementation is deliberately explicit so callers do not
        mistake rule-based report fallbacks for a live merchant model answer.
        """
        raise RuntimeError("model_client_text_generation_not_supported")


MERCHANT_REPORT_LANGUAGE_GUARDRAIL = (
    "商家可见正文必须使用简体中文；JSON keys can stay in English, and terms like eBay, SKU, Listing, Market Report, Listing Package may remain English. "
    "Do not use test-flavored words such as placeholder, mock, demo, sample, simulated, or fake in merchant-facing text. "
    "If a fact is not available from the sanitized packet or approved inputs, write it as 待补资料 and explain the exact missing source. "
    "Every section should be useful to a Chinese-speaking eBay merchant: include 依据, 结论, 风险/缺口, and 下一步 when applicable. "
    "For market.report, cover store state, listing opportunity, price/fee risk, order/fulfillment risk, recommended next tasks, and confirmation items. "
    "For listing.package, cover title suggestions, item specifics, description structure, image/video asset plan, price and margin reminders, policy/logistics checks, and a pre-publish confirmation checklist. "
    "Never claim real publish, payment, refund, ad, or policy execution."
)


class RuleBasedModelClient(ModelClient):
    """Deterministic local model stand-in for runtime development."""

    name = "rule-based-model"
    version = "0.1.0"

    def generate_text(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.2,
        max_output_tokens: int | None = None,
        timeout_seconds: int | None = None,
        on_text_delta: Callable[[str], None] | None = None,
    ) -> dict[str, Any]:
        return {
            "text": "本地规则模型不能作为 AI CEO 对话结果。请在设置里确认 BYOK 模型 key 已由后端保存。",
            "model_mode": "rule_based_text_unavailable",
            "model_client": self.name,
            "model_configured": False,
        }

    def generate_report(self, task: JiejingTask) -> dict[str, Any]:
        sections = task.output_contract.get("required_sections", [])
        product = task.input.get("product") or task.context.get("sample_name") or "current product"
        return {
            "model_mode": "rule_based",
            "product": product,
            "task_type": task.task_type,
            "required_sections": sections,
            "sections": {section: self._section_text(task, section, product) for section in sections},
            "merchant_readable_summary": self._merchant_summary(task, product),
            "limits": [
                "No live eBay API call was made.",
                "No live sourcing platform call was made.",
                "No real publish, payment, refund, ad, or policy change was executed.",
            ],
        }

    def _merchant_summary(self, task: JiejingTask, product: str) -> str:
        agent_label = ""
        agent_profile = task.input.get("agent_profile")
        if isinstance(agent_profile, dict):
            agent_label = str(agent_profile.get("merchant_label") or "")
        prefix = f"{agent_label}: " if agent_label else ""
        summaries = {
            "ceo.intake": f"{prefix}AI CEO 已接收 {product} 的经营目标，并拆成可核查的跨境电商任务。",
            "market.data_packet": f"{prefix}{product} 的市场数据包已按来源记录整理，缺失数据保持可见。",
            "market.report": f"{prefix}{product} 的市场报告已形成结构化判断，数据缺口和下一步任务已标出。",
            "source.match": f"{prefix}{product} 的货源事实已整理，采购前仍需确认供应商真实性。",
            "listing.package": f"{prefix}{product} 的 eBay 刊登资料包已生成草稿，但发布前阻断项仍需处理。",
            "asset.brief": f"{prefix}{product} 的图片、详情页和视频素材规划已准备。",
            "customer.learn_product": f"{prefix}{product} 的客服学习资料已准备，自动回复前仍需人工确认敏感承诺。",
            "finance.review": f"{prefix}{product} 的费用核算已整理，利润和物流风险保持可见。",
            "confirmation.package": f"{prefix}确认中心已收集 {product} 的高风险决策项。",
            "ceo.final_report": f"{prefix}AI CEO 已汇总 {product} 的闭环经营记录。",
            "owner.review": f"{prefix}Owner review 已记录 Runtime 和 SaaS 的改进项。",
        }
        return summaries.get(task.task_type, f"{prefix}{product} 的结构化报告已生成。")

    def _section_text(self, task: JiejingTask, section: str, product: str) -> str:
        if task.task_type == "listing.package":
            examples = {
                "title": f"待确认 eBay 标题方向：围绕 {product} 的核心用途、规格和搜索词，最终标题需控制在 80 字符内。",
                "subtitle_notice": "eBay subtitle 可能产生额外费用，未经过商家确认前不建议启用。",
                "business_policies": "发货、付款、退货政策必须来自已授权店铺的官方政策记录。",
                "publish_blockers": "发布前还需补齐供应商事实、类目 Item Specifics、最终价格、图片视频素材和政策 ID。",
            }
            return examples.get(section, f"{product} 的 `{section}` 刊登字段已进入草稿，缺失事实保持待补资料。")
        if task.task_type == "market.report":
            examples = {
                "recommendation": "建议只在来源可信、利润可算、履约风险可控时进入小批量测试。",
                "risk_signals": "重点关注来源置信度不足、包裹重量不清、买家预期不匹配和费用挤压风险。",
            }
            return examples.get(section, f"{product} 的市场报告 `{section}` 已整理，未知数据保持待补资料。")
        if task.task_type == "confirmation.package":
            return f"`{section}` 已进入确认中心，任何真实动作前都需要商家确认。"
        return f"{product} 的 `{section}` 已整理。"


class OpenAICompatibleModelClient(ModelClient):
    """Configurable HTTP model client with deterministic fallback.

    This client is intentionally provider-neutral. It uses an OpenAI-compatible
    chat-completions request only when endpoint, key, and model are explicitly
    configured through environment variables. Otherwise it falls back to the
    local rule-based client so tests and demos never block on external billing.
    """

    name = "openai-compatible-http-model"
    version = "0.1.0"

    def __init__(
        self,
        endpoint: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        timeout_seconds: int = 45,
        fallback: ModelClient | None = None,
    ) -> None:
        self.live_disabled = _env_truthy("JIEJING_MODEL_DISABLE_LIVE")
        self.fallback = fallback or RuleBasedModelClient()
        self.timeout_seconds = timeout_seconds
        if self.live_disabled:
            self.endpoint = endpoint or ""
            self.api_key = ""
            self.model = model or ""
            return
        base_url = (os.environ.get("JIEJING_MODEL_BASE_URL") or os.environ.get("OPENAI_BASE_URL") or "").rstrip("/")
        self.endpoint = endpoint or os.environ.get("JIEJING_MODEL_ENDPOINT") or (f"{base_url}/chat/completions" if base_url else "")
        self.api_key = api_key or os.environ.get("JIEJING_MODEL_API_KEY") or os.environ.get("OPENAI_API_KEY") or ""
        self.model = model or os.environ.get("JIEJING_MODEL") or os.environ.get("OPENAI_MODEL") or ""

    def configured(self) -> bool:
        return bool(self.endpoint and self.api_key and self.model)

    def generate_report(self, task: JiejingTask) -> dict[str, Any]:
        if not self.configured():
            report = self.fallback.generate_report(task)
            report["model_mode"] = "http_model_not_configured_fallback"
            report["model_client"] = self.name
            report["model_configured"] = False
            return report
        try:
            return self._generate_live(task)
        except Exception as exc:  # pragma: no cover - live provider dependent
            report = self.fallback.generate_report(task)
            report["model_mode"] = "http_model_error_fallback"
            report["model_client"] = self.name
            report["model_configured"] = True
            report["model_error"] = str(exc)[:500]
            return report

    def _generate_live(self, task: JiejingTask) -> dict[str, Any]:
        product = task.input.get("product") or task.context.get("sample_name") or "current product"
        sections = task.output_contract.get("required_sections", [])
        prompt = {
            "role": "user",
            "content": (
                "You are the Jiejing AI CEO Runtime report writer. Return ONLY valid JSON with keys: "
                "merchant_readable_summary, required_sections, sections, limits. The sections object MUST contain "
                "one non-empty entry for every required section listed below. Keep unknown supplier, eBay policy, taxonomy, "
                "logistics, cost, media, and customer-service facts as 待补资料.\n"
                f"{MERCHANT_REPORT_LANGUAGE_GUARDRAIL}\n\n"
                f"Task type: {task.task_type}\n"
                f"Product: {product}\n"
                f"Merchant goal: {task.input.get('merchant_goal', '')}\n"
                f"Required sections: {json.dumps(sections, ensure_ascii=False)}\n"
                f"Agent profile: {json.dumps(task.input.get('agent_profile', {}), ensure_ascii=False)}\n"
                f"Agent instructions: {json.dumps(task.input.get('agent_instructions', {}), ensure_ascii=False)}\n"
                f"Tool permissions: {json.dumps(task.input.get('tool_permissions', []), ensure_ascii=False)}\n"
                f"Handoff contract: {json.dumps(task.input.get('handoff_contract', {}), ensure_ascii=False)}\n"
                f"Input: {json.dumps(task.input, ensure_ascii=False)}"
            ),
        }
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": "你为捷境 eBay-first 商家 SaaS 写结构化经营报告。商家可见正文必须是简体中文，严格保留确认中心边界。",
                },
                prompt,
            ],
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
        }
        request = urllib.request.Request(
            self.endpoint,
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={
                "content-type": "application/json",
                "authorization": f"Bearer {self.api_key}",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:  # pragma: no cover - live provider dependent
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"model HTTP {exc.code}: {detail[:300]}") from exc
        content = body["choices"][0]["message"]["content"]
        parsed = json.loads(content)
        parsed.setdefault("sections", {})
        parsed.setdefault("limits", [])
        parsed["model_mode"] = "live_http_model"
        parsed["model_client"] = self.name
        parsed["model_configured"] = True
        parsed["product"] = product
        parsed["task_type"] = task.task_type
        parsed["required_sections"] = sections
        parsed["_usage"] = _normalized_model_usage(body)
        return parsed

    def generate_text(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.2,
        max_output_tokens: int | None = None,
        timeout_seconds: int | None = None,
        on_text_delta: Callable[[str], None] | None = None,
    ) -> dict[str, Any]:
        if not self.configured():
            raise RuntimeError("model_client_not_configured")
        token_budget = _bounded_int(
            max_output_tokens,
            default=_env_int("JIEJING_MODEL_TEXT_MAX_TOKENS", default=900, minimum=128, maximum=4096),
            minimum=128,
            maximum=4096,
        )
        request_timeout = _bounded_int(
            timeout_seconds,
            default=self.timeout_seconds,
            minimum=1,
            maximum=max(1, self.timeout_seconds),
        )
        stream_enabled = _env_truthy(
            "JIEJING_MODEL_TEXT_STREAM_ENABLED",
            default=urlparse(self.endpoint).netloc.lower() == "api.deepseek.com",
        )
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
            "max_tokens": token_budget,
            "stream": stream_enabled,
        }
        if stream_enabled:
            payload["stream_options"] = {"include_usage": True}
        request = urllib.request.Request(
            self.endpoint,
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={
                "content-type": "application/json",
                "authorization": f"Bearer {self.api_key}",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=request_timeout) as response:
                if stream_enabled:
                    content, finish_reason, usage = self._read_streaming_text(response, on_text_delta=on_text_delta)
                    return {
                        "text": content,
                        "model_mode": "live_http_model_text_stream",
                        "model_client": self.name,
                        "model_configured": True,
                        "model": self.model,
                        "timeout_seconds": request_timeout,
                        "max_output_tokens": token_budget,
                        "finish_reason": finish_reason,
                        "_usage": usage,
                    }
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:  # pragma: no cover - live provider dependent
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"model HTTP {exc.code}: {detail[:300]}") from exc
        choice = body["choices"][0]
        content = choice["message"]["content"]
        return {
            "text": str(content or "").strip(),
            "model_mode": "live_http_model_text",
            "model_client": self.name,
            "model_configured": True,
            "model": self.model,
            "timeout_seconds": request_timeout,
            "max_output_tokens": token_budget,
            "finish_reason": str(choice.get("finish_reason") or ""),
            "_usage": _normalized_model_usage(body),
        }

    @staticmethod
    def _read_streaming_text(
        response: Any,
        *,
        on_text_delta: Callable[[str], None] | None = None,
    ) -> tuple[str, str, dict[str, int]]:
        chunks: list[str] = []
        finish_reason = ""
        usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
        for raw_line in response:
            line = raw_line.decode("utf-8", errors="replace").strip() if isinstance(raw_line, bytes) else str(raw_line).strip()
            if not line or not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if not data or data == "[DONE]":
                continue
            try:
                event = json.loads(data)
            except json.JSONDecodeError:
                continue
            event_usage = _normalized_model_usage(event if isinstance(event, dict) else {})
            if event_usage["total_tokens"] or event_usage["input_tokens"] or event_usage["output_tokens"]:
                usage = event_usage
            choices = event.get("choices") if isinstance(event, dict) else None
            if not isinstance(choices, list) or not choices:
                continue
            choice = choices[0] if isinstance(choices[0], dict) else {}
            delta = choice.get("delta") if isinstance(choice.get("delta"), dict) else {}
            content = delta.get("content")
            if isinstance(content, str) and content:
                chunks.append(content)
                if on_text_delta is not None:
                    try:
                        on_text_delta(content)
                    except Exception:
                        # A disconnected browser must not discard a provider answer
                        # that still needs to be validated and persisted server-side.
                        pass
            if choice.get("finish_reason"):
                finish_reason = str(choice.get("finish_reason") or "")
        return "".join(chunks).strip(), finish_reason, usage


class OpenAIResponsesModelClient(ModelClient):
    """OpenAI Responses API model client with deterministic fallback.

    The Responses API is the preferred OpenAI interface for direct model
    requests and tool-capable workflows. This client is still optional: if the
    required environment variables are absent, Runtime falls back to local
    deterministic output and records that the live model was not configured.
    """

    name = "openai-responses-model"
    version = "0.1.0"

    def __init__(
        self,
        endpoint: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        timeout_seconds: int = 60,
        fallback: ModelClient | None = None,
    ) -> None:
        self.live_disabled = _env_truthy("JIEJING_MODEL_DISABLE_LIVE")
        self.fallback = fallback or RuleBasedModelClient()
        self.timeout_seconds = timeout_seconds
        if self.live_disabled:
            self.endpoint = endpoint or ""
            self.api_key = ""
            self.model = model or ""
            return
        base_url = (os.environ.get("JIEJING_MODEL_BASE_URL") or os.environ.get("OPENAI_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
        self.endpoint = endpoint or os.environ.get("JIEJING_MODEL_ENDPOINT") or f"{base_url}/responses"
        self.api_key = api_key or os.environ.get("JIEJING_MODEL_API_KEY") or os.environ.get("OPENAI_API_KEY") or ""
        self.model = model or os.environ.get("JIEJING_MODEL") or os.environ.get("OPENAI_MODEL") or ""

    def configured(self) -> bool:
        return bool(self.endpoint and self.api_key and self.model)

    def generate_report(self, task: JiejingTask) -> dict[str, Any]:
        if not self.configured():
            report = self.fallback.generate_report(task)
            report["model_mode"] = "responses_model_not_configured_fallback"
            report["model_client"] = self.name
            report["model_configured"] = False
            return report
        try:
            return self._generate_live(task)
        except Exception as exc:  # pragma: no cover - live provider dependent
            report = self.fallback.generate_report(task)
            report["model_mode"] = "responses_model_error_fallback"
            report["model_client"] = self.name
            report["model_configured"] = True
            report["model_error"] = str(exc)[:500]
            return report

    def _generate_live(self, task: JiejingTask) -> dict[str, Any]:
        product = task.input.get("product") or task.context.get("sample_name") or "current product"
        sections = task.output_contract.get("required_sections", [])
        input_text = (
            "Return ONLY valid JSON with keys: merchant_readable_summary, required_sections, sections, limits.\n"
            "The sections object MUST contain one non-empty entry for every required section listed below.\n"
            "Keep unknown supplier, eBay policy, taxonomy, logistics, cost, media, and customer-service facts as 待补资料.\n"
            f"{MERCHANT_REPORT_LANGUAGE_GUARDRAIL}\n\n"
            f"Task type: {task.task_type}\n"
            f"Product: {product}\n"
            f"Merchant goal: {task.input.get('merchant_goal', '')}\n"
            f"Required sections: {json.dumps(sections, ensure_ascii=False)}\n"
            f"Agent profile: {json.dumps(task.input.get('agent_profile', {}), ensure_ascii=False)}\n"
            f"Agent instructions: {json.dumps(task.input.get('agent_instructions', {}), ensure_ascii=False)}\n"
            f"Tool permissions: {json.dumps(task.input.get('tool_permissions', []), ensure_ascii=False)}\n"
            f"Handoff contract: {json.dumps(task.input.get('handoff_contract', {}), ensure_ascii=False)}\n"
            f"Input: {json.dumps(task.input, ensure_ascii=False)}"
        )
        payload = {
            "model": self.model,
            "instructions": "你为捷境 eBay-first 商家 SaaS 写结构化经营报告。商家可见正文必须是简体中文，严格保留确认中心边界。",
            "input": input_text,
            "store": False,
        }
        request = urllib.request.Request(
            self.endpoint,
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={
                "content-type": "application/json",
                "authorization": f"Bearer {self.api_key}",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:  # pragma: no cover - live provider dependent
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"model HTTP {exc.code}: {detail[:300]}") from exc
        content = self._extract_response_text(body)
        parsed = json.loads(content)
        parsed.setdefault("sections", {})
        parsed.setdefault("limits", [])
        parsed["model_mode"] = "live_responses_model"
        parsed["model_client"] = self.name
        parsed["model_configured"] = True
        parsed["product"] = product
        parsed["task_type"] = task.task_type
        parsed["required_sections"] = sections
        parsed["_usage"] = _normalized_model_usage(body)
        return parsed

    def generate_text(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.2,
        max_output_tokens: int | None = None,
        timeout_seconds: int | None = None,
        on_text_delta: Callable[[str], None] | None = None,
    ) -> dict[str, Any]:
        if not self.configured():
            raise RuntimeError("model_client_not_configured")
        token_budget = _bounded_int(
            max_output_tokens,
            default=_env_int("JIEJING_MODEL_TEXT_MAX_TOKENS", default=900, minimum=128, maximum=4096),
            minimum=128,
            maximum=4096,
        )
        request_timeout = _bounded_int(
            timeout_seconds,
            default=self.timeout_seconds,
            minimum=1,
            maximum=max(1, self.timeout_seconds),
        )
        payload = {
            "model": self.model,
            "instructions": system_prompt,
            "input": user_prompt,
            "temperature": temperature,
            "max_output_tokens": token_budget,
            "store": False,
        }
        request = urllib.request.Request(
            self.endpoint,
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={
                "content-type": "application/json",
                "authorization": f"Bearer {self.api_key}",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=request_timeout) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:  # pragma: no cover - live provider dependent
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"model HTTP {exc.code}: {detail[:300]}") from exc
        output_text = self._extract_response_text(body).strip()
        if output_text and on_text_delta is not None:
            try:
                on_text_delta(output_text)
            except Exception:
                pass
        return {
            "text": output_text,
            "model_mode": "live_responses_model_text",
            "model_client": self.name,
            "model_configured": True,
            "model": self.model,
            "timeout_seconds": request_timeout,
            "max_output_tokens": token_budget,
            "_usage": _normalized_model_usage(body),
        }

    def _extract_response_text(self, body: dict[str, Any]) -> str:
        if isinstance(body.get("output_text"), str):
            return body["output_text"]
        for item in body.get("output", []) or []:
            if not isinstance(item, dict):
                continue
            for content in item.get("content", []) or []:
                if isinstance(content, dict) and content.get("type") in {"output_text", "text"}:
                    text = content.get("text")
                    if isinstance(text, str):
                        return text
        raise RuntimeError("Responses API returned no text output")


class DeepSeekModelClient(OpenAICompatibleModelClient):
    """DeepSeek OpenAI-compatible client for Jiejing-managed credentials.

    The key is only held in process memory. It is never returned by
    model_client_status_from_env and should never be written into frontend code
    or runtime artifacts.
    """

    name = "deepseek-openai-compatible-model"
    version = "0.1.0"

    def __init__(
        self,
        endpoint: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        timeout_seconds: int = 120,
        fallback: ModelClient | None = None,
        hermes_auth_path: str | None = None,
    ) -> None:
        if _env_truthy("JIEJING_MODEL_DISABLE_LIVE"):
            self.credential_source = "disabled_by_env"
            super().__init__(
                endpoint=endpoint or "",
                api_key="",
                model=model or os.environ.get("JIEJING_MODEL") or os.environ.get("DEEPSEEK_MODEL") or "deepseek-v4-pro",
                timeout_seconds=timeout_seconds,
                fallback=fallback,
            )
            return
        credential = self._resolve_credential(hermes_auth_path)
        base_url = (
            os.environ.get("JIEJING_DEEPSEEK_BASE_URL")
            or os.environ.get("JIEJING_MODEL_BASE_URL")
            or os.environ.get("DEEPSEEK_BASE_URL")
            or credential.get("base_url")
            or "https://api.deepseek.com"
        ).rstrip("/")
        self.credential_source = credential.get("source") or (
            "constructor" if api_key else "env" if os.environ.get("JIEJING_MODEL_API_KEY") or os.environ.get("DEEPSEEK_API_KEY") else "missing"
        )
        super().__init__(
            endpoint=endpoint or os.environ.get("JIEJING_MODEL_ENDPOINT") or f"{base_url}/chat/completions",
            api_key=api_key or os.environ.get("JIEJING_MODEL_API_KEY") or os.environ.get("DEEPSEEK_API_KEY") or credential.get("api_key") or "",
            model=model or os.environ.get("JIEJING_MODEL") or os.environ.get("DEEPSEEK_MODEL") or "deepseek-v4-pro",
            timeout_seconds=timeout_seconds,
            fallback=fallback,
        )

    def _resolve_credential(self, hermes_auth_path: str | None) -> dict[str, str]:
        if not self._legacy_hermes_model_fallback_enabled():
            return {}
        auth_path = hermes_auth_path or os.environ.get("JIEJING_HERMES_AUTH_JSON") or ""
        if auth_path:
            credential = self._credential_from_file(Path(auth_path), source=f"hermes_auth_json:{auth_path}")
            if credential:
                return credential
        if os.name != "nt":
            credential = self._credential_from_file(Path("/home/hermes/.hermes/auth.json"), source="hermes_auth_json:/home/hermes/.hermes/auth.json")
            if credential:
                return credential
        if os.name == "nt" and self._env_enabled("JIEJING_ENABLE_HERMES_WSL_SECRET_LOOKUP", default=True):
            credential = self._credential_from_wsl()
            if credential:
                return credential
        return {}

    def _legacy_hermes_model_fallback_enabled(self) -> bool:
        return self._env_enabled("JIEJING_ALLOW_HERMES_MODEL_FALLBACK", default=False)

    def _credential_from_file(self, path: Path, source: str) -> dict[str, str]:
        try:
            if not path.exists():
                return {}
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        return self._select_deepseek_credential(data, source)

    def _credential_from_wsl(self) -> dict[str, str]:
        script = r"""
import json
from pathlib import Path
path = Path('/home/hermes/.hermes/auth.json')
if not path.exists():
    raise SystemExit(0)
data = json.loads(path.read_text(encoding='utf-8'))
pool = data.get('credential_pool', {}).get('deepseek', [])
if not isinstance(pool, list):
    raise SystemExit(0)
pool = sorted([item for item in pool if isinstance(item, dict)], key=lambda item: int(item.get('priority') or 999))
for item in pool:
    token = item.get('access_token')
    if token and item.get('last_status') in {None, 'ok'}:
        print(json.dumps({'api_key': token, 'base_url': item.get('base_url') or '', 'source': item.get('source') or 'wsl_hermes_auth'}))
        break
"""
        try:
            completed = subprocess.run(
                ["wsl.exe", "-e", "python3", "-c", script],
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                timeout=8,
                check=False,
            )
        except Exception:
            return {}
        if completed.returncode != 0 or not completed.stdout.strip():
            return {}
        try:
            data = json.loads(completed.stdout.strip().splitlines()[-1])
        except Exception:
            return {}
        api_key = str(data.get("api_key") or "")
        if not api_key:
            return {}
        return {
            "api_key": api_key,
            "base_url": str(data.get("base_url") or "https://api.deepseek.com"),
            "source": f"wsl_hermes_auth:{data.get('source') or 'deepseek'}",
        }

    def _select_deepseek_credential(self, data: dict[str, Any], source: str) -> dict[str, str]:
        pool = data.get("credential_pool", {}).get("deepseek", []) if isinstance(data, dict) else []
        if not isinstance(pool, list):
            return {}
        candidates = sorted(
            [item for item in pool if isinstance(item, dict)],
            key=lambda item: int(item.get("priority") or 999),
        )
        for item in candidates:
            token = str(item.get("access_token") or "")
            if not token:
                continue
            if item.get("last_status") not in {None, "ok"}:
                continue
            return {
                "api_key": token,
                "base_url": str(item.get("base_url") or "https://api.deepseek.com"),
                "source": source,
            }
        return {}

    def _env_enabled(self, name: str, default: bool = False) -> bool:
        raw = os.environ.get(name)
        if raw is None:
            return default
        return raw.strip().lower() in {"1", "true", "yes", "on"}


def _normalized_model_usage(body: dict[str, Any]) -> dict[str, int]:
    usage = body.get("usage") if isinstance(body, dict) and isinstance(body.get("usage"), dict) else {}

    def read(*keys: str) -> int:
        for key in keys:
            if key not in usage:
                continue
            try:
                return max(0, int(usage.get(key) or 0))
            except (TypeError, ValueError):
                return 0
        return 0

    input_tokens = read("input_tokens", "prompt_tokens")
    output_tokens = read("output_tokens", "completion_tokens")
    total_tokens = read("total_tokens") or input_tokens + output_tokens
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
    }


def model_client_from_env() -> ModelClient:
    configured_provider = os.environ.get("JIEJING_MODEL_PROVIDER") or os.environ.get("JIEJING_MODEL_API_STYLE")
    if not configured_provider:
        deepseek = DeepSeekModelClient()
        if deepseek.configured():
            return deepseek
        return OpenAIResponsesModelClient()
    provider = configured_provider.strip().lower()
    if provider in {"deepseek", "deepseek-v4-pro", "ds"}:
        return DeepSeekModelClient()
    if provider in {"chat", "chat_completions", "openai_compatible", "compatible"}:
        return OpenAICompatibleModelClient()
    if provider in {"rules", "rule_based", "local"}:
        return RuleBasedModelClient()
    return OpenAIResponsesModelClient()


def model_client_status_from_env() -> dict[str, Any]:
    client = model_client_from_env()
    endpoint = getattr(client, "endpoint", "")
    parsed = urlparse(endpoint) if endpoint else None
    legacy_hermes_model_fallback_enabled = _env_truthy("JIEJING_ALLOW_HERMES_MODEL_FALLBACK")
    return {
        "client": client.name,
        "version": client.version,
        "configured": bool(getattr(client, "configured", lambda: False)()),
        "model": getattr(client, "model", "") or "",
        "endpoint_host": parsed.netloc if parsed else "",
        "endpoint_path": parsed.path if parsed else "",
        "credential_present": bool(getattr(client, "api_key", "")),
        "credential_source": getattr(client, "credential_source", None),
        "live_disabled": bool(getattr(client, "live_disabled", False)),
        "fallback": isinstance(client, (OpenAICompatibleModelClient, OpenAIResponsesModelClient))
        and not bool(getattr(client, "configured", lambda: False)()),
        "legacy_hermes_model_fallback_enabled": legacy_hermes_model_fallback_enabled,
        "secret_exposed": False,
    }
