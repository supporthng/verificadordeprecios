"use client";

import { useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { FRECUENCIAS, NO_COMPARTIDA, type ColumnasGuardadas } from "@/lib/fuentes";
import {
  compartirPorEnlace, driveConfigurado, elegirArchivoDrive, enlaceDeArchivo, nombreSinExtension, type ArchivoDrive,
} from "@/lib/googleDrive";
import { crearGoogle, revisarGoogle, type Revision } from "./fuentes";

type Props = { negocioId: string; slug: string; nombresUsados: string[] };

/** Nuevo inventario que se llena solo desde una hoja de Google o un Excel en Drive. */
export function FuenteGoogle({ negocioId, slug, nombresUsados }: Props) {
  const router = useRouter();
  const [url, setUrl] = useState("");
  const [revision, setRevision] = useState<Extract<Revision, { ok: true }> | null>(null);
  const [columnas, setColumnas] = useState<ColumnasGuardadas | null>(null);
  const [nombre, setNombre] = useState("");
  const [cada, setCada] = useState(60);
  const [estado, setEstado] = useState<{ tipo: "error" | "bien" | "trabajando"; texto: string } | null>(null);
  const [elegido, setElegido] = useState<ArchivoDrive | null>(null);
  const elegidoRef = useRef<ArchivoDrive | null>(null);   // lo mismo que «elegido», para leerlo dentro de revisar()
  const [sinCompartir, setSinCompartir] = useState(false);
  const trabajando = estado?.tipo === "trabajando";
  const repetido = nombresUsados.some((n) => n.trim().toLowerCase() === nombre.trim().toLowerCase());

  async function revisar(enlace: string = url, nombreSugerido = "") {
    setEstado({ tipo: "trabajando", texto: "Leyendo la hoja en Google…" });
    setRevision(null);
    setSinCompartir(false);
    const r = await revisarGoogle(enlace);
    if (!r.ok) {
      // Elegido desde Drive pero sin compartir por enlace: se ofrece compartirlo con un toque.
      if (r.error === NO_COMPARTIDA && elegidoRef.current) { setSinCompartir(true); setEstado(null); return; }
      setEstado({ tipo: "error", texto: r.error });
      return;
    }
    setRevision(r);
    setColumnas(r.columnas);
    setNombre((n) => n || nombreSugerido || "Hoja de Google");
    setEstado(null);
  }

  /** Elegir el archivo en Google Drive: se llena el enlace y se revisa de una vez. */
  async function elegirDeDrive() {
    setEstado({ tipo: "trabajando", texto: "Abriendo Google Drive…" });
    try {
      const a = await elegirArchivoDrive();
      if (!a) { setEstado(null); return; }
      elegidoRef.current = a;
      setElegido(a);
      const enlace = enlaceDeArchivo(a);
      setUrl(enlace);
      setNombre("");
      await revisar(enlace, nombreSinExtension(a.nombre));
    } catch (e) {
      setEstado({ tipo: "error", texto: e instanceof Error ? e.message : "No se pudo abrir Google Drive." });
    }
  }

  async function compartirYRevisar() {
    if (!elegido) return;
    setEstado({ tipo: "trabajando", texto: "Compartiendo el archivo por enlace…" });
    const error = await compartirPorEnlace(elegido);
    if (error) { setEstado({ tipo: "error", texto: error }); return; }
    await revisar(enlaceDeArchivo(elegido), nombreSinExtension(elegido.nombre));
  }

  async function crear() {
    if (!columnas) return;
    setEstado({ tipo: "trabajando", texto: "Creando el inventario y cargando los productos…" });
    const r = await crearGoogle({ negocioId, slug, nombre, url, columnas, cada_min: cada });
    if (!r.ok) { setEstado({ tipo: "error", texto: r.error }); router.refresh(); return; }
    setEstado({ tipo: "bien", texto: `Listo: ${r.productos.toLocaleString("es-DO")} productos. Se actualizará solo ${FRECUENCIAS.find((f) => f.min === cada)?.texto}.` });
    setRevision(null); setUrl(""); setNombre("");
    router.refresh();
  }

  const selector = (clave: keyof ColumnasGuardadas, etiqueta: string) => revision && columnas && (
    <div className="campo" style={{ marginBottom: 0 }}>
      <label htmlFor={`g-col-${clave}`}>{etiqueta}</label>
      <select id={`g-col-${clave}`} value={columnas[clave]} onChange={(e) => setColumnas({ ...columnas, [clave]: e.target.value })}>
        {revision.encabezados.map((t, i) => <option key={i} value={t}>{t}</option>)}
      </select>
    </div>
  );

  return (
    <section className="tarjeta" aria-labelledby="t-google" style={{ marginTop: 20 }}>
      <h2 id="t-google">Inventario desde Google</h2>
      <p className="quieto" style={{ marginTop: 0 }}>
        Una hoja de Google o un Excel guardado en Google Drive que se actualiza solo. Elígelo desde Google Drive o,
        en Google, toca <strong>Compartir › Acceso general › Cualquier persona con el enlace</strong> y pega el enlace.
      </p>
      {driveConfigurado() && (
        <p style={{ margin: "0 0 14px" }}>
          <button className="boton" type="button" onClick={elegirDeDrive} disabled={trabajando}>Elegir de Google Drive</button>
          <span className="quieto pequeno" style={{ marginLeft: 10 }}>o pega el enlace abajo</span>
        </p>
      )}
      {sinCompartir && elegido && (
        <div className="aviso" role="status" style={{ marginBottom: 14 }}>
          <p style={{ margin: "0 0 10px" }}>
            «{elegido.nombre}» es privado. Para que Prezio lo actualice solo, debe quedar como
            <strong> «Cualquier persona con el enlace · Lector»</strong>. Solo se comparte para leer, no para editar.
          </p>
          <button className="boton" type="button" onClick={compartirYRevisar} disabled={trabajando}>Compartir por enlace y continuar</button>
        </div>
      )}
      <div className="fila">
        <div className="campo" style={{ marginBottom: 0, flex: "3 1 320px" }}>
          <label htmlFor="g-url">Enlace de la hoja</label>
          <input id="g-url" type="url" value={url} onChange={(e) => { setUrl(e.target.value); setRevision(null); setSinCompartir(false); elegidoRef.current = null; setElegido(null); }}
            placeholder="https://docs.google.com/spreadsheets/d/…" autoComplete="off" />
        </div>
        <button className="boton secundario" type="button" onClick={() => void revisar()} disabled={!url.trim() || trabajando}>Revisar la hoja</button>
      </div>

      {revision && columnas && (
        <>
          <p style={{ margin: "16px 0 8px" }}>
            <strong>{revision.validos.toLocaleString("es-DO")} productos</strong> listos
            {revision.descartados > 0 && <span className="quieto"> · {revision.descartados.toLocaleString("es-DO")} filas sin código, nombre o precio</span>}
          </p>
          <div className="desplazable">
            <table className="tabla pequeno">
              <thead><tr>{revision.encabezados.map((t, i) => <th key={i}>{t}</th>)}</tr></thead>
              <tbody>{revision.muestra.map((f, r) => <tr key={r}>{revision.encabezados.map((_, i) => <td key={i}>{f[i] ?? ""}</td>)}</tr>)}</tbody>
            </table>
          </div>
          <div className="fila" style={{ marginTop: 16 }}>
            {selector("codigo", "Código")}
            {selector("nombre", "Nombre")}
            {selector("precio", "Precio")}
          </div>
          <div className="fila" style={{ marginTop: 16 }}>
            <div className="campo" style={{ marginBottom: 0 }}>
              <label htmlFor="g-nombre">Nombre del inventario</label>
              <input id="g-nombre" value={nombre} onChange={(e) => setNombre(e.target.value)} maxLength={80} />
            </div>
            <div className="campo" style={{ marginBottom: 0 }}>
              <label htmlFor="g-cada">Actualizar</label>
              <select id="g-cada" value={cada} onChange={(e) => setCada(Number(e.target.value))}>
                {FRECUENCIAS.map((f) => <option key={f.min} value={f.min}>{f.texto}</option>)}
              </select>
            </div>
            <button className="boton" type="button" onClick={crear}
              disabled={trabajando || !nombre.trim() || repetido || !revision.validos}>Crear inventario</button>
          </div>
          {repetido && <p className="error-campo">Ya existe un inventario con ese nombre.</p>}
        </>
      )}
      {estado && (
        <p className={estado.tipo === "error" ? "aviso error" : estado.tipo === "bien" ? "aviso bien" : "quieto"}
          role={estado.tipo === "error" ? "alert" : "status"} style={{ marginTop: 16, marginBottom: 0 }}>{estado.texto}</p>
      )}
    </section>
  );
}
