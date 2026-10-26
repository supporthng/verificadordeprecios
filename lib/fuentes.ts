/** Inventarios que se llenan solos desde Google (en el servidor de Prezio, no en el navegador).
 *  Acepta el enlace de una hoja de Google, una hoja «publicada en la web» o un Excel/CSV guardado en Drive.
 *  La hoja debe estar compartida como «Cualquier persona con el enlace · Lector». */

import { detectarColumnas, leerCsv, leerXlsx, normalizar, productos, type Columnas, type Filas, type Producto } from "@/lib/hoja";

export type ColumnasGuardadas = { codigo: string; nombre: string; precio: string };
export type OrigenGoogle = { tipo: "google"; url: string; columnas?: ColumnasGuardadas; cada_min?: number };

export const FRECUENCIAS = [
  { min: 15, texto: "cada 15 minutos" },
  { min: 30, texto: "cada 30 minutos" },
  { min: 60, texto: "cada hora" },
  { min: 180, texto: "cada 3 horas" },
  { min: 720, texto: "cada 12 horas" },
  { min: 1440, texto: "una vez al día" },
] as const;

export const NO_COMPARTIDA = "Google no dejó leer la hoja. Compártela: Compartir › Acceso general › «Cualquier persona con el enlace» · Lector.";

/** Convierte el enlace que pega el cliente en la dirección de descarga. Solo direcciones de Google. */
export function enlaceGoogle(texto: string): string {
  let u: URL;
  try { u = new URL(texto.trim()); } catch { throw new Error("Pega el enlace completo (empieza con https://)."); }
  if (u.protocol !== "https:" || !["docs.google.com", "drive.google.com"].includes(u.hostname)) {
    throw new Error("Pega el enlace de una hoja de Google o de un archivo de Google Drive.");
  }
  const gid = u.searchParams.get("gid") ?? u.hash.match(/gid=(\d+)/)?.[1] ?? null;
  // Hoja «publicada en la web»: …/spreadsheets/d/e/2PACX…/pubhtml → …/pub?output=csv
  const pub = u.pathname.match(/^\/spreadsheets\/d\/e\/([\w-]+)\//);
  if (pub) {
    const d = new URL(`https://docs.google.com/spreadsheets/d/e/${pub[1]}/pub`);
    d.searchParams.set("output", "csv");
    if (gid) d.searchParams.set("gid", gid);
    return d.toString();
  }
  const hoja = u.pathname.match(/^\/spreadsheets\/d\/([\w-]{20,})/);
  if (hoja) {
    const d = new URL(`https://docs.google.com/spreadsheets/d/${hoja[1]}/export`);
    d.searchParams.set("format", "csv");
    if (gid) d.searchParams.set("gid", gid);
    return d.toString();
  }
  // Archivo en Drive (Excel o CSV subido): /file/d/<id>/…, /open?id=…, /uc?id=…
  const archivo = u.pathname.match(/^\/file\/d\/([\w-]{20,})/)?.[1] ?? u.searchParams.get("id");
  if (u.hostname === "drive.google.com" && archivo && /^[\w-]{20,}$/.test(archivo)) {
    return `https://drive.google.com/uc?export=download&id=${archivo}`;
  }
  throw new Error("No reconocí ese enlace. Ábrelo en Google, copia la dirección de arriba y pégala aquí.");
}

const MAX_BYTES = 40 * 1024 * 1024;

/** Descarga y lee la hoja: devuelve sus filas (la primera hoja del Excel, o la pestaña del enlace). */
export async function descargarGoogle(url: string, hacerFetch: typeof fetch = fetch): Promise<Filas> {
  const destino = enlaceGoogle(url);
  const control = new AbortController();
  const t = setTimeout(() => control.abort(), 40000);
  let r: Response;
  try {
    r = await hacerFetch(destino, { redirect: "follow", cache: "no-store", signal: control.signal });
  } catch {
    throw new Error("Google no respondió. Se intentará de nuevo en la próxima vuelta.");
  } finally {
    clearTimeout(t);
  }
  // Tras las redirecciones debe seguir siendo Google (protege al servidor de enlaces trucados).
  const final = r.url ? new URL(r.url).hostname : "docs.google.com";
  if (!/(^|\.)(google\.com|googleusercontent\.com)$/.test(final)) throw new Error("El enlace salió de Google.");
  if (r.status === 401 || r.status === 403 || r.status === 404) throw new Error(NO_COMPARTIDA);
  if (!r.ok) throw new Error(`Google respondió con un error (${r.status}).`);
  const datos = new Uint8Array(await r.arrayBuffer());
  if (datos.byteLength > MAX_BYTES) throw new Error("La hoja pesa más de 40 MB.");
  if (datos[0] === 0x50 && datos[1] === 0x4b) return leerXlsx(datos.buffer.slice(datos.byteOffset, datos.byteOffset + datos.byteLength));
  const texto = new TextDecoder("utf-8").decode(datos);
  if (/^\s*<(!doctype html|html)/i.test(texto)) throw new Error(NO_COMPARTIDA);
  if (datos[0] === 0xd0 && datos[1] === 0xcf) throw new Error("Ese archivo es un Excel antiguo (.xls). Guárdalo como .xlsx en Drive.");
  return leerCsv(texto);
}

/** Columnas por su NOMBRE (si alguien mueve columnas en la hoja, sigue funcionando). */
export function columnasDe(filas: Filas, guardadas?: ColumnasGuardadas): Columnas {
  if (!guardadas) return detectarColumnas(filas);
  const buscadas = [guardadas.codigo, guardadas.nombre, guardadas.precio].map(normalizar);
  for (let r = 0; r < Math.min(40, filas.length); r++) {
    const norm = (filas[r] ?? []).map(normalizar);
    const [codigo, nombre, precio] = buscadas.map((b) => norm.indexOf(b));
    if (codigo >= 0 && nombre >= 0 && precio >= 0) return { encabezado: r, codigo, nombre, precio };
  }
  const faltan = [guardadas.codigo, guardadas.nombre, guardadas.precio]
    .filter((n) => !filas.slice(0, 40).some((f) => (f ?? []).map(normalizar).includes(normalizar(n))));
  throw new Error(`No encontré en la hoja la columna ${faltan.map((f) => `«${f}»`).join(", ") || "elegida"}. ¿Le cambiaron el nombre?`);
}

export function nombresDeColumnas(filas: Filas, c: Columnas): ColumnasGuardadas {
  const f = filas[c.encabezado] ?? [];
  return { codigo: f[c.codigo] ?? "", nombre: f[c.nombre] ?? "", precio: f[c.precio] ?? "" };
}

/** Lee la hoja de un origen y devuelve los productos listos para guardar. */
export async function productosDeGoogle(origen: OrigenGoogle, hacerFetch?: typeof fetch): Promise<Producto[]> {
  const filas = await descargarGoogle(origen.url, hacerFetch);
  if (!filas.length) throw new Error("La hoja está vacía.");
  const { lista } = productos(filas, columnasDe(filas, origen.columnas));
  if (!lista.length) throw new Error("La hoja no tiene productos con código, nombre y precio.");
  return lista;
}

export const PARTE = 4000;

/** Envía los productos en partes; la última reemplaza el inventario de una vez. Devuelve cuántos quedaron. */
export async function enviarEnPartes(
  lista: Producto[],
  enviar: (lote: string, parte: Producto[], fin: boolean) => Promise<number>,
): Promise<number> {
  const lote = crypto.randomUUID();
  let total = 0;
  for (let i = 0; i < lista.length; i += PARTE) {
    const fin = i + PARTE >= lista.length;
    const n = await enviar(lote, lista.slice(i, i + PARTE), fin);
    if (fin) total = n;
  }
  return total;
}
