"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { Marca } from "./Marca";

type ApiApp = { ir_app?: (s: string) => Promise<unknown>; salir?: () => Promise<unknown>; abrir_en_navegador?: (u: string) => Promise<unknown> };
const apiApp = (): ApiApp | null => (typeof window !== "undefined" ? (window as { pywebview?: { api?: ApiApp } }).pywebview?.api ?? null : null);

/** ¿Esta página está abierta dentro de la app Prezio Administrador? (la app pone window.pywebview.api) */
export function useEnApp(): boolean {
  const [en, setEn] = useState(false);
  useEffect(() => {
    let n = 0;
    const t = setInterval(() => {
      if (apiApp()?.ir_app) { setEn(true); clearInterval(t); }
      else if (++n > 30) clearInterval(t);
    }, 150);
    return () => clearInterval(t);
  }, []);
  return en;
}

const PANEL = [
  { clave: "", texto: "Resumen" },
  { clave: "sucursales", texto: "Sucursales" },
  { clave: "inventarios", texto: "Inventarios" },
  { clave: "apariencia", texto: "Apariencia" },
  { clave: "equipos", texto: "Equipos" },
  { clave: "usuarios", texto: "Usuarios" },
] as const;

/** En la app, el mismo menú lateral de la pantalla de la app (Inicio, Base de datos, Copia automática y las secciones
 *  del panel) siempre a la vista mientras se navega por el panel, en la misma ventana. Los enlaces que se abren en
 *  otra pestaña (p. ej. «Probar» el verificador) van al navegador, para que la ventana nunca quede sin salida. */
export function MenuLateralApp({ negocio }: { negocio: { nombre: string; slug: string } }) {
  const en = useEnApp();
  const ruta = usePathname() ?? "";
  useEffect(() => {
    if (!en) return;
    document.documentElement.dataset.enApp = "1";
    const alHacerClic = (e: MouseEvent) => {
      const a = (e.target as HTMLElement | null)?.closest?.("a[target=_blank]") as HTMLAnchorElement | null;
      if (!a || !a.href.startsWith(window.location.origin + "/")) return;
      e.preventDefault();
      void apiApp()?.abrir_en_navegador?.(a.href);
    };
    document.addEventListener("click", alHacerClic, true);
    return () => { document.removeEventListener("click", alHacerClic, true); delete document.documentElement.dataset.enApp; };
  }, [en]);
  if (!en) return null;
  const base = `/n/${negocio.slug}`;
  const activa = ruta === base ? "" : ruta.startsWith(base + "/") ? ruta.slice(base.length + 1).split("/")[0] : null;
  const icono = { fill: "none", stroke: "currentColor", strokeWidth: 2, viewBox: "0 0 24 24", "aria-hidden": true } as const;
  return (
    <aside className="menu-app" aria-label="Menú de la app">
      <div className="menu-app-marca"><Marca claro tamano={26} /><small>Administrador</small></div>
      <div className="menu-app-negocio"><strong>{negocio.nombre}</strong></div>
      <nav aria-label="Secciones">
        <button type="button" onClick={() => void apiApp()?.ir_app?.("inicio")}>
          <svg {...icono}><path d="M3 11l9-7 9 7v9a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z" /></svg>Inicio
        </button>
        <button type="button" onClick={() => void apiApp()?.ir_app?.("base")}>
          <svg {...icono}><ellipse cx="12" cy="5" rx="8" ry="3" /><path d="M4 5v6c0 1.7 3.6 3 8 3s8-1.3 8-3V5M4 11v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6" /></svg>Base de datos
        </button>
        <button type="button" onClick={() => void apiApp()?.ir_app?.("copia")}>
          <svg {...icono}><path d="M21 12a9 9 0 1 1-3-6.7L21 8M21 3v5h-5" /></svg>Copia automática
        </button>
        <span className="menu-app-grupo">Panel del negocio</span>
        {PANEL.map((p) => (
          <Link key={p.clave} href={p.clave ? `${base}/${p.clave}` : base} aria-current={activa === p.clave ? "page" : undefined}>
            <span className="menu-app-punto" />{p.texto}
          </Link>
        ))}
      </nav>
      <div className="menu-app-pie">
        <button type="button" onClick={() => void apiApp()?.salir?.()}>Salir</button>
      </div>
    </aside>
  );
}

/** Lo que no va dentro de la app (cada app es de un solo negocio). */
export function SoloWeb({ children }: { children: React.ReactNode }) {
  return useEnApp() ? null : <>{children}</>;
}

/** «Salir»: en la web cierra la sesión; en la app también la de la app (y vuelve a su pantalla de entrar). */
export function BotonSalir() {
  const en = useEnApp();
  return (
    <form action="/salir" method="post" onSubmit={(e) => { if (en) { e.preventDefault(); void apiApp()?.salir?.(); } }}>
      <button className="boton secundario" type="submit">Salir</button>
    </form>
  );
}
