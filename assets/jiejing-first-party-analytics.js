(function jiejingFirstPartyAnalytics() {
  "use strict";

  const visitorStorageKey = "jiejing_analytics_visitor_v1";
  const sessionStorageKey = "jiejing_analytics_session_v1";
  const sourceStorageKey = "jiejing_analytics_source_v1";
  const internalPreviewKey = "jiejing_analytics_internal_preview_until_v1";
  const internalBrowserKey = "jiejing_analytics_internal_browser_v1";
  const sourceTags = Object.freeze({"#from-douyin": "douyin", "#from-wechat": "wechat", "#from-xiaohongshu": "xiaohongshu", "#from-bilibili": "bilibili"});
  const sourceLifetimeMs = 30 * 60 * 1000;
  const sourceTagExpiresAt = Date.now() + sourceLifetimeMs;
  let sourceTagRecorded = false;
  const performanceScopes = new Set(["page_load", "settings_module"]);
  const performanceOutcomes = new Set(["success", "error"]);
  const performanceMetricKeys = new Set([
    "ttfb_ms",
    "fcp_ms",
    "lcp_ms",
    "cls_milli",
    "dom_ready_ms",
    "load_complete_ms",
    "app_shell_ready_ms",
    "duration_ms",
  ]);
  let appShellReadyMs = 0;
  let largestContentfulPaintMs = 0;
  let cumulativeLayoutShift = 0;
  let performanceSampleSent = false;
  const performanceObservers = [];
  let internalBrowserPagePause = false;
  let lastKnownInternalBrowser = false;

  // Explicit opt-out for this origin/browser only; never infer it from a merchant role.
  // Read on every event so another tab's successful set/cancel takes effect immediately.
  function getInternalBrowserStatus() {
    try {
      const persistent = window.localStorage.getItem(internalBrowserKey) === "1";
      lastKnownInternalBrowser = persistent;
      return { internal: persistent || internalBrowserPagePause, persistent, storage_available: true, page_only: internalBrowserPagePause && !persistent, error: null };
    } catch (error) {
      const paused = internalBrowserPagePause || lastKnownInternalBrowser;
      return { internal: paused, persistent: false, storage_available: false, page_only: paused, error: "storage_unavailable" };
    }
  }

  function setInternalBrowser(enabled) {
    if (typeof enabled !== "boolean") {
      return { ok: false, ...getInternalBrowserStatus(), error: "invalid_internal_browser_setting" };
    }
    if (enabled) internalBrowserPagePause = true;
    try {
      if (enabled) window.localStorage.setItem(internalBrowserKey, "1");
      else window.localStorage.removeItem(internalBrowserKey);
      const verified = getInternalBrowserStatus();
      if (!verified.storage_available || verified.persistent !== enabled) {
        return { ok: false, ...verified, error: verified.error || "storage_write_not_verified" };
      }
      internalBrowserPagePause = false;
      return { ok: true, ...verified, internal: verified.persistent, page_only: false };
    } catch (error) {
      return { ok: false, ...getInternalBrowserStatus(), error: "storage_unavailable" };
    }
  }

  function analyticsCollectionAllowed() {
    // Even explicit test mode must not bypass the browser's own persistent opt-out.
    if (getInternalBrowserStatus().internal) return false;
    if (window.__JIEJING_ANALYTICS_TEST_MODE__ === true) return true;
    if (window.location.hash === "#internal-test") {
      try { window.sessionStorage.setItem(internalPreviewKey, String(Date.now() + sourceLifetimeMs)); } catch (error) { /* No storage required for this page. */ }
      return false;
    }
    try {
      const until = Number(window.sessionStorage.getItem(internalPreviewKey));
      if (until > Date.now() && until <= Date.now() + sourceLifetimeMs) return false;
    } catch (error) { /* Storage unavailable: preserve normal collection policy. */ }
    // Automated browser traffic is excluded from live visitor totals by default.
    if (window.navigator && window.navigator.webdriver === true) return false;
    const hostname = String(window.location.hostname || "").toLowerCase();
    return !["127.0.0.1", "localhost"].includes(hostname);
  }

  function randomId() {
    if (window.crypto && typeof window.crypto.randomUUID === "function") {
      return window.crypto.randomUUID();
    }
    const bytes = new Uint8Array(16);
    if (window.crypto && typeof window.crypto.getRandomValues === "function") {
      window.crypto.getRandomValues(bytes);
      return Array.from(bytes, (value) => value.toString(16).padStart(2, "0")).join("");
    }
    return `${Date.now()}-${Math.random().toString(36).slice(2)}-${Math.random().toString(36).slice(2)}`;
  }

  function storedRandomId(storageName, key) {
    try {
      const storage = window[storageName];
      const current = String(storage.getItem(key) || "").trim();
      if (current) return current;
      const created = randomId();
      storage.setItem(key, created);
      return created;
    } catch (error) {
      return randomId();
    }
  }

  function apiBase() {
    const sources = [
      document.querySelector('meta[name="jiejing-saas-api-base"]')?.content || "",
      (() => {
        try {
          return localStorage.getItem("jiejing_saas_api_base") || "";
        } catch (error) {
          return "";
        }
      })(),
      window.location.origin,
    ];
    for (const source of sources) {
      const value = String(source || "").trim().replace(/\/+$/, "");
      if (!value) continue;
      try {
        const url = new URL(value, window.location.origin);
        if (!/^https?:$/.test(url.protocol) || url.search || url.hash) continue;
        return url.origin + url.pathname.replace(/\/+$/, "");
      } catch (error) {
        // Ignore invalid local configuration and continue with the same origin.
      }
    }
    return window.location.origin;
  }

  const visitorId = storedRandomId("localStorage", visitorStorageKey);
  const sessionId = storedRandomId("sessionStorage", sessionStorageKey);

  function currentPageKey() {
    const path = String(window.location.pathname || "").toLowerCase();
    if (path.endsWith("/app.html") || path.endsWith("app.html")) return "workbench";
    if (window.location.hash === "#pricing") return "pricing";
    return "landing";
  }

  function sourceMetadata() {
    // Only exact, predefined fragments are inspected. Never collect a query,
    // full URL or referrer. A tag is not proof of a platform referral.
    const tagged = Object.hasOwn(sourceTags, window.location.hash) ? sourceTags[window.location.hash] : "";
    try {
      if (tagged && !sourceTagRecorded) {
        window.sessionStorage.setItem(sourceStorageKey, JSON.stringify({source: tagged, expires_at: sourceTagExpiresAt}));
        sourceTagRecorded = true;
      }
      const saved = JSON.parse(window.sessionStorage.getItem(sourceStorageKey) || "null");
      if (saved && Object.values(sourceTags).includes(saved.source) && saved.expires_at > Date.now() && saved.expires_at <= Date.now() + sourceLifetimeMs) return {traffic_source: saved.source};
    } catch (error) { /* A missing/corrupt record leaves attribution unknown. */ }
    return tagged && Date.now() < sourceTagExpiresAt ? {traffic_source: tagged} : {};
  }

  function context() {
    return { visitor_id: visitorId, session_id: sessionId, event_id: randomId(), metadata: sourceMetadata() };
  }

  function track(eventKey, options) {
    if (!analyticsCollectionAllowed()) return;
    const settings = options && typeof options === "object" ? options : {};
    const payload = {
      event_key: String(eventKey || ""),
      page_key: String(settings.page_key || currentPageKey()),
      ...context(),
      metadata: { ...(settings.metadata && typeof settings.metadata === "object" ? settings.metadata : {}), traffic_source: undefined, ...sourceMetadata() },
    };
    fetch(`${apiBase()}/analytics/events`, {
      method: "POST",
      credentials: "include",
      keepalive: true,
      headers: { "content-type": "application/json" },
      body: JSON.stringify(payload),
    }).catch(() => {});
  }

  function boundedMetric(value) {
    const number = Number(value);
    if (!Number.isFinite(number) || number < 0) return null;
    return Math.min(Math.round(number), 120000);
  }

  function trackPerformance(scope, values) {
    const normalizedScope = String(scope || "").trim().toLowerCase();
    if (!performanceScopes.has(normalizedScope)) return;
    const input = values && typeof values === "object" ? values : {};
    const metadata = { performance_scope: normalizedScope };
    const outcome = String(input.outcome || "").trim().toLowerCase();
    if (performanceOutcomes.has(outcome)) metadata.outcome = outcome;
    performanceMetricKeys.forEach((key) => {
      const metric = boundedMetric(input[key]);
      if (metric !== null) metadata[key] = metric;
    });
    track("performance_sample", { metadata });
  }

  function markAppShellReady() {
    if (appShellReadyMs || !window.performance || typeof window.performance.now !== "function") return;
    appShellReadyMs = boundedMetric(window.performance.now()) || 0;
  }

  function observePerformance() {
    if (!window.performance || typeof window.PerformanceObserver !== "function") return;
    try {
      const lcpObserver = new PerformanceObserver((list) => {
        const entries = list.getEntries();
        const latest = entries[entries.length - 1];
        if (latest) largestContentfulPaintMs = boundedMetric(latest.startTime) || largestContentfulPaintMs;
      });
      lcpObserver.observe({ type: "largest-contentful-paint", buffered: true });
      performanceObservers.push(lcpObserver);
    } catch (error) {
      // Older browsers can still submit navigation and paint timing below.
    }
    try {
      const clsObserver = new PerformanceObserver((list) => {
        list.getEntries().forEach((entry) => {
          if (!entry.hadRecentInput) cumulativeLayoutShift += Number(entry.value || 0);
        });
      });
      clsObserver.observe({ type: "layout-shift", buffered: true });
      performanceObservers.push(clsObserver);
    } catch (error) {
      // Layout shift is optional and omitted when unsupported.
    }
  }

  function sendPageLoadPerformance() {
    if (performanceSampleSent || !window.performance) return;
    performanceSampleSent = true;
    performanceObservers.forEach((observer) => {
      try {
        observer.disconnect();
      } catch (error) {
        // Ignore observer cleanup failures.
      }
    });
    const navigation = window.performance.getEntriesByType("navigation")[0];
    const firstContentfulPaint = window.performance.getEntriesByName("first-contentful-paint")[0];
    const metrics = { outcome: "success" };
    if (navigation) {
      metrics.ttfb_ms = navigation.responseStart - navigation.startTime;
      metrics.dom_ready_ms = navigation.domContentLoadedEventEnd - navigation.startTime;
      metrics.load_complete_ms = navigation.loadEventEnd - navigation.startTime;
    }
    if (firstContentfulPaint) metrics.fcp_ms = firstContentfulPaint.startTime;
    if (largestContentfulPaintMs) metrics.lcp_ms = largestContentfulPaintMs;
    metrics.cls_milli = cumulativeLayoutShift * 1000;
    if (appShellReadyMs) metrics.app_shell_ready_ms = appShellReadyMs;
    trackPerformance("page_load", metrics);
  }

  function schedulePageLoadPerformance() {
    observePerformance();
    const schedule = () => window.setTimeout(sendPageLoadPerformance, 1500);
    if (document.readyState === "complete") schedule();
    else window.addEventListener("load", schedule, { once: true });
    document.addEventListener(
      "visibilitychange",
      () => {
        if (document.visibilityState === "hidden") sendPageLoadPerformance();
      },
      { once: true },
    );
  }

  window.JiejingAnalytics = Object.freeze({
    track,
    trackPerformance,
    markAppShellReady,
    context,
    currentPageKey,
    getInternalBrowserStatus,
    setInternalBrowser,
  });

  function bindEvents() {
    track("page_view");
    document.addEventListener("click", (event) => {
      const target = event.target instanceof Element ? event.target.closest("a, button") : null;
      if (!target) return;
      if (target.matches('a[href="#pricing"], [data-plan], [data-account-action="subscription"], [data-global-flow-key="billing"]')) {
        track("pricing_view", { page_key: currentPageKey() === "workbench" ? "workbench" : "pricing" });
      }
      if (target.matches('#entryRegisterSubmit, [data-saas-action="register-session"]')) {
        track("signup_started", { page_key: "register" });
      }
      if (target.matches('#entryLoginSubmit, [data-saas-action="login-session"]')) {
        track("login_started", { page_key: "login" });
      }
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bindEvents, { once: true });
  } else {
    bindEvents();
  }
  schedulePageLoadPerformance();
})();
