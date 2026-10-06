
const $ = (id) => document.getElementById(id);
const api = async (path, opts = {}) => {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.detail || `HTTP ${res.status}`);
  return body;
};
const fmt = (n) =>
  n >= 1e6 ? (n / 1e6).toFixed(1) + "M" : n >= 1e3 ? (n / 1e3).toFixed(1) + "K" : String(n ?? 0);

async function doSearch() {
  const q = $("searchInput").value.trim();
  if (!q) return;
  $("searchBtn").disabled = true;
  $("searchStatus").textContent = "Searching…";
  $("searchStatus").classList.remove("error");
  try {
    const data = await api(`/api/search?q=${encodeURIComponent(q)}`);
    $("searchStatus").textContent = `${data.count} result(s)`;
    $("searchResults").innerHTML = data.results
      .map(
        (u) => `
      <div class="user-row">
        <img src="${esc(u.profile_pic)}" alt="" referrerpolicy="no-referrer"
             onerror="this.style.visibility='hidden'"/>
        <div class="meta">
          <div class="uname">@${esc(u.username)} ${u.is_verified ? "✔️" : ""}</div>
          <div class="fname">${esc(u.full_name)} · ${fmt(u.followers)} followers
            ${u.is_private ? "· 🔒 private" : ""}</div>
        </div>
        ${
          u.subscribed
            ? `<button class="small secondary" disabled>Subscribed ✓</button>`
            : `<button class="small" onclick="subscribe('${esc(u.username)}')">Subscribe</button>`
        }
      </div>`
      )
      .join("");
  } catch (e) {
    $("searchStatus").textContent = e.message;
    $("searchStatus").classList.add("error");
  } finally {
    $("searchBtn").disabled = false;
  }
}
async function subscribe(username) {
  try {
    await api("/api/subscribe", {
      method: "POST",
      body: JSON.stringify({ username }),
    });
    await loadSubscriptions();
    doSearch();
    } catch (e) {
      alert("Subscribe failed: " + e.message);
    }
  }

async function unsubscribe(username) {
  await api(`/api/subscriptions/${encodeURIComponent(username)}`, { method: "DELETE" });
  await loadSubscriptions();
  loadFeed(false);
}

async function loadSubscriptions() {
  const { subscriptions } = await api("/api/subscriptions");
  $("subsList").innerHTML = subscriptions.length
    ? subscriptions
        .map(
          (s) => `
      <div class="sub-row">
        <img src="${esc(s.profile_pic)}" referrerpolicy="no-referrer"
             onerror="this.style.visibility='hidden'"/>
        <div class="meta">
          <div class="uname">@${esc(s.username)}</div>
          <div class="count">${fmt(s.followers)} followers · ${s.cached_videos} cached videos</div>
        </div>
        <button class="small" onclick="loadUserVideos('${esc(s.username)}')">Get videos</button>
        <button class="small secondary" onclick="unsubscribe('${esc(s.username)}')">✕</button>
      </div>`
        )
        .join("")
    : `<div class="empty">No subscriptions yet — search a handle above.</div>`;
}

async function loadUserVideos(username) {
  $("feedStatus").textContent = `Fetching every video of @${username}… (large profiles can take a while)`;
  $("feedStatus").classList.remove("error");
  try {
    const data = await api(
      `/api/subscriptions/${encodeURIComponent(username)}/videos`
    );
    $("feedStatus").textContent = `${data.count} videos from @${username} (${data.source})`;
    renderFeed(data.videos);
    loadSubscriptions();
  } catch (e) {
    $("feedStatus").textContent = e.message;
    $("feedStatus").classList.add("error");
  }
}

async function loadFeed(refresh) {
  $("feedStatus").textContent = refresh
    ? "Refreshing all subscriptions from Instagram…"
    : "Loading cached feed…";
  try {
    const data = await api(`/api/feed${refresh ? "?refresh=true" : ""}`);
    $("feedStatus").textContent = `${data.count} videos across ${data.subscriptions} subscription(s)`;
    renderFeed(data.videos);
  } catch (e) {
    $("feedStatus").textContent = e.message;
    $("feedStatus").classList.add("error");
  }
}
