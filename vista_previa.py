"""Vista previa de la pantalla lectora para la página Apariencia.

Usa los MISMOS archivos que los equipos (docs/index.html, docs/estilos.css y docs/pantalla.js),
así que lo que se ve aquí es lo que se verá en los verificadores, a la resolución elegida.
No depende de que GitHub Pages esté actualizado.
"""
import base64
import json
import re
from functools import lru_cache
from pathlib import Path

DOCS = Path(__file__).resolve().parent / "docs"

RESOLUCIONES = {
    "Verificador 2connect · 1024×600": (1024, 600),
    "Pantalla pequeña · 800×480": (800, 480),
    "Tableta · 1280×800": (1280, 800),
    "PC o TV Full HD · 1920×1080": (1920, 1080),
    "Vertical · 1080×1920": (1080, 1920),
}
PANTALLAS = {"espera": "Esperando", "producto": "Precio", "no": "No encontrado"}
PRODUCTO_DEMO = ["7460000000017", "Café molido tradicional 1 lb", 289.95]


@lru_cache(maxsize=1)
def _plantilla():
    """index.html sin scripts ni enlaces externos, con el CSS en línea (fuente aparte)."""
    html = (DOCS / "index.html").read_text(encoding="utf-8")
    css = (DOCS / "estilos.css").read_text(encoding="utf-8")
    css = css.replace('url("fuentes/Sora.ttf")', 'url("__FUENTE__")')
    html = re.sub(r"<script\b[^>]*>.*?</script>\s*", "", html, flags=re.S)
    html = re.sub(r"<link\b[^>]*>\s*", "", html)
    html = html.replace("</head>", f"<style>{css}</style>\n</head>")
    pantalla = (DOCS / "pantalla.js").read_text(encoding="utf-8")
    conductor = """
<script>
(function () {
  var D = window.frameElement && window.frameElement.__vista;
  if (!D) return;
  document.body.classList.add("vista-previa");
  Pantalla.aplicar(D.apariencia, { logo: D.logo, qr: D.qr });
  if (D.pantalla === "producto") Pantalla.producto(D.producto, D.producto[0], 10);
  else Pantalla.espera(D.pantalla === "no", D.producto[0]);
  document.getElementById("estado-red").textContent = "En línea";
})();
</script>"""
    html = html.replace("</body>", f"<script>{pantalla}</script>{conductor}\n</body>")
    return html


@lru_cache(maxsize=1)
def _fuente_b64():
    try:
        return base64.b64encode((DOCS / "fuentes" / "Sora.ttf").read_bytes()).decode("ascii")
    except OSError:
        return ""


def _data_url(datos):
    return ("data:image/png;base64," + base64.b64encode(datos).decode("ascii")) if datos else None


def componente(vistas, logo=None, qr=None, columnas=1, alto_max=420, producto=None):
    """HTML para st.components.v1.html con una o varias pantallas a escala.

    vistas: lista de dicts {apariencia, pantalla, ancho, alto, titulo?}.
    Devuelve (html, alto_sugerido_px)."""
    datos = {
        "plantilla": _plantilla(),
        "fuente": _fuente_b64(),
        "logo": _data_url(logo),
        "qr": _data_url(qr),
        "producto": list(producto or PRODUCTO_DEMO),
        "vistas": vistas,
        "columnas": max(1, int(columnas)),
        "altoMax": int(alto_max),
    }
    filas = -(-len(vistas) // datos["columnas"])
    con_titulo = any(v.get("titulo") for v in vistas)
    alto = filas * (alto_max + (30 if con_titulo else 0) + 14) + 6
    carga = json.dumps(datos, ensure_ascii=False).replace("</", "<\\/")
    html = """<!doctype html><html><head><meta charset="utf-8"><style>
  html,body{margin:0;background:transparent;font-family:"Source Sans Pro",system-ui,sans-serif}
  .rejilla{display:grid;gap:14px;align-items:start}
  .celda{display:flex;flex-direction:column;align-items:center;gap:8px;min-width:0}
  .marco{position:relative;overflow:hidden;border-radius:10px;border:1px solid #d5dce6;
         box-shadow:0 6px 20px rgba(15,36,64,.10);background:#fff}
  .marco iframe{position:absolute;left:0;top:0;border:0;transform-origin:0 0;pointer-events:none}
  .titulo{font-size:14px;color:#31415a;font-weight:600}
</style></head><body><div class="rejilla" id="r"></div>
<script>
(function(){
  var D = __DATOS__;
  var fuente = "";
  try {
    var b = atob(D.fuente), u = new Uint8Array(b.length);
    for (var i = 0; i < b.length; i++) u[i] = b.charCodeAt(i);
    fuente = URL.createObjectURL(new Blob([u], {type: "font/ttf"}));
  } catch (e) {}
  var doc = D.plantilla.replace("__FUENTE__", fuente);
  var r = document.getElementById("r");
  r.style.gridTemplateColumns = "repeat(" + D.columnas + ", minmax(0, 1fr))";
  var celdas = D.vistas.map(function (v) {
    var c = document.createElement("div"); c.className = "celda";
    var m = document.createElement("div"); m.className = "marco";
    var f = document.createElement("iframe");
    f.width = v.ancho; f.height = v.alto; f.title = v.titulo || "Vista previa";
    f.__vista = {apariencia: v.apariencia, pantalla: v.pantalla, logo: D.logo, qr: D.qr, producto: D.producto};
    f.srcdoc = doc;
    m.appendChild(f); c.appendChild(m);
    if (v.titulo) { var t = document.createElement("div"); t.className = "titulo"; t.textContent = v.titulo; c.appendChild(t); }
    r.appendChild(c);
    return {c: c, m: m, f: f, v: v};
  });
  function medir() {
    celdas.forEach(function (x) {
      var esc = Math.min(x.c.clientWidth / x.v.ancho, D.altoMax / x.v.alto, 1);
      x.m.style.width = Math.floor(x.v.ancho * esc) + "px";
      x.m.style.height = Math.floor(x.v.alto * esc) + "px";
      x.f.style.transform = "scale(" + esc + ")";
    });
  }
  medir();
  window.addEventListener("resize", medir);
})();
</script></body></html>"""
    return html.replace("__DATOS__", carga), alto
