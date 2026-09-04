const DISPLAY_N = 20;
const LOCAL_STORAGE_KEY = "sd-rankings-tried";

// Cross-device sync uses a private GitHub Gist as storage, authenticated
// with a personal access token the user creates (scope: "gist" only) and
// pastes into the Sync panel -- see index.html. The token lives in
// localStorage on each device; that's a deterrent, not real security (same
// caveat as any client-side secret), but this is a single-user personal
// list, so it's fine.
const GH_TOKEN_KEY = "sd-rankings-gh-token";
const GH_GIST_ID_KEY = "sd-rankings-gist-id";
const GIST_FILENAME = "tried.json";

let DATA = null;
let ACTIVE_CATEGORY = null;
let TRIED = {}; // { [category]: Set<id> }

function loadLocalTried() {
  try {
    const raw = localStorage.getItem(LOCAL_STORAGE_KEY);
    const parsed = raw ? JSON.parse(raw) : {};
    const result = {};
    for (const [cat, ids] of Object.entries(parsed)) {
      result[cat] = new Set(ids);
    }
    return result;
  } catch (err) {
    return {};
  }
}

function saveLocalTried() {
  try {
    const plain = {};
    for (const [cat, ids] of Object.entries(TRIED)) {
      plain[cat] = Array.from(ids);
    }
    localStorage.setItem(LOCAL_STORAGE_KEY, JSON.stringify(plain));
  } catch (err) {
    // storage unavailable (private mode, quota, etc.) -- ignore, in-memory
    // state still works for this session
  }
}

function getSyncConfig() {
  return {
    token: localStorage.getItem(GH_TOKEN_KEY) || "",
    gistId: localStorage.getItem(GH_GIST_ID_KEY) || "",
  };
}

function setSyncConfig(token, gistId) {
  if (token) localStorage.setItem(GH_TOKEN_KEY, token);
  else localStorage.removeItem(GH_TOKEN_KEY);
  if (gistId) localStorage.setItem(GH_GIST_ID_KEY, gistId);
  else localStorage.removeItem(GH_GIST_ID_KEY);
}

async function ghRequest(path, options) {
  const { token } = getSyncConfig();
  const res = await fetch(`https://api.github.com${path}`, {
    ...options,
    headers: {
      Authorization: `token ${token}`,
      Accept: "application/vnd.github+json",
      ...(options && options.headers),
    },
  });
  if (!res.ok) throw new Error(`GitHub API HTTP ${res.status}`);
  return res.json();
}

// Creates the sync gist on first use (first device to save a token with no
// gist ID yet) and stores its ID so later persistTried calls reuse it.
// Other devices get the same ID by pasting it into the Sync panel.
async function ensureGist() {
  const { token, gistId } = getSyncConfig();
  if (!token) return null;
  if (gistId) return gistId;
  const gist = await ghRequest("/gists", {
    method: "POST",
    body: JSON.stringify({
      description: "beli-scrapper tried list (do not share this link)",
      public: false,
      files: { [GIST_FILENAME]: { content: JSON.stringify({}) } },
    }),
  });
  setSyncConfig(token, gist.id);
  return gist.id;
}

async function loadRemoteTried() {
  const { token, gistId } = getSyncConfig();
  if (!token || !gistId) return null;
  try {
    const gist = await ghRequest(`/gists/${gistId}`);
    const file = gist.files && gist.files[GIST_FILENAME];
    if (!file) return null;
    const remote = JSON.parse(file.content);
    const result = {};
    for (const [cat, ids] of Object.entries(remote)) {
      result[cat] = new Set(ids);
    }
    return result;
  } catch (err) {
    return null;
  }
}

async function persistTried() {
  saveLocalTried();
  const { token } = getSyncConfig();
  if (!token) return;
  try {
    const gistId = await ensureGist();
    if (!gistId) return;
    await ghRequest(`/gists/${gistId}`, {
      method: "PATCH",
      body: JSON.stringify({
        files: { [GIST_FILENAME]: { content: JSON.stringify(triedToPlain()) } },
      }),
    });
  } catch (err) {
    // offline or token revoked -- local state (already saved) still
    // reflects the change; it'll drift back into sync next time
    // loadRemoteTried succeeds and this device re-persists
  }
}

function triedToPlain() {
  const plain = {};
  for (const [cat, ids] of Object.entries(TRIED)) {
    plain[cat] = Array.from(ids);
  }
  return plain;
}

function updateSyncStatus(message) {
  const statusEl = document.getElementById("sync-status");
  if (!statusEl) return;
  if (message) {
    statusEl.textContent = message;
    return;
  }
  const { token, gistId } = getSyncConfig();
  statusEl.textContent = token && gistId ? "Synced across devices." : "Not set up -- only saved on this device.";
}

