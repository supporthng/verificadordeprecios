/** Puente con las apps Prezio (Android y Windows) cuando la página /equipo corre dentro de ellas.
 *  Android: objeto window.PrezioApp. Windows (pywebview): window.pywebview.api (asíncrono). */

export type AppNativa = {
  plataforma: "android" | "windows";
  version: () => Promise<string>;
  salir: () => void;
  cerrar: () => void;
  buscarActualizacion: () => void;
};

type Android = { plataforma(): string; version(): string; salir(): void; cerrar?(): void; buscarActualizacion(): void };
type Windows = { version(): Promise<string>; salir(): Promise<unknown>; cerrar?(): Promise<unknown>; buscarActualizacion(): Promise<unknown> };

export function appNativa(): AppNativa | null {
  if (typeof window === "undefined") return null;
  const w = window as unknown as { PrezioApp?: Android; pywebview?: { api?: Windows } };
  if (w.PrezioApp) {
    const a = w.PrezioApp;
    return {
      plataforma: "android",
      version: async () => { try { return a.version(); } catch { return ""; } },
      salir: () => a.salir(),
      cerrar: () => { if (a.cerrar) a.cerrar(); else a.salir(); },
      buscarActualizacion: () => a.buscarActualizacion(),
    };
  }
  const api = w.pywebview?.api;
  if (api && typeof api.salir === "function") {
    return {
      plataforma: "windows",
      version: async () => { try { return String(await api.version()); } catch { return ""; } },
      salir: () => { void api.salir(); },
      cerrar: () => { void (api.cerrar ?? api.salir)(); },
      buscarActualizacion: () => { void api.buscarActualizacion(); },
    };
  }
  return null;
}

/** Avisos de la app al actualizarse: buscando, al_dia, descargando, instalando, error. */
export const TEXTO_ACTUALIZACION: Record<string, string> = {
  buscando: "Buscando una versión nueva de la app…",
  al_dia: "La app ya está en la última versión.",
  descargando: "Descargando la versión nueva de la app…",
  instalando: "Instalando la versión nueva: la app se abre sola en unos segundos.",
  confirmar: "Android pide confirmar la instalación.",
  error: "No se pudo actualizar la app. Se intentará de nuevo más tarde.",
};
