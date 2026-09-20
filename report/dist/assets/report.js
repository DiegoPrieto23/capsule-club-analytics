/* Capsule Club Analytics — comportamiento del informe.
   Dos cosas: pintar los gráficos y cambiar de modo. El modo oscuro no es un
   volteo del claro: cada figura se construye dos veces en Python, con los pasos
   oscuros de la paleta, y aquí sólo se elige cuál se pinta. */
(function () {
  "use strict";

  var KEY = "capsule-club-theme";
  var root = document.documentElement;

  function currentTheme() {
    return root.getAttribute("data-theme") === "dark" ? "dark" : "light";
  }

  function specFor(node, theme) {
    var raw = node.getAttribute("data-spec-" + theme);
    return raw ? JSON.parse(raw) : null;
  }

  var CONFIG = {
    displayModeBar: false,
    responsive: true,
    // El informe se abre con file://; sin conexión no debe intentar nada remoto.
    staticPlot: false
  };

  function draw(theme) {
    var nodes = document.querySelectorAll(".plot[data-spec-light]");
    Array.prototype.forEach.call(nodes, function (node) {
      var spec = specFor(node, theme) || specFor(node, "light");
      if (!spec) { return; }
      Plotly.react(node, spec.data, spec.layout, CONFIG);
    });
  }

  function applyTheme(theme, redraw) {
    root.setAttribute("data-theme", theme);
    try { localStorage.setItem(KEY, theme); } catch (e) { /* modo privado */ }
    if (redraw) { draw(theme); }
  }

  // El ajuste guardado gana sobre la preferencia del sistema, en los dos sentidos.
  var stored = null;
  try { stored = localStorage.getItem(KEY); } catch (e) { stored = null; }
  if (stored === "dark" || stored === "light") {
    root.setAttribute("data-theme", stored);
  } else if (window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches) {
    root.setAttribute("data-theme", "dark");
  }

  function boot() {
    draw(currentTheme());
    var toggle = document.getElementById("theme-toggle");
    if (toggle) {
      toggle.addEventListener("click", function () {
        applyTheme(currentTheme() === "dark" ? "light" : "dark", true);
      });
    }
    // Las tablas de un <details> cerrado no existen para el layout: al abrirlas
    // no hay que redibujar nada, pero al cambiar de tamaño sí.
    var resizeTimer = null;
    window.addEventListener("resize", function () {
      window.clearTimeout(resizeTimer);
      resizeTimer = window.setTimeout(function () {
        Array.prototype.forEach.call(document.querySelectorAll(".plot"), function (node) {
          if (node.data) { Plotly.Plots.resize(node); }
        });
      }, 180);
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
