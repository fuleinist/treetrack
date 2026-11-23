const SPECIES = [
  ["generic", "Generic street tree"],
  ["lilly-pilly", "Lilly pilly"],
  ["jacaranda", "Jacaranda"],
  ["crepe-myrtle", "Crepe myrtle"],
  ["eucalyptus", "Eucalyptus"],
  ["plane", "London plane"],
  ["citrus", "Citrus"],
  ["fig", "Port Jackson fig"],
];

const STATUS = {
  water: ["Water now", "water"],
  wait: ["Wait for rain", "wait"],
  rain: ["Rain covered", "rain"],
  watch: ["Watch", "watch"],
  established: ["Established", "established"],
};

function h(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === null || value === undefined) continue;
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value);
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

function round(value) {
  return Math.round(Number(value) || 0);
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
  return then.toLocaleDateString("en-AU", { day: "numeric", month: "short" });
}

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

function renderStats(trees) {
  const thirsty = trees.filter((tree) => tree.plan && tree.plan.status === "water");
  const litres = thirsty.reduce((sum, tree) => sum + round(tree.plan.dose_l), 0);
  document.getElementById("stat-trees").textContent = trees.length;
  document.getElementById("stat-thirsty").textContent = thirsty.length;
  document.getElementById("stat-litres").textContent = litres;
}

function treeCard(tree) {
  const plan = tree.plan;
  const [label, tone] = plan ? STATUS[plan.status] || ["Ready", "none"] : ["No weather", "none"];
  const dose = plan ? round(plan.dose_l) : null;
  const buckets = plan ? plan.buckets : 0;
  const unit = dose === null
    ? "litres<br>needs weather"
    : `litres<br>${buckets} bucket${buckets === 1 ? "" : "s"}`;

  return h(
    "article",
    { class: "tree-card" },
    h(
      "div",
      { class: "tree-card__top" },
      h("span", { class: `chip chip--${tone}`, text: label }),
      h("span", { class: "tree-card__adopter", text: tree.adopter ? `Adopted by ${tree.adopter}` : "Needs an adopter" }),
    ),
    h("h3", {}, h("a", { href: `/t/${tree.slug}`, text: tree.name })),
    h("p", { class: "addr", text: tree.address || "No address yet" }),
    h(
      "div",
      { class: "dose" },
      h("span", { class: "dose__num", text: dose === null ? "—" : String(dose) }),
      h("span", { class: "dose__unit", html: unit }),
    ),
    h("p", {
      class: "reason",
      text: plan ? plan.reason : "Weather is unavailable. Open the tree to enter a manual reading.",
    }),
    h(
      "div",
      { class: "card-meta" },
      h("span", { text: tree.last_watered ? `Last watered ${relativeDate(tree.last_watered)}` : "Never watered" }),
      h("span", { text: `${round(tree.litres_7d)} L in the last 7 days` }),
      h("span", { text: `${tree.watering_count || 0} watering${(tree.watering_count || 0) === 1 ? "" : "s"}` }),
    ),
  );
}

function render(trees) {
  renderStats(trees);
  const grid = document.getElementById("trees");
  grid.replaceChildren();
  if (!trees.length) {
    grid.append(
      h(
        "div",
        { class: "panel empty" },
        h("h2", { text: "No trees yet" }),
        h("p", { text: "Add the first tree on your street. The dose takes about a minute." }),
      ),
    );
    return;
  }
  for (const tree of trees) grid.append(treeCard(tree));
}

async function load() {
  try {
    const data = await request("/api/trees");
    showError("");
    render(data.trees || []);
  } catch (error) {
    showError(`Could not load the trees. ${error.message}`);
  }
}

function fillSpecies() {
  const select = document.getElementById("species-select");
  for (const [value, label] of SPECIES) {
    select.append(h("option", { value, text: label }));
  }
}

function setupForms() {
  const form = document.getElementById("tree-form");
  const planted = form.elements.planted_on;
  const past = new Date();
  past.setDate(past.getDate() - 200);
  planted.value = past.toISOString().slice(0, 10);
  planted.max = new Date().toISOString().slice(0, 10);

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const note = document.getElementById("form-note");
    note.textContent = "Saving…";
    const payload = Object.fromEntries(new FormData(form).entries());
    try {
      const tree = await request("/api/trees", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      showError("");
      window.location.href = `/t/${tree.slug}`;
    } catch (error) {
      note.textContent = "Weather comes from Open-Meteo for these coordinates.";
      showError(error.message);
    }
  });

  document.getElementById("add-panel").addEventListener("toggle", (event) => {
    if (event.target.open) form.scrollIntoView({ behavior: "smooth", block: "nearest" });
  });
}

fillSpecies();
setupForms();
load();