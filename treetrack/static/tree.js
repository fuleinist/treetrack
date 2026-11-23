const STATUS = {
  water: ["Water now", "water"],
  wait: ["Wait for rain", "wait"],
  rain: ["Rain covered", "rain"],
  watch: ["Watch", "watch"],
  established: ["Established", "established"],
};

const SOURCE = {
  "open-meteo": "Open-Meteo, live",
  manual: "Manual reading",
};

function showError(message) {
  const box = document.getElementById("error");
  if (!message) {
    box.hidden = true;
    box.textContent = "";
    return;
  }
  box.textContent = message;
  box.hidden = false;
}

async function request(url, options = {}) {
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const type = response.headers.get("Content-Type") || "";
  const body = type.includes("application/json") ? await response.json() : await response.text();
  if (!response.ok) {
    const message = typeof body === "string" ? body : body.error || "Request failed.";
    throw new Error(message);
  }
  return body;
}

function setText(id, value) {
  const node = document.getElementById(id);
  if (node) node.textContent = value;
}

function slug() {
  const parts = window.location.pathname.split("/").filter(Boolean);
  return decodeURIComponent(parts[1] || "");
}

function relativeDate(iso) {
  if (!iso) return "never";
  const then = new Date(`${iso}T00:00:00`);
  if (Number.isNaN(then.getTime())) return iso;
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const days = Math.round((today - then) / 86400000);
  if (days <= 0) return "today";
  if (days === 1) return "yesterday";
  if (days < 30) return `${days} days ago`;
  return then.toLocaleDateString("en-AU", { day: "numeric", month: "short", year: "numeric" });
}

function shortDate(iso) {
  if (!iso) return "—";
  const value = new Date(`${iso}T00:00:00`);
  if (Number.isNaN(value.getTime())) return iso;
  return value.toLocaleDateString("en-AU", { day: "numeric", month: "short", year: "numeric" });
}

