/** Elegir un Excel, CSV u hoja de Google directamente desde Google Drive (selector oficial de Google).
 *
 *  Solo se pide el permiso «drive.file»: Prezio ve ÚNICAMENTE el archivo que la persona elige, nunca el resto
 *  de su Drive. El permiso dura una hora y no se guarda en ningún lado.
 *
 *  Variables en Vercel (las tres son públicas, van con el prefijo NEXT_PUBLIC_):
 *    NEXT_PUBLIC_GOOGLE_CLIENT_ID   ID de cliente OAuth «Aplicación web» (Google Cloud › Credenciales)
 *    NEXT_PUBLIC_GOOGLE_API_KEY     Clave de API para el selector (Google Cloud › Credenciales)
 *    NEXT_PUBLIC_GOOGLE_APP_ID      Número del proyecto de Google Cloud (Panel › Número del proyecto)
 *  Sin ellas el botón de Drive no aparece y todo sigue funcionando con el enlace pegado. */

/* eslint-disable @typescript-eslint/no-explicit-any */

const CLIENT_ID = process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID ?? "";
const API_KEY = process.env.NEXT_PUBLIC_GOOGLE_API_KEY ?? "";
const APP_ID = process.env.NEXT_PUBLIC_GOOGLE_APP_ID ?? "";

export const driveConfigurado = (): boolean => Boolean(CLIENT_ID && API_KEY && APP_ID);

const PERMISO = "https://www.googleapis.com/auth/drive.file";
const API = "https://www.googleapis.com/drive/v3/files";
const MIME_HOJA = "application/vnd.google-apps.spreadsheet";
const MIME_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";
const MIMES = [MIME_HOJA, MIME_XLSX, "text/csv", "application/vnd.ms-excel"].join(",");

export type ArchivoDrive = { id: string; nombre: string; mime: string; token: string };

function cargarScript(src: string): Promise<void> {
  return new Promise((ok, mal) => {
    const falla = () => mal(new Error("No se pudo cargar Google. Revisa la conexión a internet."));
    const previo = document.querySelector<HTMLScriptElement>(`script[src="${src}"]`);
    if (previo) {
      if (previo.dataset.listo) ok();
      else { previo.addEventListener("load", () => ok()); previo.addEventListener("error", falla); }
      return;
    }
    const s = document.createElement("script");
    s.src = src; s.async = true;
    s.onload = () => { s.dataset.listo = "1"; ok(); };
    s.onerror = falla;
    document.head.appendChild(s);
  });
}

/** Pide el permiso a Google (ventana emergente). Devuelve null si la persona cierra la ventana. */
function pedirPermiso(): Promise<string | null> {
  return new Promise((ok, mal) => {
    const g = (window as any).google;
    const cliente = g.accounts.oauth2.initTokenClient({
      client_id: CLIENT_ID,
      scope: PERMISO,
      callback: (r: any) => {
        if (r?.access_token) ok(r.access_token);
        else if (r?.error === "access_denied") ok(null);
        else mal(new Error("Google no dio acceso a Drive. Intenta de nuevo."));
      },
      error_callback: (e: any) => {
        if (e?.type === "popup_closed") ok(null);
        else mal(new Error("No se pudo abrir la ventana de Google. Permite las ventanas emergentes e intenta de nuevo."));
      },
    });
    cliente.requestAccessToken({ prompt: "" });
  });
}

/** Abre el selector de Google Drive. Devuelve el archivo elegido, o null si la persona cancela. */
export async function elegirArchivoDrive(): Promise<ArchivoDrive | null> {
  if (!driveConfigurado()) throw new Error("Falta configurar Google Drive en Prezio.");
  await Promise.all([cargarScript("https://accounts.google.com/gsi/client"), cargarScript("https://apis.google.com/js/api.js")]);
  const token = await pedirPermiso();
  if (!token) return null;
  await new Promise<void>((ok) => (window as any).gapi.load("picker", { callback: ok }));
  const g = (window as any).google;
  return new Promise<ArchivoDrive | null>((ok) => {
    const mias = new g.picker.DocsView(g.picker.ViewId.DOCS)
      .setIncludeFolders(true).setSelectFolderEnabled(false).setMimeTypes(MIMES);
    const compartidas = new g.picker.DocsView(g.picker.ViewId.DOCS)
      .setIncludeFolders(true).setSelectFolderEnabled(false).setOwnedByMe(false).setMimeTypes(MIMES);
    const selector = new g.picker.PickerBuilder()
      .setAppId(APP_ID)
      .setDeveloperKey(API_KEY)
      .setOAuthToken(token)
      .setLocale("es")
      .setTitle("Elige el Excel o la hoja de Google")
      .addView(mias)
      .addView(compartidas)
      .setCallback((r: any) => {
        if (r.action === g.picker.Action.PICKED) {
          const d = r.docs?.[0];
          ok(d ? { id: String(d.id), nombre: String(d.name ?? "Archivo"), mime: String(d.mimeType ?? ""), token } : null);
        } else if (r.action === g.picker.Action.CANCEL) ok(null);
      })
      .build();
    selector.setVisible(true);
  });
}

/** Enlace normal del archivo elegido (el mismo que el cliente pegaría a mano). */
export function enlaceDeArchivo(a: ArchivoDrive): string {
  return a.mime === MIME_HOJA
    ? `https://docs.google.com/spreadsheets/d/${a.id}/edit`
    : `https://drive.google.com/file/d/${a.id}/view`;
}

/** Descarga el archivo elegido (sin necesidad de compartirlo) y lo deja listo para leer. */
export async function descargarDeDrive(a: ArchivoDrive): Promise<{ name: string; arrayBuffer(): Promise<ArrayBuffer> }> {
  const esHoja = a.mime === MIME_HOJA;
  const url = esHoja
    ? `${API}/${a.id}/export?mimeType=${encodeURIComponent(MIME_XLSX)}`
    : `${API}/${a.id}?alt=media&supportsAllDrives=true`;
  let r: Response;
  try { r = await fetch(url, { headers: { Authorization: `Bearer ${a.token}` } }); }
  catch { throw new Error("No se pudo descargar el archivo de Google Drive. Revisa la conexión."); }
  if (!r.ok) throw new Error(`Google Drive no dejó leer el archivo (${r.status}).`);
  const datos = await r.arrayBuffer();
  const name = esHoja && !/\.xlsx$/i.test(a.nombre) ? `${a.nombre}.xlsx` : a.nombre;
  return { name, arrayBuffer: async () => datos };
}

/** Deja el archivo como «Cualquier persona con el enlace · Lector» para que Prezio lo actualice solo.
 *  Devuelve un texto de error, o "" si quedó bien. Solo funciona si la persona es dueña o editora del archivo. */
export async function compartirPorEnlace(a: ArchivoDrive): Promise<string> {
  try {
    const r = await fetch(`${API}/${a.id}/permissions?supportsAllDrives=true`, {
      method: "POST",
      headers: { Authorization: `Bearer ${a.token}`, "Content-Type": "application/json" },
      body: JSON.stringify({ role: "reader", type: "anyone" }),
    });
    if (r.ok) return "";
    return r.status === 403
      ? "No tienes permiso para compartir este archivo. Pídele al dueño que lo comparta como «Cualquier persona con el enlace»."
      : `Google no dejó compartir el archivo (${r.status}).`;
  } catch {
    return "No se pudo compartir el archivo. Revisa la conexión.";
  }
}

export function nombreSinExtension(nombre: string): string {
  return nombre.replace(/\.[^.]+$/, "").replace(/[_]+/g, " ").trim().slice(0, 80);
}