function setupSyncPanel() {
  const btn = document.getElementById("sync-btn");
  const panel = document.getElementById("sync-panel");
  const tokenInput = document.getElementById("sync-token");
  const gistInput = document.getElementById("sync-gist-id");
  const saveBtn = document.getElementById("sync-save");
  const closeBtn = document.getElementById("sync-close");

  const openPanel = () => {
    const { token, gistId } = getSyncConfig();
    tokenInput.value = token;
    gistInput.value = gistId;
    updateSyncStatus();
    panel.hidden = false;
  };
  const closePanel = () => {
    panel.hidden = true;
  };

  btn.addEventListener("click", openPanel);
  closeBtn.addEventListener("click", closePanel);
  panel.addEventListener("click", (e) => {
    if (e.target === panel) closePanel();
  });

  saveBtn.addEventListener("click", async () => {
    const token = tokenInput.value.trim();
    const gistId = gistInput.value.trim();
    setSyncConfig(token, gistId);
    if (!token) {
      updateSyncStatus();
      return;
    }
    updateSyncStatus("Connecting...");
    try {
      const id = await ensureGist();
      gistInput.value = id;
      const remote = await loadRemoteTried();
      if (remote) {
        for (const [cat, ids] of Object.entries(remote)) {
          if (!TRIED[cat]) TRIED[cat] = new Set();
          for (const rid of ids) TRIED[cat].add(rid);
        }
        saveLocalTried();
        renderList();
      }
      await persistTried();
      updateSyncStatus("Synced across devices.");
    } catch (err) {
      updateSyncStatus("Couldn't connect -- check the token and try again.");
    }
  });
}