function renderTree(tree) {
  document.title = `${tree.name} — treetrack`;
  setText("tree-name", tree.name);
  setText("tree-address", tree.address || "No address");
  setText("adopter-line", tree.adopter ? `Adopted by ${tree.adopter}` : "Needs an adopter");

  document.getElementById("hero").hidden = false;
  document.getElementById("sign-link").href = `/t/${tree.slug}/sign`;
  document.getElementById("ics-link").href = `/t/${tree.slug}/reminder.ics`;

  const plan = tree.plan;
  const [label, tone] = plan ? STATUS[plan.status] || ["Ready", "none"] : ["No weather", "none"];
  const chip = document.getElementById("status-chip");
  chip.textContent = label;
  chip.className = `chip chip--${tone}`;

  if (plan) {
    setText("dose", String(Math.round(plan.dose_l)));
    setText(
      "buckets",
      plan.dose_l > 0
        ? `${plan.buckets} × ${Math.round(tree.bucket_l)} L bucket${plan.buckets === 1 ? "" : "s"} · next check ${shortDate(plan.next_check)}`
        : `No water needed · next check ${shortDate(plan.next_check)}`,
    );
    setText("reason", plan.reason);
  } else {
    setText("dose", "—");
    setText("buckets", "Weather input needed");
    setText("reason", "Enter a manual weather reading below to get this week's dose.");
  }

  document.getElementById("manual-panel").hidden = Boolean(tree.weather);

  const weather = tree.weather;
  if (weather) {
    setText("w-et0", `${Number(weather.et0_7d).toFixed(0)} mm`);
    setText("w-rain", `${Number(weather.rain_7d).toFixed(1)} mm`);
    setText("w-next", `${Number(weather.rain_next_3d).toFixed(1)} mm`);
    setText("w-credit", plan ? `${Math.round(plan.rain_credit_l)} L` : "—");
    setText("w-source", SOURCE[weather.source] || weather.source);
    const fetched = weather.fetched_at ? new Date(weather.fetched_at) : null;
    const when = fetched && !Number.isNaN(fetched.getTime())
      ? fetched.toLocaleString("en-AU", { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" })
      : "an unknown time";
    setText("w-note", `Fetched ${when}. The app keeps this reading for three hours.`);
  }

  const inputs = document.getElementById("method-inputs");
  inputs.replaceChildren();
  if (plan) {
    const rows = [
      `Species factor ${plan.species_factor}`,
      `Age factor ${plan.age_factor} at ${plan.age_years} years`,
      `Mulch factor ${plan.mulch_factor}`,
      `Demand ${Math.round(plan.demand_l)} L`,
      `Rain credit ${Math.round(plan.rain_credit_l)} L`,
      `Logged this week ${Math.round(plan.logged_l)} L`,
      `Net gap ${Math.round(plan.net_l)} L`,
    ];
    for (const text of rows) {
      const item = document.createElement("li");
      item.textContent = text;
      inputs.append(item);
    }
  }

  renderHistory(tree.waterings || []);
  const adoptInput = document.querySelector("#adopt-form [name=adopter]");
  if (adoptInput && tree.adopter) adoptInput.value = tree.adopter;
}

function renderHistory(entries) {
  const body = document.getElementById("history");
  body.replaceChildren();
  if (!entries.length) {
    const row = document.createElement("tr");
    const cell = document.createElement("td");
    cell.colSpan = 4;
    cell.className = "empty";
    cell.textContent = "No waterings logged yet.";
    row.append(cell);
    body.append(row);
    return;
  }
  for (const entry of entries) {
    const row = document.createElement("tr");
    for (const value of [
      shortDate(entry.on_date),
      `${Number(entry.litres)} L`,
      entry.by_name || "Anonymous",
      entry.note || "",
    ]) {
      const cell = document.createElement("td");
      cell.textContent = value;
      row.append(cell);
    }
    body.append(row);
  }
}

async function load() {
  try {
    const tree = await request(`/api/trees/${encodeURIComponent(slug())}`);
    showError("");
    renderTree(tree);
  } catch (error) {
    showError(`Could not load this tree. ${error.message}`);
  }
}

function setupForms(tree) {
  const waterForm = document.getElementById("water-form");
  waterForm.elements.on_date.value = new Date().toISOString().slice(0, 10);
  waterForm.elements.on_date.max = new Date().toISOString().slice(0, 10);
  waterForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const note = document.getElementById("water-note");
    note.textContent = "Saving…";
    try {
      await request(`/api/trees/${encodeURIComponent(slug())}/waterings`, {
        method: "POST",
        body: JSON.stringify(Object.fromEntries(new FormData(waterForm).entries())),
      });
      note.textContent = "Saved.";
      waterForm.reset();
      waterForm.elements.on_date.value = new Date().toISOString().slice(0, 10);
      await load();
    } catch (error) {
      note.textContent = "";
      showError(error.message);
    }
  });

  document.getElementById("adopt-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.target;
    const note = document.getElementById("adopt-note");
    note.textContent = "Saving…";
    try {
      await request(`/api/trees/${encodeURIComponent(slug())}/adopt`, {
        method: "POST",
        body: JSON.stringify(Object.fromEntries(new FormData(form).entries())),
      });
      note.textContent = "Adopted. Thank you.";
      await load();
    } catch (error) {
      note.textContent = "";
      showError(error.message);
    }
  });

  document.getElementById("manual-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.target;
    const values = Object.fromEntries(new FormData(form).entries());
    values.lat = tree.lat;
    values.lon = tree.lon;
    try {
      await request("/api/weather/manual", { method: "POST", body: JSON.stringify(values) });
      showError("");
      window.location.reload();
    } catch (error) {
      showError(error.message);
    }
  });
}

load().then(async () => {
  try {
    const tree = await request(`/api/trees/${encodeURIComponent(slug())}`);
    setupForms(tree);
  } catch (error) {
    /* the page already shows the load error */
  }
});