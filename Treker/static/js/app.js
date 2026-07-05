let winRateChart = null;
let mmrChart = null;
let currentAccountId = null;
let metaHeroes = [];
let cachedData = {};

const els = {
  input: document.getElementById("player-input"),
  searchBtn: document.getElementById("search-btn"),
  suggestions: document.getElementById("search-suggestions"),
  loading: document.getElementById("loading"),
  loadingTitle: document.getElementById("loading-title"),
  loadingSub: document.getElementById("loading-sub"),
  error: document.getElementById("error"),
  dashboard: document.getElementById("dashboard"),
  saveSnapshotBtn: document.getElementById("save-snapshot-btn"),
  snapshotStatus: document.getElementById("snapshot-status"),
  tabs: document.getElementById("tabs"),
};

document.addEventListener("DOMContentLoaded", () => {
  els.searchBtn.addEventListener("click", () => searchPlayer());
  els.input.addEventListener("keydown", (e) => e.key === "Enter" && searchPlayer());
  els.input.addEventListener(
    "input",
    debounce(async () => {
      const query = els.input.value.trim();
      if (query.length < 2 || /^\d+$/.test(query)) return hideSuggestions();
      await showSuggestions(query);
    }, 350)
  );
  els.saveSnapshotBtn.addEventListener("click", saveSnapshot);
  initTabs();
  initMetaFilters();
  loadMeta();
});

function initTabs() {
  els.tabs.querySelectorAll(".tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      els.tabs.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));
      document.querySelectorAll(".tab-panel").forEach((p) => p.classList.remove("active"));
      tab.classList.add("active");
      document.querySelector(`[data-panel="${tab.dataset.tab}"]`)?.classList.add("active");
    });
  });
}

function initMetaFilters() {
  document.querySelectorAll(".filter-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".filter-btn").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      renderMetaTable(btn.dataset.tier);
    });
  });

  document.querySelectorAll(".rank-btn").forEach((btn) => {
    btn.addEventListener("click", async () => {
      document.querySelectorAll(".rank-btn").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      await loadMeta(btn.dataset.rank);
    });
  });
}

async function searchPlayer(accountId = null) {
  hideError();
  hideSuggestions();
  showLoading(true, "Загрузка профиля...", "Подготовка анализа");

  try {
    if (!accountId) {
      const raw = els.input.value.trim();
      if (!raw) throw new Error("Введите Steam ID, ссылку или ник");
      const resolved = await fetchJson(`/api/resolve?raw=${encodeURIComponent(raw)}`);
      accountId = resolved.account_id;
    }

    currentAccountId = accountId;

    showLoading(true, "Анализ 100 матчей...", "Загрузка AI-прогноза и пати");
    const [profile, matches, analysis, party, progress] = await Promise.all([
      fetchJson(`/api/player/${accountId}`),
      fetchJson(`/api/player/${accountId}/matches?limit=100`),
      fetchJson(`/api/player/${accountId}/analysis?limit=100`),
      fetchJson(`/api/player/${accountId}/party?limit=100`),
      fetchJson(`/api/progress/${accountId}?limit=100`),
    ]);

    cachedData = { profile, matches, analysis, party, progress };
    renderDashboard();
    showLoading(false);
    els.dashboard.classList.remove("hidden");
  } catch (error) {
    showLoading(false);
    showError(error.message || "Не удалось загрузить данные");
  }
}

function renderDashboard() {
  const { profile, matches, analysis, party, progress } = cachedData;
  const p = profile.profile || {};
  const name = p.profile?.personaname || `Player ${profile.account_id}`;

  document.getElementById("player-avatar").src =
    p.profile?.avatarfull || p.profile?.avatar || "/static/img/default-avatar.svg";
  document.getElementById("player-name").textContent = name;
  document.getElementById("player-rank").textContent = profile.rank_label;
  document.getElementById("player-mmr").textContent = profile.mmr_estimate
    ? `MMR ~ ${Math.round(profile.mmr_estimate)}`
    : "MMR скрыт";
  document.getElementById("player-wl").textContent = `${profile.wl?.win || 0}W / ${profile.wl?.lose || 0}L`;
  document.getElementById("dotabuff-link").href = profile.dotabuff.profile_url;

  document.getElementById("stat-last20").textContent = `${progress.last_20_win_rate}%`;
  document.getElementById("stat-overall").textContent = `${progress.overall_win_rate}%`;
  document.getElementById("stat-matches").textContent = progress.total_analyzed;

  const streak = progress.current_streak;
  const streakEl = document.getElementById("stat-streak");
  streakEl.textContent =
    streak.type === "none" ? "—" : `${streak.count}${streak.type === "win" ? "W" : "L"}`;
  streakEl.style.color =
    streak.type === "win" ? "var(--green)" : streak.type === "loss" ? "var(--red)" : "inherit";

  renderWinRateChart(progress.points || []);
  renderMmrChart(profile.account_id, profile.mmr_estimate);
  renderOverviewSummary(analysis, party);
  renderMatchesTab(matches.matches || []);
  renderHeroesTab(profile.heroes || []);
  renderPredictionsTab(analysis);
  renderPartyTab(party);
}

