"use client";

import { useEffect, useState } from "react";

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

/** En la app, arriba del panel y siempre a la vista: volver atrás, a Inicio, a «Base de datos» o «Copia automática»
 *  sin salir de la ventana. Los enlaces que se abren en otra pestaña (p. ej. «Probar» el verificador) van al
 *  navegador, para que la ventana de la app nunca se quede en una página sin salida. */
export function NavegacionApp() {
  const en = useEnApp();
  const [puedeVolver, setPuedeVolver] = useState(false);
  useEffect(() => {
    if (!en) return;
    document.documentElement.dataset.enApp = "1";
    setPuedeVolver(window.history.length > 1);
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
  return (
    <>
      {puedeVolver && <button type="button" className="subnav-app" onClick={() => window.history.back()}>‹ Atrás</button>}
      <button type="button" className="subnav-app" onClick={() => void apiApp()?.ir_app?.("inicio")}>Inicio</button>
      <button type="button" className="subnav-app" onClick={() => void apiApp()?.ir_app?.("base")}>Base de datos</button>
      <button type="button" className="subnav-app" onClick={() => void apiApp()?.ir_app?.("copia")}>Copia automática</button>
    </>
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
