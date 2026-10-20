/* ==========================================================================
   Instafeed — frontend application
   Vanilla ES2020, no build step, no dependencies.
   ========================================================================== */
(() => {
  "use strict";

  // ---------------------------------------------------------------------
  // Small helpers
  // ---------------------------------------------------------------------
  const $ = (id) => document.getElementById(id);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

  const esc = (value) =>
    String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");

  const fmt = (n) => {
    const value = Number(n || 0);
    if (value >= 1e9) return (value / 1e9).toFixed(1).replace(/\.0$/, "") + "B";
    if (value >= 1e6) return (value / 1e6).toFixed(1).replace(/\.0$/, "") + "M";
    if (value >= 1e3) return (value / 1e3).toFixed(1).replace(/\.0$/, "") + "K";
    return String(value);
  };

  const fmtDate = (iso) => {
    if (!iso) return "";
    const date = new Date(iso);
    if (Number.isNaN(date.getTime())) return String(iso).slice(0, 10);
    return date.toLocaleDateString(undefined, {
      year: "numeric",
      month: "short",
      day: "numeric",
    });
  };

  const fmtDuration = (seconds) => {
    const total = Math.round(Number(seconds || 0));
    if (!total) return "";
    const m = Math.floor(total / 60);
    const s = total % 60;
    return `${m}:${String(s).padStart(2, "0")}`;
  };

  const store = {
    get(key, fallback = null) {
      try {
        const raw = window.localStorage.getItem(key);
        return raw === null ? fallback : JSON.parse(raw);
      } catch {
        return fallback;
      }
    },
    set(key, value) {
      try {
        window.localStorage.setItem(key, JSON.stringify(value));
      } catch {
        /* storage disabled — ignore */
      }
    },
    remove(key) {
      try {
        window.localStorage.removeItem(key);
      } catch {
        /* ignore */
      }
    },
  };

  // ---------------------------------------------------------------------
  // API client
  // ---------------------------------------------------------------------
  const TOKEN_KEY = "instafeed.token";
  const THEME_KEY = "instafeed.theme";

  const api = async (path, options = {}) => {
    const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
    const token = store.get(TOKEN_KEY);
    if (token) headers.Authorization = `Bearer ${token}`;

    const response = await fetch(path, { ...options, headers });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) {
      const error = new Error(body.detail || `Request failed (${response.status})`);
      error.status = response.status;
      throw error;
    }
    return body;
  };

  const get = (path) => api(path);
  const post = (path, payload) =>
    api(path, { method: "POST", body: JSON.stringify(payload ?? {}) });
  const del = (path) => api(path, { method: "DELETE" });

  // ---------------------------------------------------------------------
  // Toasts
  // ---------------------------------------------------------------------
  const toast = (message, kind = "") => {
    const host = $("toasts");
    const node = document.createElement("div");
    node.className = `toast${kind ? ` is-${kind}` : ""}`;
    node.innerHTML = `<span>${esc(message)}</span>`;
    host.appendChild(node);
    window.setTimeout(() => {
      node.style.opacity = "0";
      node.style.transform = "translateX(18px)";
      window.setTimeout(() => node.remove(), 260);
    }, 3400);
  };

  const setStatus = (id, message, kind = "") => {
    const node = $(id);
    if (!node) return;
    node.textContent = message || "";
    node.classList.remove("is-error", "is-success");
    if (kind) node.classList.add(`is-${kind}`);
  };

  // ---------------------------------------------------------------------
  // Application state
  // ---------------------------------------------------------------------
  const state = {
    user: null,
    view: "feed",
    sort: "new",
    page: 1,
    pageSize: 24,
    pages: 1,
    total: 0,
    search: "",
    creator: "",
    bookmarkedOnly: false,
    subscriptions: [],
    stats: {},
    currentVideoMap: {},
  };

  const VIEW_META = {
    feed: ["Feed", "Everything your subscriptions posted, in one place."],
    discover: ["Discover", "Find new creators and subscribe in one click."],
    subscriptions: ["Subscriptions", "The handles you follow and what we cached."],
    bookmarks: ["Bookmarks", "Reels you saved for later."],
    stats: ["Insights", "Your feed, quantified."],
  };

  // ---------------------------------------------------------------------
  // Theme
  // ---------------------------------------------------------------------
  const applyTheme = (theme) => {
    document.documentElement.setAttribute("data-theme", theme);
    store.set(THEME_KEY, theme);
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.setAttribute("content", theme === "dark" ? "#08080d" : "#f6f6fa");
  };

  const initTheme = () => {
    const saved = store.get(THEME_KEY);
    if (saved === "dark" || saved === "light") {
      applyTheme(saved);
      return;
    }
    const prefersDark =
      window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
    applyTheme(prefersDark ? "dark" : "light");
  };

  // ---------------------------------------------------------------------
  // Auth
  // ---------------------------------------------------------------------
  const showAuth = () => {
    $("app").hidden = true;
    $("auth").hidden = false;
    $("loginUsername").focus();
  };

  const showApp = () => {
    $("auth").hidden = true;
    $("app").hidden = false;
    $("userName").textContent = state.user?.username || "—";
    $("userHandle").textContent = state.user?.email || "@" + (state.user?.username || "");
    $("userAvatar").src =
      "https://api.dicebear.com/7.x/initials/svg?seed=" +
      encodeURIComponent(state.user?.username || "user");
  };

  const setSession = (token, user) => {
    store.set(TOKEN_KEY, token);
    state.user = user;
    showApp();
    bootstrap();
  };

  const clearSession = () => {
    store.remove(TOKEN_KEY);
    state.user = null;
    showAuth();
  };

  const handleAuthSubmit = async (mode) => {
    const statusId = "authStatus";
    setStatus(statusId, mode === "login" ? "Signing in…" : "Creating your account…");
    try {
      if (mode === "login") {
        const data = await post("/api/auth/login", {
          username: $("loginUsername").value.trim(),
          password: $("loginPassword").value,
        });
        setSession(data.token, data.user);
      } else {
        const data = await post("/api/auth/register", {
          username: $("registerUsername").value.trim(),
          email: $("registerEmail").value.trim(),
          password: $("registerPassword").value,
        });
        setSession(data.token, data.user);
      }
      setStatus(statusId, "");
      toast("Welcome to Instafeed!", "success");
    } catch (error) {
      setStatus(statusId, error.message, "error");
    }
  };

  // ---------------------------------------------------------------------
  // Rendering — feed
  // ---------------------------------------------------------------------
  const videoCard = (video) => {
    const poster = esc(video.thumbnail_url);
    const bookmarked = Number(video.bookmarked) === 1;
    const duration = fmtDuration(video.duration);
    return `
      <article class="video-card" data-video-id="${esc(video.id)}">
        <div class="video-media">
          <img class="poster" src="${poster}" alt="" loading="lazy"
               referrerpolicy="no-referrer"
               onerror="this.style.display='none'" />
          <div class="video-overlay">
            <div class="video-top">
              <button class="bookmark-btn${bookmarked ? " is-active" : ""}"
                      data-bookmark="${esc(video.id)}"
                      title="${bookmarked ? "Remove bookmark" : "Save for later"}"
                      aria-label="Bookmark">
                <svg viewBox="0 0 24 24" width="15" height="15" fill="${bookmarked ? "currentColor" : "none"}"
                     stroke="currentColor" stroke-width="2">
                  <path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"/>
                </svg>
              </button>
            </div>
            <div class="video-bottom">
              <span>${esc(video.username)}</span>
              ${duration ? `<span>· ${duration}</span>` : ""}
              <span>· ${fmt(video.views)} views</span>
            </div>
          </div>
        </div>
        <div class="video-body">
          <div class="video-owner">
            <span>${esc(video.caption || "Untitled reel")}</span>
          </div>
          <div class="video-stats">
            <span>♥ ${fmt(video.likes)}</span>
            <span>💬 ${fmt(video.comments)}</span>
            <span>${fmtDate(video.taken_at)}</span>
          </div>
        </div>
      </article>`;
  };

  const renderFeed = (videos) => {
    const grid = $("feedGrid");
    state.currentVideoMap = Object.fromEntries(
      videos.map((video) => [video.id, video]),
    );
    if (!videos.length) {
      grid.innerHTML = `
        <div class="empty" style="grid-column:1/-1">
          <strong>Nothing here yet</strong>
          Subscribe to a creator, then hit <em>Sync now</em> to pull their reels in.
        </div>`;
      return;
    }
    grid.innerHTML = videos.map(videoCard).join("");
  };

  const renderSkeleton = (count = 8) => {
    $("feedGrid").innerHTML = Array.from(
      { length: count },
      () => `<div class="skeleton"></div>`,
    ).join("");
  };

  const renderPager = () => {
    const pager = $("pager");
    if (state.pages <= 1) {
      pager.innerHTML = "";
      return;
    }
    pager.innerHTML = `
      <button class="btn btn-ghost" data-page="${state.page - 1}" ${state.page <= 1 ? "disabled" : ""}>← Prev</button>
      <span class="page-info">Page ${state.page} of ${state.pages} · ${state.total} videos</span>
      <button class="btn btn-ghost" data-page="${state.page + 1}" ${state.page >= state.pages ? "disabled" : ""}>Next →</button>`;
  };

  const loadFeed = async () => {
    renderSkeleton();
    const params = new URLSearchParams({
      page: String(state.page),
      page_size: String(state.pageSize),
      sort: state.sort,
    });
    if (state.creator) params.set("username", state.creator);
    if (state.search) params.set("q", state.search);
    if (state.bookmarkedOnly) params.set("bookmarked", "true");

    try {
      const data = await get(`/api/feed?${params.toString()}`);
      state.total = data.total;
      state.pages = data.pages;
      renderFeed(data.videos);
      renderPager();
      setStatus(
        "feedStatus",
        `${data.total} video${data.total === 1 ? "" : "s"} across ${data.subscriptions} subscription${data.subscriptions === 1 ? "" : "s"}`,
        "success",
      );
    } catch (error) {
      $("feedGrid").innerHTML = "";
      setStatus("feedStatus", error.message, "error");
    }
  };

  // ---------------------------------------------------------------------
  // Rendering — discover
  // ---------------------------------------------------------------------
  const renderSearchResults = (results) => {
    const host = $("searchResults");
    if (!results.length) {
      host.innerHTML = `<div class="empty">No creator matched that search.</div>`;
      return;
    }
    host.innerHTML = results
      .map(
        (user) => `
        <div class="user-row">
          <img src="${esc(user.profile_pic)}" alt="" loading="lazy"
               referrerpolicy="no-referrer" onerror="this.style.visibility='hidden'" />
          <div class="row-meta">
            <strong>@${esc(user.username)}
              ${user.is_verified ? '<span class="badge badge-accent">verified</span>' : ""}
              ${user.is_private ? '<span class="badge">private</span>' : ""}
            </strong>
            <small>${esc(user.full_name || "")} · ${fmt(user.followers)} followers</small>
          </div>
          <div class="row-actions">
            ${
              user.subscribed
                ? `<button class="btn btn-ghost" data-unsubscribe="${esc(user.username)}">Unsubscribe</button>`
                : `<button class="btn btn-primary" data-subscribe="${esc(user.username)}">Subscribe</button>`
            }
          </div>
        </div>`,
      )
      .join("");
  };

  const doSearch = async () => {
    const query = $("searchInput").value.trim();
    if (!query) return;
    $("searchBtn").disabled = true;
    setStatus("searchStatus", "Searching Instagram…");
    try {
      const data = await get(`/api/search?q=${encodeURIComponent(query)}`);
      renderSearchResults(data.results);
      setStatus("searchStatus", `${data.count} creator${data.count === 1 ? "" : "s"} found`, "success");
    } catch (error) {
      setStatus("searchStatus", error.message, "error");
    } finally {
      $("searchBtn").disabled = false;
    }
  };

  // ---------------------------------------------------------------------
  // Rendering — subscriptions
  // ---------------------------------------------------------------------
  const renderSubscriptions = (subs) => {
    state.subscriptions = subs;
    const host = $("subsList");
    if (!subs.length) {
      host.innerHTML = `
        <div class="empty">
          <strong>No subscriptions yet</strong>
          Head to <em>Discover</em> and subscribe to your first creator.
        </div>`;
      return;
    }
    host.innerHTML = subs
      .map(
        (sub) => `
        <div class="sub-row">
          <img src="${esc(sub.profile_pic)}" alt="" loading="lazy"
               referrerpolicy="no-referrer" onerror="this.style.visibility='hidden'" />
          <div class="row-meta">
            <strong>@${esc(sub.username)}</strong>
            <small>${fmt(sub.followers)} followers · ${sub.cached_videos} cached video${sub.cached_videos === 1 ? "" : "s"}</small>
          </div>
          <div class="row-actions">
            <button class="btn btn-ghost" data-fetch="${esc(sub.username)}">Fetch</button>
            <button class="btn btn-ghost" data-unsubscribe="${esc(sub.username)}">Unsubscribe</button>
          </div>
        </div>`,
      )
      .join("");
  };

  const loadSubscriptions = async () => {
    try {
      const data = await get("/api/subscriptions");
      renderSubscriptions(data.subscriptions);
      setStatus("subsStatus", `${data.subscriptions.length} subscription(s)`, "success");
      syncCreatorFilter();
      return data.subscriptions;
    } catch (error) {
      setStatus("subsStatus", error.message, "error");
      return [];
    }
  };

  const syncCreatorFilter = () => {
    const select = $("filterCreator");
    const current = state.creator;
    const names = Array.from(
      new Set(state.subscriptions.map((s) => s.username).concat(state.creator ? [state.creator] : [])),
    );
    select.innerHTML =
      `<option value="">All creators</option>` +
      names.map((n) => `<option value="${esc(n)}">@${esc(n)}</option>`).join("");
    select.value = current || "";
  };

  // ---------------------------------------------------------------------
  // Rendering — bookmarks
  // ---------------------------------------------------------------------
  const loadBookmarks = async () => {
    const grid = $("marksGrid");
    try {
      const data = await get("/api/bookmarks");
      if (!data.bookmarks.length) {
        grid.innerHTML = `
          <div class="empty" style="grid-column:1/-1">
            <strong>No saved reels yet</strong>
            Tap the bookmark icon on any video to keep it here.
          </div>`;
        setStatus("marksStatus", "");
        return;
      }
      grid.innerHTML = data.bookmarks
        .map((mark) => {
          const video = {
            id: mark.video_id,
            username: mark.username || "",
            caption: mark.caption || "",
            thumbnail_url: mark.thumbnail_url || "",
            video_url: mark.video_url || "",
            likes: mark.likes || 0,
            comments: 0,
            views: mark.views || 0,
            duration: 0,
            taken_at: mark.taken_at || "",
            bookmarked: 1,
          };
          state.currentVideoMap[video.id] = video;
          return videoCard(video);
        })
        .join("");
      setStatus("marksStatus", `${data.bookmarks.length} saved reel(s)`, "success");
    } catch (error) {
      grid.innerHTML = "";
      setStatus("marksStatus", error.message, "error");
    }
  };

  // ---------------------------------------------------------------------
  // Rendering — insights
  // ---------------------------------------------------------------------
  const renderInsights = (stats) => {
    state.stats = stats;
    $("iVideos").textContent = fmt(stats.videos);
    $("iViews").textContent = fmt(stats.total_views);
    $("iLikes").textContent = fmt(stats.total_likes);
    $("iComments").textContent = fmt(stats.total_comments);

    const top = stats.top_creators || [];
    const max = top.reduce((acc, row) => Math.max(acc, row.videos), 0) || 1;
    $("topCreators").innerHTML = top.length
      ? top
          .map(
            (row, index) => `
        <div class="ranking-row">
          <span class="rank">#${index + 1}</span>
          <strong>@${esc(row.username)}</strong>
          <span>${row.videos} video${row.videos === 1 ? "" : "s"} · ${fmt(row.likes)} likes</span>
          <div class="bar"><span style="width:${Math.round((row.videos / max) * 100)}%"></span></div>
        </div>`,
          )
          .join("")
      : `<div class="empty">No data yet — sync your feed first.</div>`;

    const timeline = stats.timeline || [];
    const maxDay = timeline.reduce((acc, row) => Math.max(acc, row.videos), 0) || 1;
    $("timeline").innerHTML = timeline.length
      ? timeline
          .map(
            (row) => `
        <div class="bar-col" title="${esc(row.day)}: ${row.videos} video(s)">
          <div class="bar-fill" style="height:${Math.max(4, Math.round((row.videos / maxDay) * 100))}%"></div>
          <span class="bar-label">${esc(String(row.day).slice(5))}</span>
        </div>`,
          )
          .join("")
      : `<div class="empty">Nothing captured yet.</div>`;

    const history = stats.poll_history || [];
    $("pollHistory").innerHTML = history.length
      ? history
          .map(
            (row) => `
        <div class="history-row">
          <span>${esc(fmtDate(row.ran_at))} ${esc(String(row.ran_at || "").slice(11, 19))}</span>
          <span>${row.total_new} new · ${row.checked} checked · ${row.errors} error(s) · ${row.duration_ms}ms</span>
        </div>`,
          )
          .join("")
      : `<div class="empty">The scheduler has not run yet.</div>`;
  };

  const loadStats = async () => {
    try {
      renderInsights(await get("/api/stats"));
    } catch (error) {
      toast(error.message, "error");
    }
  };

  // ---------------------------------------------------------------------
  // Actions
  // ---------------------------------------------------------------------
  const subscribe = async (username) => {
    try {
      await post("/api/subscribe", { username });
      toast(`Subscribed to @${username}`, "success");
      await loadSubscriptions();
      if ($("searchInput").value.trim()) doSearch();
    } catch (error) {
      toast(error.message, "error");
    }
  };

  const unsubscribe = async (username) => {
    try {
      await del(`/api/subscriptions/${encodeURIComponent(username)}`);
      toast(`Unsubscribed from @${username}`);
      await loadSubscriptions();
      await loadFeed();
    } catch (error) {
      toast(error.message, "error");
    }
  };

  const fetchUserVideos = async (username) => {
    setStatus("subsStatus", `Fetching every video of @${username}…`);
    try {
      const data = await get(
        `/api/subscriptions/${encodeURIComponent(username)}/videos?refresh=true`,
      );
      setStatus(
        "subsStatus",
        `@${username}: ${data.count} video(s) (${data.source})`,
        "success",
      );
      toast(`Synced ${data.count} videos from @${username}`, "success");
      await loadSubscriptions();
      await loadFeed();
    } catch (error) {
      setStatus("subsStatus", error.message, "error");
    }
  };

  const toggleBookmark = async (videoId, button) => {
    const active = button.classList.contains("is-active");
    try {
      if (active) {
        await del(`/api/bookmarks/${encodeURIComponent(videoId)}`);
        toast("Removed from bookmarks");
      } else {
        await post("/api/bookmarks", { video_id: videoId });
        toast("Saved for later", "success");
      }
      button.classList.toggle("is-active");
      const svg = button.querySelector("svg");
      if (svg) svg.setAttribute("fill", active ? "none" : "currentColor");
      await loadStats();
    } catch (error) {
      toast(error.message, "error");
    }
  };

  const runPoll = async () => {
    const button = $("pollBtn");
    button.disabled = true;
    toast("Checking every subscription for new reels…");
    try {
      const data = await post("/api/poll");
      toast(
        data.total_new
          ? `Found ${data.total_new} new reel(s) in ${(data.duration_ms / 1000).toFixed(1)}s`
          : "Everything is up to date",
        data.total_new ? "success" : "",
      );
      await loadFeed();
      await loadSubscriptions();
      await loadStats();
    } catch (error) {
      toast(error.message, "error");
    } finally {
      button.disabled = false;
    }
  };

  const exportFeed = async () => {
    try {
      const query = state.creator ? `?username=${encodeURIComponent(state.creator)}` : "";
      const response = await fetch(`/api/feed/export?format=json${query}`, {
        headers: { Authorization: `Bearer ${store.get(TOKEN_KEY) || ""}` },
      });
      if (!response.ok) throw new Error("Export failed");
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = "instafeed-feed.json";
      link.click();
      URL.revokeObjectURL(url);
      toast("Feed exported", "success");
    } catch (error) {
      toast(error.message, "error");
    }
  };

  const openLightbox = (videoId) => {
    const card = document.querySelector(`.video-card[data-video-id="${CSS.escape(videoId)}"]`);
    if (!card) return;
    const video = state.currentVideoMap?.[videoId];
    if (!video) return;
    $("lightboxBody").innerHTML = `
      <div class="lb-head">
        <img src="${esc(video.thumbnail_url)}" alt="" referrerpolicy="no-referrer" />
        <div>
          <strong>@${esc(video.username)}</strong>
          <div class="video-stats">
            <span>♥ ${fmt(video.likes)}</span>
            <span>💬 ${fmt(video.comments)}</span>
            <span>${fmt(video.views)} views</span>
            <span>${esc(fmtDate(video.taken_at))}</span>
          </div>
        </div>
      </div>
      <video controls autoplay playsinline src="${esc(video.video_url)}"></video>
      <p class="lb-caption">${esc(video.caption || "")}</p>`;
    $("lightbox").hidden = false;
    void card;
  };

  const closeLightbox = () => {
    $("lightbox").hidden = true;
    $("lightboxBody").innerHTML = "";
  };

  // ---------------------------------------------------------------------
  // Views
  // ---------------------------------------------------------------------
  const switchView = (view) => {
    state.view = view;
    $$(".nav-item[data-view]").forEach((node) =>
      node.classList.toggle("is-active", node.dataset.view === view),
    );
    $$(".view").forEach((node) => {
      node.hidden = node.dataset.view !== view;
    });
    const [title, subtitle] = VIEW_META[view] || ["Instafeed", ""];
    $("viewTitle").textContent = title;
    $("viewSubtitle").textContent = subtitle;
    $("sidebar").classList.remove("is-open");

    if (view === "feed") loadFeed();
    if (view === "subscriptions") loadSubscriptions();
    if (view === "bookmarks") loadBookmarks();
    if (view === "stats") loadStats();
  };

  const bootstrap = async () => {
    await Promise.all([loadSubscriptions(), loadFeed(), loadStats()]);
  };

  // ---------------------------------------------------------------------
  // Event wiring
  // ---------------------------------------------------------------------
  const wire = () => {
    // Auth
    $("tabLogin").addEventListener("click", () => {
      $("tabLogin").classList.add("is-active");
      $("tabRegister").classList.remove("is-active");
      $("loginForm").hidden = false;
      $("registerForm").hidden = true;
      setStatus("authStatus", "");
    });
    $("tabRegister").addEventListener("click", () => {
      $("tabRegister").classList.add("is-active");
      $("tabLogin").classList.remove("is-active");
      $("registerForm").hidden = false;
      $("loginForm").hidden = true;
      setStatus("authStatus", "");
    });
    $("loginForm").addEventListener("submit", (event) => {
      event.preventDefault();
      handleAuthSubmit("login");
    });
    $("registerForm").addEventListener("submit", (event) => {
      event.preventDefault();
      handleAuthSubmit("register");
    });
    $("logoutBtn").addEventListener("click", clearSession);

    // Navigation
    $$(".nav-item[data-view]").forEach((node) =>
      node.addEventListener("click", () => switchView(node.dataset.view)),
    );
    $("menuBtn").addEventListener("click", () =>
      $("sidebar").classList.toggle("is-open"),
    );
    $("themeToggle").addEventListener("click", () => {
      const next =
        document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark";
      applyTheme(next);
    });

    // Discover
    $("searchBtn").addEventListener("click", doSearch);
    $("searchInput").addEventListener("keydown", (event) => {
      if (event.key === "Enter") doSearch();
    });
    $("exactBtn").addEventListener("click", () => {
      const handle = $("exactInput").value.trim().replace(/^@/, "");
      if (handle) subscribe(handle);
    });
    $("exactInput").addEventListener("keydown", (event) => {
      if (event.key === "Enter") $("exactBtn").click();
    });

    // Feed controls
    $$("#sortGroup .chip").forEach((chip) =>
      chip.addEventListener("click", () => {
        $$("#sortGroup .chip").forEach((other) => other.classList.remove("is-active"));
        chip.classList.add("is-active");
        state.sort = chip.dataset.sort;
        state.page = 1;
        loadFeed();
      }),
    );
    $("filterCreator").addEventListener("change", (event) => {
      state.creator = event.target.value;
      state.page = 1;
      loadFeed();
    });
    $("bookmarkedFilter").addEventListener("change", (event) => {
      state.bookmarkedOnly = event.target.checked;
      state.page = 1;
      loadFeed();
    });
    $("exportBtn").addEventListener("click", exportFeed);
    $("pollBtn").addEventListener("click", runPoll);
    $("refreshSubsBtn").addEventListener("click", async () => {
      await loadSubscriptions();
      toast("Subscriptions refreshed");
    });

    let searchTimer = null;
    $("globalSearch").addEventListener("input", (event) => {
      window.clearTimeout(searchTimer);
      const value = event.target.value.trim();
      searchTimer = window.setTimeout(() => {
        state.search = value;
        state.page = 1;
        if (state.view !== "feed") switchView("feed");
        else loadFeed();
      }, 320);
    });

    // Delegated actions
    document.addEventListener("click", (event) => {
      const subscribeBtn = event.target.closest("[data-subscribe]");
      if (subscribeBtn) return subscribe(subscribeBtn.dataset.subscribe);

      const unsubscribeBtn = event.target.closest("[data-unsubscribe]");
      if (unsubscribeBtn) return unsubscribe(unsubscribeBtn.dataset.unsubscribe);

      const fetchBtn = event.target.closest("[data-fetch]");
      if (fetchBtn) return fetchUserVideos(fetchBtn.dataset.fetch);

      const bookmarkBtn = event.target.closest("[data-bookmark]");
      if (bookmarkBtn) {
        event.stopPropagation();
        return toggleBookmark(bookmarkBtn.dataset.bookmark, bookmarkBtn);
      }

      const pageBtn = event.target.closest("[data-page]");
      if (pageBtn && !pageBtn.disabled) {
        state.page = Number(pageBtn.dataset.page);
        loadFeed();
        window.scrollTo({ top: 0, behavior: "smooth" });
        return;
      }

      const card = event.target.closest(".video-card");
      if (card && !event.target.closest("button")) {
        openLightbox(card.dataset.videoId);
      }
    });

    $("lightboxClose").addEventListener("click", closeLightbox);
    $("lightbox").addEventListener("click", (event) => {
      if (event.target === $("lightbox")) closeLightbox();
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") closeLightbox();
      if (event.key === "/" && document.activeElement.tagName !== "INPUT") {
        event.preventDefault();
        $("globalSearch").focus();
      }
    });
  };

  // ---------------------------------------------------------------------
  // Boot
  // ---------------------------------------------------------------------
  const boot = async () => {
    initTheme();
    wire();

    const token = store.get(TOKEN_KEY);
    if (!token) {
      showAuth();
      return;
    }
    try {
      const data = await get("/api/auth/me");
      state.user = data.user;
      showApp();
      bootstrap();
    } catch {
      store.remove(TOKEN_KEY);
      showAuth();
    }
  };

  // Keep a map of the currently rendered videos so the lightbox can find them.
  window.addEventListener("DOMContentLoaded", () => {
    boot();
  });
})();
