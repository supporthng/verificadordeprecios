"""Pantalla lectora de la Consulta en línea (Streamlit), con el MISMO diseño que los equipos
sin internet (docs/estilos.css + docs/pantalla.js): estilos, color, textos, logo, nombre,
QR y foto del producto según Apariencia.

Se dibuja con st.markdown (no en un iframe) para no tocar el cuadro del escáner ni su
mecanismo de enfoque. Todas las reglas van dentro de .vp para no afectar al resto de la app.
"""
import html

TINTA, BLANCO = "#0f2440", "#ffffff"
FONDO = {"claro": "#ffffff", "noche": "#10213d", "etiqueta": "#ffffff"}
FUENTE = "https://supporthng.github.io/verificadordeprecios/fuentes/Sora.ttf"


# ---------------------------------------------------------------- colores (igual que pantalla.js)
def _rgb(h):
    n = int(h[1:], 16)
    return [(n >> 16) & 255, (n >> 8) & 255, n & 255]


def _hex(c):
    return "#" + "".join(f"{round(v):02x}" for v in c)


def _lum(h):
    def canal(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (canal(v) for v in _rgb(h))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contraste(a, b):
    x, y = _lum(a), _lum(b)
    return (max(x, y) + 0.05) / (min(x, y) + 0.05)


def _mezclar(a, b, t):
    x, y = _rgb(a), _rgb(b)
    return _hex([x[i] + (y[i] - x[i]) * t for i in range(3)])


def legible(color, fondo, minimo):
    hacia = TINTA if _lum(fondo) > 0.4 else BLANCO
    for paso in range(4):
        c = _mezclar(color, hacia, paso * 0.05)
        if contraste(c, fondo) >= minimo:
            return c
    return hacia


def _sobre(fondo):
    return BLANCO if contraste(BLANCO, fondo) >= contraste(TINTA, fondo) else TINTA


def variables(a):
    e, marca = a["estilo"], a["color_marca"]
    fondo = marca if e == "marca" else FONDO.get(e, BLANCO)
    tinta = _sobre(marca) if e == "marca" else ("#f3f6fb" if e == "noche" else TINTA)
    gris = _mezclar(tinta, fondo, 0.3) if e == "marca" else ("#9fb0c8" if e == "noche" else "#6b7a90")
    linea = _mezclar(tinta, fondo, 0.78) if e == "marca" else ("#24395c" if e == "noche" else "#e6ebf2")
    precio = tinta if e == "marca" else (TINTA if e == "etiqueta" else legible(marca, fondo, 4.5 if e == "noche" else 3))
    acento = tinta if e == "marca" else legible(marca, fondo, 2.2)
    return {"--marca": marca, "--sobre-marca": _sobre(marca), "--papel": fondo, "--tinta": tinta,
            "--gris": gris, "--linea": linea, "--precio": precio, "--acento": acento,
            "--alerta": "#ff7b70" if e == "noche" else "#d92d20"}


# ---------------------------------------------------------------- piezas
def _img(src, clase, alt=""):
    return f'<img class="{clase}" alt="{html.escape(alt)}" src="{src}">' if src else ""


def _cabecera(clase, logo, nombre, clase_logo):
    if not (logo or nombre):
        return ""
    return (f'<header class="{clase}">{_img(logo, clase_logo, "Logo de la tienda")}'
            + (f'<span>{html.escape(nombre)}</span>' if nombre else "") + "</header>")


def pantalla(a, estado, logo=None, qr=None, foto=None, producto=None, codigo="", pista=None,
             fija=False, segundos=10):
    """HTML de la pantalla. estado: espera | no | buscando | error | producto.
    logo, qr y foto: direcciones (data:…) o None. producto: {name, price}."""
    e = a["estilo"]
    panel = e == "panel"
    nombre = a["nombre_negocio"].strip() if a["mostrar_nombre"] else ""
    logo = logo if a["mostrar_logo"] else None
    qr = qr if a["mostrar_qr"] else None
    foto = foto if a.get("mostrar_foto", True) else None
    centro = a["posicion_logo"] == "centro" and not panel
    clases = ["vp", f"estilo-{e}", "logo-centro" if centro else "logo-esquina"]
    if fija:
        clases.append("fija")
    if not logo:
        clases.append("sin-logo")
    estilo = ";".join(f"{k}:{v}" for k, v in variables(a).items())

    partes = []
    if panel:
        partes.append('<aside class="vp-panel"><div class="vp-panel-marca">'
                      + _img(logo, "vp-panel-logo", "Logo de la tienda")
                      + (f'<p class="vp-panel-nombre">{html.escape(nombre)}</p>' if nombre else "")
                      + "</div>"
                      + (f'<figure class="vp-panel-qr"><img alt="Código QR" src="{qr}">'
                         f'<figcaption>{html.escape(a["texto_qr"])}</figcaption></figure>' if qr else "")
                      + "</aside>")

    if estado == "producto" and producto is not None:
        try:
            entero, centavos = f"{float(producto.get('price') or 0):,.2f}".split(".")
        except (TypeError, ValueError):
            entero, centavos = "0", "00"
        cuerpo = (
            ("" if panel else _cabecera("vp-rcab", logo, nombre, "vp-rcab-logo"))
            + (f'<figure class="vp-foto"><img alt="" src="{foto}"></figure>' if foto else "")
            + '<div class="vp-prod">'
            f'<p class="vp-nombre">{html.escape(str(producto.get("name") or ""))}</p>'
            f'<p class="vp-codigo">Código <span>{html.escape(codigo)}</span></p></div>'
            f'<p class="vp-etiqueta" aria-label="Precio"><span class="vp-moneda">{html.escape(a["moneda"])}</span>'
            f'<span class="vp-entero">{entero}</span><span class="vp-centavos">{centavos}</span></p>'
            f'<div class="vp-cuenta"><span style="animation-duration:{int(segundos)}s"></span></div>'
        )
        partes.append(f'<section class="vp-main vp-resultado{" con-foto" if foto else ""}">{cuerpo}</section>')
    else:
        alerta = estado in ("no", "error")
        if estado == "no":
            titulo = "No encontramos este producto"
            texto = (f'Código <strong>{html.escape(codigo)}</strong>. Consulta el precio en caja.')
        elif estado == "error":
            titulo = "No pudimos consultar el precio"
            texto = html.escape(pista or "Consulta el precio en caja.")
        elif estado == "buscando":
            titulo, texto = "Buscando el precio…", "Un momento, por favor."
        else:
            titulo, texto = html.escape(a["titulo_espera"]), html.escape(a["mensaje_espera"])
        cuerpo = (
            ("" if panel else _cabecera("vp-cab", logo, nombre, "vp-cab-logo"))
            + '<div class="vp-centro">'
            f'<h1 class="vp-titulo{" alerta" if alerta else ""}">{titulo}</h1>'
            f'<div class="vp-laser{" detenido" if alerta else ""}"><span></span></div>'
            f'<p class="vp-pista">{texto}</p></div>'
            + (f'<aside class="vp-qr"><span>{html.escape(a["texto_qr"])}</span><img alt="Código QR" src="{qr}"></aside>'
               if qr and not panel else "")
        )
        partes.append(f'<section class="vp-main vp-espera">{cuerpo}</section>')
    if e == "etiqueta":
        partes.append('<div class="vp-riel"></div>')
    return f'<div class="{" ".join(clases)}" style="{estilo}">{"".join(partes)}</div>'


CSS = """
<style>
@font-face { font-family: "Sora"; src: url("%s") format("truetype"); font-weight: 100 800; font-display: swap; }
.vp {
  --margen: clamp(16px, 3.6vmin, 60px);
  position: relative; display: flex; width: 100%%; box-sizing: border-box; overflow: hidden;
  height: calc(100dvh - 5.5rem); min-height: 420px; border-radius: 18px;
  background: var(--papel); color: var(--tinta);
  font-family: "Sora", "Segoe UI", Roboto, Arial, sans-serif; font-variant-numeric: tabular-nums;
  box-shadow: 0 1px 0 var(--linea), 0 10px 30px rgba(15, 36, 64, .06);
}
.vp.fija { position: fixed; inset: 0; z-index: 50; height: auto; min-height: 0; border-radius: 0; box-shadow: none; }
.vp * { box-sizing: border-box; }
.vp p, .vp h1, .vp figure { margin: 0; }
.vp-main { flex: 1 1 auto; min-width: 0; display: grid; padding: var(--margen); position: relative; }

/* ---- espera ---- */
.vp-espera { grid-template-rows: auto 1fr auto; }
.vp-cab { grid-row: 1; justify-self: start; display: flex; align-items: center; gap: clamp(10px, 2.4vmin, 22px); min-width: 0; max-width: 100%%; }
.vp-cab-logo { display: block; max-height: clamp(40px, 12vh, 150px); max-width: 30vw; object-fit: contain; }
.vp-cab span { font-weight: 700; letter-spacing: -.015em; line-height: 1.1; font-size: clamp(18px, 3.6vmin, 48px);
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.vp.sin-logo .vp-cab span { font-size: clamp(20px, 4.4vmin, 58px); }
.vp-centro { grid-row: 2; align-self: center; justify-self: center; width: min(1300px, 100%%); text-align: center; }
.vp-titulo { font-weight: 600; letter-spacing: -.02em; line-height: 1.05; text-wrap: balance;
  font-size: clamp(28px, 8vmin, 106px); padding: 0 !important; color: var(--tinta); font-family: inherit; }
.vp-titulo.alerta { color: var(--alerta); }
.vp.estilo-marca .vp-titulo.alerta { color: var(--tinta); }
.vp-pista { margin-top: clamp(12px, 3vh, 28px) !important; color: var(--gris); font-size: clamp(15px, 3vmin, 34px); text-wrap: balance; }
.vp-pista strong { color: var(--tinta); font-weight: 600; letter-spacing: .03em; }
.vp.logo-centro .vp-espera { grid-template-rows: 1fr auto auto 1fr auto; }
.vp.logo-centro .vp-cab { grid-row: 2; justify-self: center; flex-direction: column; text-align: center; }
.vp.logo-centro .vp-cab-logo { max-height: clamp(60px, 22vh, 320px); max-width: 60vw; }
.vp.logo-centro .vp-cab span { color: var(--gris); font-size: clamp(18px, 3.8vmin, 52px); white-space: normal; }
.vp.logo-centro .vp-centro { grid-row: 3; margin-top: clamp(18px, 6vh, 60px); }
.vp.logo-centro .vp-titulo { font-size: clamp(26px, 6.4vmin, 88px); }
.vp.logo-centro .vp-qr { grid-row: 5; }
.vp-laser { position: relative; height: 2px; margin: clamp(20px, 5.5vh, 52px) auto 0; width: min(900px, 78%%); background: var(--linea); border-radius: 1px; }
.vp-laser span { position: absolute; top: -1px; left: 0; height: 4px; width: 22%%; border-radius: 2px;
  background: #ff7a1a; box-shadow: 0 0 14px 2px rgba(255, 122, 26, .55);
  animation: vp-barrido 2.6s cubic-bezier(.45, 0, .55, 1) infinite alternate; }
.vp.estilo-marca .vp-laser span { background: var(--tinta); box-shadow: 0 0 12px 1px var(--tinta); }
.vp-laser.detenido { background: transparent; }
.vp-laser.detenido span { animation: none; width: 100%%; background: var(--alerta); box-shadow: none; height: 3px; }
.vp.estilo-marca .vp-laser.detenido span { background: var(--tinta); opacity: .55; }
@keyframes vp-barrido { from { left: 0; } to { left: 78%%; } }
.vp-qr { grid-row: 3; justify-self: end; display: flex; align-items: center; gap: 14px; color: var(--gris);
  font-size: clamp(12px, 2.2vmin, 24px); line-height: 1.3; text-align: right; }
.vp-qr span { max-width: 15ch; }
.vp-qr img { display: block; width: clamp(70px, 16vmin, 200px); height: auto; border-radius: 10px; padding: 6px; background: #fff; border: 1px solid var(--linea); }

/* ---- precio ---- */
.vp-resultado { grid-template-rows: auto 1fr auto; }
.vp-rcab { grid-row: 1; grid-column: 1 / -1; display: flex; align-items: center; gap: 12px; color: var(--gris);
  font-weight: 600; font-size: clamp(14px, 2.4vmin, 28px); min-width: 0; }
.vp-rcab span { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.vp-rcab-logo { display: block; max-height: clamp(26px, 7vh, 80px); max-width: 20vw; object-fit: contain; }
.vp-prod { grid-row: 2; align-self: center; min-width: 0; max-width: 100%%; }
.vp-nombre { font-weight: 600; letter-spacing: -.02em; line-height: 1.1; text-wrap: balance; font-size: clamp(26px, 6.6vmin, 88px);
  display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; overflow-wrap: anywhere; }
.vp-codigo { margin-top: clamp(8px, 2vh, 16px) !important; color: var(--gris); font-size: clamp(14px, 2.4vmin, 28px); }
.vp-codigo span { color: var(--tinta); letter-spacing: .03em; }
.vp-etiqueta { grid-row: 3; justify-self: end; display: flex; align-items: flex-start; color: var(--precio);
  font-weight: 700; line-height: .86; letter-spacing: -.04em; white-space: nowrap; }
.vp-moneda { font-size: calc(clamp(22px, 5.6vmin, 76px) * var(--escala, 1)); font-weight: 600; letter-spacing: 0; margin: .5em .3em 0 0; color: var(--tinta); }
.vp-entero { font-size: calc(clamp(90px, 29vmin, 420px) * var(--escala, 1)); }
.vp-centavos { font-size: calc(clamp(34px, 10vmin, 144px) * var(--escala, 1)); margin-left: .08em; padding-top: .1em; border-bottom: .07em solid currentColor; line-height: .9; }
.vp-cuenta { position: absolute; top: 0; left: 0; right: 0; height: clamp(4px, .6vmin, 8px); background: var(--linea); overflow: hidden; }
.vp-cuenta span { display: block; height: 100%%; background: var(--acento); transform-origin: left; animation: vp-cuenta 10s linear forwards; }
@keyframes vp-cuenta { from { transform: scaleX(1); } to { transform: scaleX(0); } }
.vp-resultado.con-foto { grid-template-columns: auto minmax(0, 1fr); column-gap: clamp(18px, 4vmin, 64px); }
.vp-resultado.con-foto .vp-prod, .vp-resultado.con-foto .vp-etiqueta { grid-column: 2; }
.vp-foto { grid-column: 1; grid-row: 2 / 4; align-self: center; width: min(30vw, 58vh); aspect-ratio: 1; background: #fff;
  border-radius: clamp(10px, 2vmin, 22px); padding: clamp(8px, 2vmin, 22px); display: flex; align-items: center; justify-content: center; }
.vp.estilo-claro .vp-foto, .vp.estilo-etiqueta .vp-foto, .vp.estilo-panel .vp-foto { border: 1px solid var(--linea); }
.vp.estilo-panel .vp-foto { width: min(22vw, 50vh); }
.vp-foto img { display: block; max-width: 100%%; max-height: 100%%; object-fit: contain; }

/* ---- estilos ---- */
.vp.estilo-noche .vp-cab-logo, .vp.estilo-noche .vp-rcab-logo, .vp.estilo-marca .vp-cab-logo, .vp.estilo-marca .vp-rcab-logo,
.vp-panel-logo { background: #fff; border-radius: 12px; padding: clamp(5px, 1.2vmin, 12px); }
.vp.estilo-etiqueta .vp-etiqueta { background: #ffd21f; border-radius: clamp(6px, 1.2vmin, 12px);
  padding: clamp(12px, 3vmin, 30px) clamp(16px, 4vmin, 40px) clamp(10px, 2.4vmin, 24px);
  box-shadow: inset 0 calc(-1 * clamp(4px, 1vmin, 9px)) 0 rgba(15, 36, 64, .1); }
.vp.estilo-etiqueta .vp-moneda { color: var(--precio); }
.vp-riel { position: absolute; left: 0; right: 0; bottom: 0; height: clamp(6px, 1.6vh, 14px); background: #ffd21f; }
.vp-panel { flex: 0 0 clamp(220px, 29vw, 440px); background: var(--marca); color: var(--sobre-marca);
  display: flex; flex-direction: column; justify-content: space-between; gap: 16px; padding: var(--margen); padding-bottom: calc(var(--margen) + 40px); }
.vp-panel-marca { display: flex; flex-direction: column; align-items: flex-start; gap: clamp(10px, 2.4vh, 22px); min-width: 0; }
.vp-panel-logo { display: block; max-width: 100%%; max-height: clamp(56px, 24vh, 220px); object-fit: contain; }
.vp-panel-nombre { font-weight: 700; letter-spacing: -.02em; line-height: 1.08; font-size: clamp(20px, 4.4vmin, 46px); overflow-wrap: anywhere; }
.vp-panel-qr { display: flex; align-items: center; gap: 12px; }
.vp-panel-qr img { display: block; width: clamp(64px, 14vmin, 140px); height: auto; border-radius: 10px; padding: 6px; background: #fff; flex: none; }
.vp-panel-qr figcaption { font-size: clamp(12px, 2vmin, 17px); line-height: 1.3; opacity: .85; }

@media (orientation: portrait) {
  .vp-resultado, .vp-resultado.con-foto { grid-template-columns: minmax(0, 1fr); grid-template-rows: auto 1fr auto auto auto 1fr; text-align: center; }
  .vp-rcab { justify-content: center; }
  .vp .vp-resultado .vp-foto { grid-column: 1; grid-row: 3; justify-self: center; width: min(46vw, 26vh); margin-bottom: 3vh; }
  .vp .vp-resultado .vp-prod { grid-column: 1; grid-row: 4; }
  .vp .vp-resultado .vp-etiqueta { grid-column: 1; grid-row: 5; justify-self: center; margin-top: 3vh; }
  .vp-cab, .vp-qr { justify-self: center; }
  .vp.estilo-panel { flex-direction: column; }
  .vp-panel { flex: 0 0 auto; flex-direction: row; align-items: center; padding-bottom: var(--margen); }
  .vp-panel-marca { flex-direction: row; align-items: center; }
  .vp-panel-logo { max-height: 14vh; max-width: 40vw; }
  .vp-panel-qr figcaption { display: none; }
}
@media (prefers-reduced-motion: reduce) { .vp-laser span, .vp-cuenta span { animation: none; } }
</style>
""" % FUENTE

# El precio siempre cabe a lo ancho (se instala una vez en la página).
AJUSTE_JS = r"""
(() => {
  if (window.__vpAjuste) return; window.__vpAjuste = true;
  function ajustar() {
    document.querySelectorAll('.vp-etiqueta').forEach((et) => {
      const main = et.closest('.vp-main'); if (!main) return;
      et.style.setProperty('--escala', '1');
      const cs = getComputedStyle(main);
      let disponible = main.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight);
      const foto = main.querySelector('.vp-foto');
      if (foto && innerWidth > innerHeight) disponible -= foto.getBoundingClientRect().width + (parseFloat(cs.columnGap) || 0);
      const ancho = et.getBoundingClientRect().width;
      if (disponible > 0 && ancho > disponible) et.style.setProperty('--escala', String(Math.max(.35, disponible / ancho * .97)));
    });
  }
  new MutationObserver(() => requestAnimationFrame(ajustar)).observe(document.body, {childList: true, subtree: true});
  addEventListener('resize', ajustar);
  if (document.fonts) document.fonts.ready.then(ajustar);
  ajustar();
})();
"""
