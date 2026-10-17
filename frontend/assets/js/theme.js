// Theme picker. Loaded in <head> so the saved theme is applied before the page paints.
(function () {
  var KEY = "synapse-theme";
  var THEMES = [
    { id: "paper",    name: "Paper",    bg: "#eceeea", side: "#0f1a3a", accent: "#2748ff", color: "#0f1a3a" },
    { id: "midnight", name: "Midnight", bg: "#0c1022", side: "#080c1c", accent: "#4a6bff", color: "#080c1c" },
    { id: "aurora",   name: "Aurora",   bg: "#06161b", side: "#031013", accent: "#19d3b0", color: "#031013" },
    { id: "sunset",   name: "Sunset",   bg: "#f7ece3", side: "#3b1d33", accent: "#d93f3a", color: "#3b1d33" },
    { id: "orchid",   name: "Orchid",   bg: "#110a22", side: "#0b0618", accent: "#8450f5", color: "#0b0618" },
    { id: "forest",   name: "Forest",   bg: "#e9efe6", side: "#12301f", accent: "#1f7a4d", color: "#12301f" }
  ];

  var closeOpen = function () {};
  document.addEventListener("click", function () { closeOpen(); });

  function saved() { try { return localStorage.getItem(KEY); } catch (e) { return null; } }
  function remember(id) { try { localStorage.setItem(KEY, id); } catch (e) { /* private mode */ } }
  function find(id) { return THEMES.filter(function (t) { return t.id === id; })[0]; }
  function initial() {
    var id = saved();
    if (find(id)) return id;
    return "midnight";
  }

  function apply(id, animate) {
    var theme = find(id) || THEMES[0];
    var root = document.documentElement;
    if (animate) {
      root.classList.add("theme-anim");
      setTimeout(function () { root.classList.remove("theme-anim"); }, 400);
    }
    root.setAttribute("data-theme", theme.id);
    var meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.setAttribute("content", theme.color);
    return theme;
  }

  function swatch(theme) {
    var el = document.createElement("span");
    el.className = "swatch";
    el.style.setProperty("--sw-bg", theme.bg);
    el.style.setProperty("--sw-side", theme.side);
    el.style.setProperty("--sw-accent", theme.accent);
    el.innerHTML = "<i></i><i></i><i></i>";
    return el;
  }

  function mount() {
    var old = document.querySelector(".theme-wrap");
    if (old) old.remove();
    var side = document.querySelector(".side .me");
    var wrap = document.createElement("div");
    wrap.className = "theme-wrap " + (side ? "in-side" : "floating");

    var current = find(document.documentElement.getAttribute("data-theme")) || THEMES[0];
    var button = document.createElement("button");
    button.type = "button";
    button.className = "theme-btn";
    button.setAttribute("aria-haspopup", "true");
    button.setAttribute("aria-expanded", "false");
    button.appendChild(swatch(current));
    var label = document.createElement("span");
    label.className = "label";
    label.textContent = "Theme: " + current.name;
    button.appendChild(label);

    var pop = document.createElement("div");
    pop.className = "theme-pop";
    pop.hidden = true;
    pop.innerHTML = "<h3>Choose a theme</h3>";
    var grid = document.createElement("div");
    grid.className = "theme-grid";
    grid.setAttribute("role", "radiogroup");
    grid.setAttribute("aria-label", "Theme");
    THEMES.forEach(function (theme) {
      var option = document.createElement("button");
      option.type = "button";
      option.className = "theme-opt";
      option.setAttribute("role", "radio");
      option.setAttribute("aria-checked", String(theme.id === current.id));
      option.appendChild(swatch(theme));
      option.appendChild(document.createTextNode(theme.name));
      option.addEventListener("click", function () {
        remember(theme.id);
        apply(theme.id, true);
        mount();
        var again = document.querySelector(".theme-btn");
        if (again) again.focus();
      });
      grid.appendChild(option);
    });
    pop.appendChild(grid);

    function close() { pop.hidden = true; button.setAttribute("aria-expanded", "false"); }
    closeOpen = close;
    button.addEventListener("click", function (event) {
      event.stopPropagation();
      var open = pop.hidden;
      pop.hidden = !open;
      button.setAttribute("aria-expanded", String(open));
      if (open) grid.querySelector('[aria-checked="true"]').focus();
    });
    wrap.addEventListener("keydown", function (event) {
      if (event.key === "Escape") { close(); button.focus(); }
    });
    wrap.addEventListener("click", function (event) { event.stopPropagation(); });

    wrap.appendChild(button);
    wrap.appendChild(pop);
    if (side) side.parentNode.insertBefore(wrap, side); else document.body.appendChild(wrap);
  }

  apply(initial(), false);
  window.SynapseTheme = { mount: mount, apply: apply, themes: THEMES };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", mount); else mount();
})();