function renderOverviewSummary(analysis, party) {
  const role = analysis.roles?.recommended_role;
  const pick = analysis.heroes?.recommended?.[0];
  const mate = party.peers?.play_with?.[0];

  document.getElementById("ai-summary").innerHTML = `
    <h3>AI Сводка</h3>
    <p>${escapeHtml(analysis.roles?.summary || "")}</p>
    <p>${pick ? `Лучший пик: <strong>${escapeHtml(pick.hero_name)}</strong> (${pick.win_rate}% WR, ${pick.games} игр) — ${escapeHtml(pick.recommendation)}` : ""}</p>
    <p>${mate ? `Лучший тиммейт: <strong>${escapeHtml(mate.personaname)}</strong> — ${mate.with_win_rate}% WR в ${mate.with_games} играх` : party.peers?.summary || ""}</p>
    <p class="muted">${escapeHtml(analysis.model_note || "")}</p>
  `;
}

function renderMatchesTab(matches) {
  const body = document.getElementById("matches-body");
  body.innerHTML = matches
    .map((m) => {
      const teammates = (m.teammates || [])
        .map(
          (t) => `
            <div class="teammate-chip" title="${escapeHtml(t.personaname)}">
              <img class="teammate-avatar" src="${t.avatar}" alt="${escapeHtml(t.personaname)}" />
              ${t.hero_icon ? `<img class="teammate-hero" src="${t.hero_icon}" alt="hero" />` : ""}
            </div>`
        )
        .join("");

      return `
        <tr class="${m.won ? "row-win" : "row-loss"}">
          <td class="${m.won ? "result-win" : "result-loss"}">${m.won ? "Победа" : "Поражение"}</td>
          <td>
            <div class="hero-cell">
              <img src="${m.hero_image}" alt="${escapeHtml(m.hero_name)}" />
              <span>${escapeHtml(m.hero_name)}</span>
            </div>
          </td>
          <td><span class="chip">${escapeHtml(m.role_label || m.role || "—")}</span></td>
          <td>${m.kills}/${m.deaths}/${m.assists}</td>
          <td><div class="teammates-row">${teammates || "—"}</div></td>
          <td>${formatDuration(m.duration)}</td>
          <td><a class="link-dotabuff" href="${m.dotabuff_match_url}" target="_blank" rel="noopener">DB</a></td>
        </tr>
      `;
    })
    .join("");
}

function renderHeroesTab(heroes) {
  const grid = document.getElementById("heroes-grid");
  const filtered = heroes.filter((h) => h.games >= 3).slice(0, 40);

  grid.innerHTML = filtered
    .map((h) => {
      const wrClass = h.win_rate >= 52 ? "good" : h.win_rate < 45 ? "bad" : "";
      return `
        <div class="hero-card">
          <img class="hero-portrait" src="${h.hero_image}" alt="${escapeHtml(h.hero_name)}" />
          <div>
            <strong>${escapeHtml(h.hero_name)}</strong>
            <div class="muted">${h.games} игр · ${escapeHtml(h.role_label || "")}</div>
          </div>
          <div class="wr ${wrClass}">${h.win_rate}%</div>
        </div>
      `;
    })
    .join("");
}