async function main() {
  const statusEl = document.getElementById("status");
  const listEl = document.getElementById("restaurant-list");
  const generatedEl = document.getElementById("generated-at");
  const tabsEl = document.getElementById("tabs");

  setupSyncPanel();
  TRIED = loadLocalTried();

  try {
    const res = await fetch("./data.json", { cache: "no-store" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    DATA = await res.json();
  } catch (err) {
    statusEl.textContent = "Couldn't load ranking data. Try refreshing.";
    return;
  }

  const categoryKeys = Object.keys(DATA.categories || {});
  if (categoryKeys.length === 0) {
    statusEl.textContent = "No categories found yet.";
    return;
  }

  if (DATA.generated_at) {
    const d = new Date(DATA.generated_at);
    generatedEl.textContent = `Last updated ${d.toLocaleDateString(undefined, {
      year: "numeric",
      month: "long",
      day: "numeric",
    })}`;
  }

  for (const key of categoryKeys) {
    const btn = document.createElement("button");
    btn.className = "tab";
    btn.type = "button";
    btn.role = "tab";
    btn.textContent = DATA.categories[key].label;
    btn.addEventListener("click", () => selectCategory(key));
    btn.dataset.category = key;
    tabsEl.appendChild(btn);
  }

  statusEl.hidden = true;
  listEl.hidden = false;
  selectCategory(categoryKeys[0]);

  // reconcile with server state once it arrives (covers "tried on another
  // device" -- merge rather than overwrite so anything marked locally
  // while offline still gets pushed up next persistTried call)
  const remote = await loadRemoteTried();
  if (remote) {
    for (const [cat, ids] of Object.entries(remote)) {
      if (!TRIED[cat]) TRIED[cat] = new Set();
      for (const id of ids) TRIED[cat].add(id);
    }
    saveLocalTried();
    renderList();
  }
}

function triedSetFor(category) {
  if (!TRIED[category]) TRIED[category] = new Set();
  return TRIED[category];
}

function selectCategory(key) {
  ACTIVE_CATEGORY = key;
  const cat = DATA.categories[key];

  for (const btn of document.querySelectorAll(".tab")) {
    const active = btn.dataset.category === key;
    btn.classList.toggle("active", active);
    btn.setAttribute("aria-selected", active ? "true" : "false");
  }

  document.getElementById("category-subtitle").textContent = cat.methodology || "";
  renderList();
}

function renderList() {
  if (!ACTIVE_CATEGORY) return;
  const cat = DATA.categories[ACTIVE_CATEGORY];
  const tried = triedSetFor(ACTIVE_CATEGORY);

  const visible = cat.restaurants.filter((r) => !tried.has(r.id)).slice(0, DISPLAY_N);

  const listEl = document.getElementById("restaurant-list");
  listEl.innerHTML = "";
  visible.forEach((r, i) => listEl.appendChild(renderCard(r, i + 1)));

  const benchEl = document.getElementById("bench-note");
  if (visible.length < DISPLAY_N) {
    benchEl.textContent =
      `Only ${visible.length} candidate${visible.length === 1 ? "" : "s"} left in the ranked ` +
      `pool for this section -- re-run the scraper to refresh it.`;
    benchEl.hidden = false;
  } else {
    benchEl.hidden = true;
  }
}

function markTried(category, id, tried) {
  const set = triedSetFor(category);
  if (tried) set.add(id);
  else set.delete(id);
  persistTried();
  renderList();
}

function showUndoToast(category, id, name) {
  const toast = document.getElementById("toast");
  toast.innerHTML = "";
  toast.textContent = `Marked "${name}" as tried. `;
  const undo = document.createElement("button");
  undo.className = "toast-undo";
  undo.type = "button";
  undo.textContent = "Undo";
  undo.addEventListener("click", () => {
    markTried(category, id, false);
    toast.hidden = true;
  });
  toast.appendChild(undo);
  toast.hidden = false;
  clearTimeout(showUndoToast._t);
  showUndoToast._t = setTimeout(() => {
    toast.hidden = true;
  }, 6000);
}

function renderCard(r, displayRank) {
  const li = document.createElement("li");
  li.className = "card";

  const rankBadge = document.createElement("div");
  rankBadge.className = "rank-badge";
  rankBadge.textContent = `#${displayRank}`;
  li.appendChild(rankBadge);

  const body = document.createElement("div");
  body.className = "card-body";

  const titleRow = document.createElement("div");
  titleRow.className = "card-title-row";
  const h2 = document.createElement("h2");
  h2.textContent = r.name;
  titleRow.appendChild(h2);
  if (r.neighborhood) {
    const nb = document.createElement("span");
    nb.className = "neighborhood";
    nb.textContent = r.neighborhood;
    titleRow.appendChild(nb);
  }

  const triedLabel = document.createElement("label");
  triedLabel.className = "tried-toggle";
  const checkbox = document.createElement("input");
  checkbox.type = "checkbox";
  checkbox.addEventListener("change", () => {
    if (checkbox.checked) {
      markTried(ACTIVE_CATEGORY, r.id, true);
      showUndoToast(ACTIVE_CATEGORY, r.id, r.name);
    }
  });
  triedLabel.appendChild(checkbox);
  triedLabel.appendChild(document.createTextNode(" Tried it"));
  titleRow.appendChild(triedLabel);

  body.appendChild(titleRow);

  const badgeRow = document.createElement("div");
  badgeRow.className = "badge-row";

  if (r.yelp && r.yelp.rating != null) {
    const b = document.createElement("span");
    b.className = "badge";
    const reviewCount = r.yelp.review_count != null ? ` (${r.yelp.review_count})` : "";
    b.textContent = `★ ${r.yelp.rating}${reviewCount} Yelp`;
    badgeRow.appendChild(b);
  }
  if (r.google && r.google.rating != null) {
    const b = document.createElement("span");
    b.className = "badge";
    const reviewCount = r.google.review_count != null ? ` (${r.google.review_count})` : "";
    b.textContent = `★ ${r.google.rating}${reviewCount} Google`;
    badgeRow.appendChild(b);
  }
  if (r.yelp && r.yelp.price) {
    const b = document.createElement("span");
    b.className = "badge neutral";
    b.textContent = r.yelp.price;
    badgeRow.appendChild(b);
  }
  if (r.month) {
    const b = document.createElement("span");
    b.className = "badge neutral";
    b.textContent = r.month;
    badgeRow.appendChild(b);
  }
  if (r.permit) {
    const b = document.createElement("span");
    b.className = "badge neutral";
    b.textContent = "Licensed (SD County)";
    badgeRow.appendChild(b);
  }
  body.appendChild(badgeRow);

  if (r.blurb) {
    const p = document.createElement("p");
    p.className = "blurb";
    p.textContent = r.blurb;
    body.appendChild(p);
  }

  const linkRow = document.createElement("div");
  linkRow.className = "link-row";
  if (r.yelp && r.yelp.url) {
    const a = document.createElement("a");
    a.href = r.yelp.url;
    a.target = "_blank";
    a.rel = "noopener";
    a.textContent = "View on Yelp";
    linkRow.appendChild(a);
  }
  if (r.google && r.google.url) {
    const a = document.createElement("a");
    a.href = r.google.url;
    a.target = "_blank";
    a.rel = "noopener";
    a.textContent = "View on Google Maps";
    linkRow.appendChild(a);
  }
  for (const src of r.sources || []) {
    if (!src.url) continue;
    const a = document.createElement("a");
    a.href = src.url;
    a.target = "_blank";
    a.rel = "noopener";
    a.textContent = `Source: ${src.name}`;
    linkRow.appendChild(a);
  }
  body.appendChild(linkRow);

  li.appendChild(body);
  return li;
}

main();
