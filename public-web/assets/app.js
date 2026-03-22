(function () {
  const state = {
    feedback: new Map(),
  };

  async function fetchJson(path) {
    const base = window.PUBLIC_APP_CONFIG.resultBaseUrl.replace(/\/$/, "");
    const response = await fetch(`${base}/${path}`);
    if (!response.ok) {
      throw new Error(`加载 ${path} 失败`);
    }
    return response.json();
  }

  function formatDate(value) {
    if (!value) {
      return "-";
    }
    return value.replace("T", " ").slice(0, 19);
  }

  function formatPrice(value) {
    return typeof value === "number" ? value.toFixed(2) : "--";
  }

  function formatAmount(value) {
    return typeof value === "number" ? value.toFixed(2) : "--";
  }

  function formatTurnoverRate(value) {
    return typeof value === "number" ? `${value.toFixed(2)}%` : "--";
  }

  function renderFeedbackCell(code) {
    const item = state.feedback.get(code) || {
      up_count: 0,
      down_count: 0,
      score: 0,
      my_vote: null,
    };
    const upActive = item.my_vote === "up" ? "vote-btn active" : "vote-btn";
    const downActive = item.my_vote === "down" ? "vote-btn active negative" : "vote-btn negative";

    return `
      <div class="feedback" data-code="${code}">
        <button class="${upActive}" data-action="up" type="button">赞 ${item.up_count}</button>
        <button class="${downActive}" data-action="down" type="button">踩 ${item.down_count}</button>
        <span class="score">分数 ${item.score}</span>
      </div>
    `;
  }

  function renderTable(tableBodyId, payload, countId, cacheTimeId) {
    const tbody = document.getElementById(tableBodyId);
    const stocks = payload.stocks || [];
    document.getElementById(countId).textContent = stocks.length;
    document.getElementById(cacheTimeId).textContent = `更新时间 ${formatDate(payload.cache_time)}，每日更新一次`;

    if (!stocks.length) {
      tbody.innerHTML = '<tr><td colspan="9" class="empty">暂无结果</td></tr>';
      return;
    }

    tbody.innerHTML = stocks.map((stock) => {
      const signal = stock.latest_signal || {};
      return `
        <tr>
          <td>${stock.code}</td>
          <td>${stock.name || ""}</td>
          <td>${stock.industry || ""}</td>
          <td>${formatPrice(stock.current_price)}</td>
          <td>${formatAmount(stock.amount)}</td>
          <td>${formatTurnoverRate(stock.turnover_rate)}</td>
          <td>${signal.direction || "-"} ${signal.type || ""}</td>
          <td>${signal.date || "-"}</td>
          <td>${renderFeedbackCell(stock.code)}</td>
        </tr>
      `;
    }).join("");
  }

  function bindVoteEvents() {
    document.body.addEventListener("click", async (event) => {
      const button = event.target.closest(".vote-btn");
      if (!button) {
        return;
      }

      const wrapper = button.closest(".feedback");
      const code = wrapper.dataset.code;
      const current = state.feedback.get(code) || {};
      const clicked = button.dataset.action;
      const action = current.my_vote === clicked ? "clear" : clicked;

      wrapper.classList.add("busy");
      try {
        const updated = await window.PublicFeedback.submitVote(code, action);
        state.feedback.set(code, updated);
        wrapper.outerHTML = renderFeedbackCell(code);
      } catch (error) {
        window.alert(error.message);
      } finally {
        const currentWrapper = document.querySelector(`.feedback[data-code="${code}"]`);
        if (currentWrapper) {
          currentWrapper.classList.remove("busy");
        }
      }
    });
  }

  async function init() {
    bindVoteEvents();

    try {
      const [manifest, buyPayload, sellPayload] = await Promise.all([
        fetchJson("manifest.json"),
        fetchJson("buy_scan_results.json"),
        fetchJson("sell_scan_results.json"),
      ]);

      document.getElementById("manifest-version").textContent = manifest.version || "-";
      document.getElementById("manifest-time").textContent = formatDate(manifest.generated_at);

      const codes = Array.from(
        new Set([...(buyPayload.stocks || []), ...(sellPayload.stocks || [])].map((item) => item.code))
      );

      try {
        state.feedback = await window.PublicFeedback.loadSummary(codes);
      } catch (error) {
        console.error(error);
        state.feedback = new Map();
      }

      renderTable("buy-table-body", buyPayload, "buy-count", "buy-cache-time");
      renderTable("sell-table-body", sellPayload, "sell-count", "sell-cache-time");
    } catch (error) {
      document.getElementById("buy-table-body").innerHTML = `<tr><td colspan="9" class="empty">${error.message}</td></tr>`;
      document.getElementById("sell-table-body").innerHTML = `<tr><td colspan="9" class="empty">${error.message}</td></tr>`;
    }
  }

  document.addEventListener("DOMContentLoaded", init);
})();
