#!/usr/bin/env python3
"""Guard eBay store/product visibility and IP screening prerequisites in the merchant UI."""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_JS = ROOT / "app.js"
STYLES = ROOT / "styles.css"


def require(text: str, needle: str, label: str) -> None:
    if needle not in text:
        raise AssertionError(f"missing {label}: {needle}")


def function_scope(source: str, name: str) -> str:
    marker = f"function {name}("
    start = source.find(marker)
    if start < 0:
        raise AssertionError(f"missing function {name}")
    next_match = re.search(r"\nfunction\s+\w+\(", source[start + len(marker) :])
    if not next_match:
        return source[start:]
    end = start + len(marker) + next_match.start()
    return source[start:end]


def main() -> None:
    app_js = APP_JS.read_text(encoding="utf-8")
    styles = STYLES.read_text(encoding="utf-8")

    product_rows_scope = function_scope(app_js, "saasListingSyncedProductRows")
    overview_scope = function_scope(app_js, "renderSaasListingStoreSyncOverview")
    ip_scope = function_scope(app_js, "renderSaasListingIpReadinessPanel")
    store_name_scope = function_scope(app_js, "saasStoreDisplayName")
    refresh_scope = function_scope(app_js, "refreshSaasState")

    for marker in [
        "hasSingleProductShape",
        "inventory_item_count",
        "offer_count",
        "eBay 官方库存摘要",
    ]:
        require(product_rows_scope, marker, "single-object inventory mapping")

    for marker in [
        "eBay 店铺同步",
        "防侵权筛查只基于 eBay 官方数据包",
        "防侵权筛查输入",
        "不能声明完成全店 IP/VeRO 筛查",
        "同步 eBay 商品",
        "商品 / offer",
        "如果只有数量没有标题/图片，IP 筛查会显示资料缺口",
    ]:
        require(overview_scope, marker, "store product sync overview")

    for marker in [
        "先看输入是否够，再谈筛查结论",
        "标题、描述、品牌、图片、类目、Item specifics、库存和 offer",
        "没有商品明细时，IP/VeRO 只能对新发布表单做预检",
        "补同步商品资料",
        "saasIpRequiredInputRows",
    ]:
        require(app_js, marker, "IP screening prerequisite copy")

    for marker in [
        "商品明细",
        "等待 SKU / 标题 / 图片",
        "waiting_for_product_data",
    ]:
        require(ip_scope, marker, "IP readiness detail")

    for marker in [
        "saasDisplayableStoreCandidate",
        "eBay 店铺：",
        "eBay 店铺已连接（等待官方名称）",
    ]:
        require(store_name_scope + app_js, marker, "merchant-visible store label")

    require(refresh_scope, "refreshedActiveStore.store_id !== store.store_id", "IP screening active-store refetch")

    for style_marker in [
        "saas-ebay-sync-overview",
        "saas-listing-ip-readiness",
        "saas-ebay-sync-overview-grid",
        "saas-listing-ip-grid",
    ]:
        require(styles, style_marker, "store product IP styling")

    print("JIEJING_EBAY_STORE_PRODUCT_IP_VISIBILITY_UI_OK")


if __name__ == "__main__":
    main()