function renderPredictionsTab(analysis) {
  const role = analysis.roles?.recommended_role;
  const roleBox = document.getElementById("role-recommendation");

  if (role) {
    roleBox.innerHTML = `
      <strong>${escapeHtml(role.label)}</strong>
      <span>${role.win_rate}% Win Rate · ${role.games} игр · Score ${role.score}</span>
      <p class="muted">${escapeHtml(analysis.roles.summary)}</p>
    `;
  } else {
    roleBox.innerHTML = `<span class="muted">Недостаточно данных</span>`;
  }

  document.getElementById("roles-list").innerHTML = (analysis.roles?.roles || [])
    .map(
      (r) => `
      <div class="role-bar">
        <span class="chip">${escapeHtml(r.label)}</span>
        <div>
          <div class="role-bar__track"><div class="role-bar__fill" style="width:${r.win_rate}%"></div></div>
          <small class="muted">${r.games} игр · ${r.win_rate}% WR · confidence ${r.confidence}%</small>
        </div>
        <strong>${r.score}</strong>
      </div>
    `
    )
    .join("");

  document.getElementById("hero-picks").innerHTML = renderPickList(analysis.heroes?.recommended || []);
  document.getElementById("hero-avoid").innerHTML = renderPickList(analysis.heroes?.avoid || [], true);
}

function renderPickList(items, avoid = false) {
  if (!items.length) return `<p class="muted">Нет данных</p>`;
  return items
    .map(
      (h) => `
      <div class="pick-item">
        <img class="hero-icon-sm" src="${h.hero_image}" alt="${escapeHtml(h.hero_name)}" />
        <div>
          <strong>${escapeHtml(h.hero_name)}</strong>
          <div class="muted">${h.games} игр · ${h.win_rate}% WR · ${escapeHtml(h.recommendation || "")}</div>
        </div>
        <strong style="color:${avoid ? "var(--red)" : "var(--green)"}">${h.score}</strong>
      </div>
    `
    )
    .join("");
}

function renderPartyTab(party) {
  document.getElementById("party-good").innerHTML = renderPartyList(party.peers?.play_with || [], "green");
  document.getElementById("party-bad").innerHTML = renderPartyList(party.peers?.avoid || [], "red");
  document.getElementById("recent-teammates").innerHTML = renderPartyList(
    (party.recent_teammates || []).map((t) => ({
      ...t,
      with_games: t.games,
      with_win_rate: t.with_win_rate,
    })),
    "blue"
  );
}

function renderPartyList(items, tone) {
  if (!items.length) return `<p class="muted">Недостаточно данных</p>`;
  return items
    .map(
      (p) => `
      <div class="party-item">
        <img src="${p.avatar || "/static/img/default-avatar.svg"}" alt="${escapeHtml(p.personaname)}" />
        <div>
          <strong>${escapeHtml(p.personaname)}</strong>
          <div class="muted">${p.with_games || p.games} совместных игр</div>
        </div>
        <strong style="color:var(--${tone === "green" ? "green" : tone === "red" ? "red" : "accent"})">${p.with_win_rate}%</strong>
        <a class="link-dotabuff" href="${p.dotabuff_url || "#"}" target="_blank" rel="noopener">DB</a>
      </div>
    `
    )
    .join("");
}

function renderMetaTable(tierFilter = "all") {
  const body = document.getElementById("meta-body");
  const rows =
    tierFilter === "all" ? metaHeroes : metaHeroes.filter((h) => h.tier === tierFilter);

  body.innerHTML = rows
    .map(
      (h) => `
      <tr>
        <td><span class="tier tier--${h.tier}">${h.tier}</span></td>
        <td>
          <div class="hero-cell">
            <img src="${h.hero_image}" alt="${escapeHtml(h.hero_name)}" />
            <span>${escapeHtml(h.hero_name)}</span>
          </div>
        </td>
        <td><span class="chip">${escapeHtml(h.role_label)}</span></td>
        <td style="color:${h.win_rate >= 52 ? "var(--green)" : h.win_rate < 48 ? "var(--red)" : "inherit"}">${h.win_rate}%</td>
        <td>${h.pick_rate}%</td>
        <td>${h.ban_rate}%</td>
        <td>${h.pro_pick}</td>
        <td><a class="link-dotabuff" href="${h.dotabuff_url}" target="_blank" rel="noopener">DB</a></td>
      </tr>
    `
    )
    .join("");
}

async function loadMeta(rank = "all") {
  try {
    const meta = await fetchJson(`/api/meta/pro?rank=${rank}`);
    metaHeroes = meta.heroes || [];
    document.getElementById("meta-source").textContent = meta.updated_note || "OpenDota Meta";
    const activeTier = document.querySelector(".filter-btn.active")?.dataset.tier || "all";
    renderMetaTable(activeTier);
  } catch {
    document.getElementById("meta-source").textContent = "Мета недоступна";
  }
}

