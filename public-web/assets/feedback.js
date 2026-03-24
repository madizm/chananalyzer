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

  async function loadSummary(signals) {
    if (!signals.length) {
      return new Map();
    }

    const base = window.PUBLIC_APP_CONFIG.feedbackApiBase;
    const response = await fetch(`${base}/summary`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ signals }),
    });
    if (!response.ok) {
      throw new Error("看法数据加载失败");
    }

    const data = await response.json();
    const summary = new Map();
    (data.items || []).forEach((item) => summary.set(`${item.code}::${item.signal_date}`, item));
    return summary;
  }

  async function submitVote(code, signalDate, action) {
    const base = window.PUBLIC_APP_CONFIG.feedbackApiBase;
    const response = await fetch(`${base}/vote`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        code,
        signal_date: signalDate,
        action,
        device_id: getDeviceId(),
      }),
    });
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw new Error(data.error || "提交失败，请稍后再试");
    }
    return response.json();
  }

  window.PublicFeedback = {
    getDeviceId,
    loadSummary,
    submitVote,
  };
})();
