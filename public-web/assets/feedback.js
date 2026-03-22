(function () {
  const DEVICE_KEY = "chanalyzer_device_id";

  function createDeviceId() {
    if (window.crypto && window.crypto.randomUUID) {
      return window.crypto.randomUUID();
    }
    return "dev-" + Math.random().toString(16).slice(2) + Date.now().toString(16);
  }

  function getDeviceId() {
    let deviceId = localStorage.getItem(DEVICE_KEY);
    if (!deviceId) {
      deviceId = createDeviceId();
      localStorage.setItem(DEVICE_KEY, deviceId);
    }
    return deviceId;
  }

  async function loadSummary(codes) {
    if (!codes.length) {
      return new Map();
    }

    const base = window.PUBLIC_APP_CONFIG.feedbackApiBase;
    const params = new URLSearchParams({
      codes: codes.join(","),
      device_id: getDeviceId(),
    });
    const response = await fetch(`${base}/summary?${params.toString()}`);
    if (!response.ok) {
      throw new Error("加载反馈汇总失败");
    }

    const data = await response.json();
    const summary = new Map();
    (data.items || []).forEach((item) => summary.set(item.code, item));
    return summary;
  }

  async function submitVote(code, action) {
    const base = window.PUBLIC_APP_CONFIG.feedbackApiBase;
    const response = await fetch(`${base}/vote`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        code,
        action,
        device_id: getDeviceId(),
      }),
    });
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw new Error(data.error || "提交投票失败");
    }
    return response.json();
  }

  window.PublicFeedback = {
    getDeviceId,
    loadSummary,
    submitVote,
  };
})();