function renderWinRateChart(points) {
  const ctx = document.getElementById("winrate-chart");
  if (winRateChart) winRateChart.destroy();

  winRateChart = new Chart(ctx, {
    type: "line",
    data: {
      labels: points.map((p) => `#${p.index}`),
      datasets: [
        {
          label: "Win Rate %",
          data: points.map((p) => p.win_rate),
          borderColor: "#4f8cff",
          backgroundColor: "rgba(79, 140, 255, 0.1)",
          fill: true,
          tension: 0.35,
          pointRadius: 0,
        },
      ],
    },
    options: chartOptions(),
  });
}

function renderMmrChart(accountId, currentMmr) {
  const snapshots = getSnapshots(accountId);
  const ctx = document.getElementById("mmr-chart");
  const empty = document.getElementById("mmr-empty");
  if (mmrChart) mmrChart.destroy();

  if (!snapshots.length) {
    empty.classList.remove("hidden");
    return;
  }
  empty.classList.add("hidden");

  mmrChart = new Chart(ctx, {
    type: "line",
    data: {
      labels: snapshots.map((s) => new Date(s.date).toLocaleDateString("ru-RU")),
      datasets: [
        {
          label: "MMR",
          data: snapshots.map((s) => s.mmr),
          borderColor: "#f0b429",
          backgroundColor: "rgba(240, 180, 41, 0.1)",
          fill: true,
          tension: 0.25,
        },
      ],
    },
    options: chartOptions(),
  });

  els.snapshotStatus.textContent = `${snapshots.length} снимков сохранено`;
}

function saveSnapshot() {
  if (!currentAccountId) return;
  const mmrText = document.getElementById("player-mmr").textContent;
  const match = mmrText.match(/(\d+)/);
  const mmr = match ? Number(match[1]) : null;
  if (!mmr) {
    els.snapshotStatus.textContent = "MMR недоступен";
    return;
  }

  const key = snapshotKey(currentAccountId);
  const snapshots = getSnapshots(currentAccountId);
  snapshots.push({ date: new Date().toISOString(), mmr });
  localStorage.setItem(key, JSON.stringify(snapshots.slice(-30)));
  els.snapshotStatus.textContent = "Снимок сохранён";
  renderMmrChart(currentAccountId, mmr);
}

async function showSuggestions(query) {
  try {
    const data = await fetchJson(`/api/search?q=${encodeURIComponent(query)}`);
    const results = data.results || [];
    if (!results.length) return hideSuggestions();

    els.suggestions.innerHTML = results
      .map(
        (p) =>
          `<button class="suggestion-item" data-id="${p.account_id}">${escapeHtml(p.personaname || "?")} · ${p.account_id}</button>`
      )
      .join("");
    els.suggestions.classList.remove("hidden");

    els.suggestions.querySelectorAll(".suggestion-item").forEach((btn) => {
      btn.addEventListener("click", () => {
        els.input.value = btn.dataset.id;
        hideSuggestions();
        searchPlayer(Number(btn.dataset.id));
      });
    });
  } catch {
    hideSuggestions();
  }
}

function hideSuggestions() {
  els.suggestions.classList.add("hidden");
  els.suggestions.innerHTML = "";
}

function snapshotKey(id) {
  return `dota2_snapshots_${id}`;
}

function getSnapshots(id) {
  try {
    return JSON.parse(localStorage.getItem(snapshotKey(id)) || "[]");
  } catch {
    return [];
  }
}

function chartOptions() {
  return {
    responsive: true,
    plugins: { legend: { labels: { color: "#edf2ff" } } },
    scales: {
      x: { ticks: { color: "#8a96ad", maxTicksLimit: 8 }, grid: { color: "rgba(255,255,255,0.04)" } },
      y: { ticks: { color: "#8a96ad" }, grid: { color: "rgba(255,255,255,0.04)" } },
    },
  };
}

async function fetchJson(url) {
  const response = await fetch(url);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`);
  return data;
}

function showLoading(show, title = "Загрузка...", sub = "") {
  els.loading.classList.toggle("hidden", !show);
  if (show) {
    els.loadingTitle.textContent = title;
    els.loadingSub.textContent = sub;
  }
}

function showError(msg) {
  els.error.textContent = msg;
  els.error.classList.remove("hidden");
}

function hideError() {
  els.error.classList.add("hidden");
}

function formatDuration(sec) {
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

function escapeHtml(v) {
  return String(v)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function debounce(fn, delay) {
  let t;
  return (...args) => {
    clearTimeout(t);
    t = setTimeout(() => fn(...args), delay);
  };
}
