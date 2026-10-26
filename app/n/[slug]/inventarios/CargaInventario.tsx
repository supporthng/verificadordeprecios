"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { supabaseNavegador } from "@/lib/supabase/browser";
import { detectarColumnas, leerArchivo, productos, type Columnas, type Filas } from "@/lib/hoja";
import { descargarDeDrive, driveConfigurado, elegirArchivoDrive } from "@/lib/googleDrive";

type Inventario = { id: string; nombre: string; usos: string[] };
type Props = { negocioId: string; inventarios: Inventario[]; moneda: string };

const LOTE = 1000;

/** Cargar un Excel o CSV: leerlo en el navegador, revisar columnas y elegir en qué inventario se guarda. */
export function CargaInventario({ negocioId, inventarios, moneda }: Props) {
  const router = useRouter();
  const [archivo, setArchivo] = useState<string>("");
  const [filas, setFilas] = useState<Filas>([]);
  const [col, setCol] = useState<Columnas | null>(null);
  const [destino, setDestino] = useState<"existente" | "nuevo">(inventarios.length ? "existente" : "nuevo");
  const [inventarioId, setInventarioId] = useState(inventarios[0]?.id ?? "");
  const [modo, setModo] = useState<"actualizar" | "reemplazar">("actualizar");
  const [nombreNuevo, setNombreNuevo] = useState("");
  const [estado, setEstado] = useState<{ tipo: "error" | "bien" | "trabajando"; texto: string; avance?: number } | null>(null);

  const resultado = useMemo(() => (col ? productos(filas, col) : null), [filas, col]);
  const encabezados = col ? (filas[col.encabezado] ?? []) : [];
  const opcionesCol = encabezados.map((t, i) => ({ i, t: t || `Columna ${i + 1}` }));
  const nombreRepetido = destino === "nuevo"
    && inventarios.some((i) => i.nombre.trim().toLowerCase() === nombreNuevo.trim().toLowerCase());
  const destinoListo = destino === "existente" ? Boolean(inventarioId) : nombreNuevo.trim().length > 0 && !nombreRepetido;
  const trabajando = estado?.tipo === "trabajando";

  async function elegirArchivo(f: { name: string; arrayBuffer(): Promise<ArrayBuffer> } | undefined) {
    setEstado(null);
    if (!f) return;
    try {
      setEstado({ tipo: "trabajando", texto: "Leyendo el archivo…" });
      const leidas = await leerArchivo(f);
      if (!leidas.length) throw new Error("El archivo está vacío.");
      setFilas(leidas);
      setCol(detectarColumnas(leidas));
      setArchivo(f.name);
      setNombreNuevo(f.name.replace(/\.[^.]+$/, "").replace(/[_]+/g, " ").trim().slice(0, 80));
      setEstado(null);
    } catch (e) {
      setFilas([]); setCol(null); setArchivo("");
      setEstado({ tipo: "error", texto: e instanceof Error ? e.message : "No se pudo leer el archivo." });
    }
  }

  /** Elegir el Excel desde Google Drive (selector de Google) y leerlo igual que uno subido. */
  async function elegirDeDrive() {
    setEstado({ tipo: "trabajando", texto: "Abriendo Google Drive…" });
    try {
      const a = await elegirArchivoDrive();
      if (!a) { setEstado(null); return; }
      setEstado({ tipo: "trabajando", texto: `Descargando «${a.nombre}» de Google Drive…` });
      await elegirArchivo(await descargarDeDrive(a));
    } catch (e) {
      setEstado({ tipo: "error", texto: e instanceof Error ? e.message : "No se pudo abrir Google Drive." });
    }
  }

  async function publicar() {
    if (!resultado || !resultado.lista.length || !destinoListo) return;
    const supabase = supabaseNavegador();
    const lista = resultado.lista;
    try {
      let id = inventarioId;
      let reemplazar = modo === "reemplazar";
      if (destino === "nuevo") {
        setEstado({ tipo: "trabajando", texto: "Creando el inventario…", avance: 0.05 });
        const { data, error } = await supabase.from("inventarios")
          .insert({ negocio_id: negocioId, nombre: nombreNuevo.trim() }).select("id").single();
        if (error) throw error;
        id = (data as { id: string }).id;
        reemplazar = true;
      }
      if (reemplazar) {
        setEstado({ tipo: "trabajando", texto: `Guardando ${lista.length.toLocaleString("es-DO")} productos…`, avance: 0.4 });
        const { error } = await supabase.rpc("reemplazar_productos", { p_inventario: id, p_productos: lista });
        if (error) throw error;
      } else {
        for (let i = 0; i < lista.length; i += LOTE) {
          setEstado({ tipo: "trabajando", texto: `Guardando productos… ${Math.min(i + LOTE, lista.length).toLocaleString("es-DO")} de ${lista.length.toLocaleString("es-DO")}`, avance: (i + LOTE) / lista.length });
          const lote = lista.slice(i, i + LOTE).map((p) => ({ ...p, inventario_id: id, negocio_id: negocioId }));
          const { error } = await supabase.from("productos").upsert(lote, { onConflict: "inventario_id,codigo" });
          if (error) throw error;
        }
        await supabase.from("inventarios").update({ actualizado: new Date().toISOString() }).eq("id", id);
      }
      const nombre = destino === "nuevo" ? nombreNuevo.trim() : inventarios.find((x) => x.id === id)?.nombre;
      setEstado({ tipo: "bien", texto: `Listo: ${lista.length.toLocaleString("es-DO")} productos en «${nombre}».` });
      setFilas([]); setCol(null); setArchivo("");
      router.refresh();
    } catch (e) {
      const m = (e as { message?: string })?.message ?? "";
      setEstado({ tipo: "error", texto: /duplicate key/i.test(m) ? "Ya existe un inventario con ese nombre." : m || "No se pudo guardar." });
    }
  }

  const selectorCol = (campo: "codigo" | "nombre" | "precio", etiqueta: string) => (
    <div className="campo">
      <label htmlFor={`col-${campo}`}>{etiqueta}</label>
      <select id={`col-${campo}`} value={col?.[campo] ?? -1}
        onChange={(e) => col && setCol({ ...col, [campo]: Number(e.target.value) })}>
        <option value={-1}>— elige —</option>
        {opcionesCol.map((o) => <option key={o.i} value={o.i}>{o.t}</option>)}
      </select>
    </div>
  );

  return (
    <section className="tarjeta" style={{ marginTop: 24 }}>
      <h2>Cargar un Excel</h2>
      <p className="quieto pequeno">Excel (.xlsx) o CSV con código de barras, descripción y precio. El archivo se lee en tu equipo.</p>
      {estado && estado.tipo !== "trabajando" && (
        <p className={`aviso ${estado.tipo === "error" ? "error" : "bien"}`} role={estado.tipo === "error" ? "alert" : "status"}>{estado.texto}</p>
      )}
      <label className="zona-archivo"
        onDragOver={(e) => e.preventDefault()}
        onDrop={(e) => { e.preventDefault(); if (!trabajando) void elegirArchivo(e.dataTransfer.files?.[0]); }}>
        <input type="file" accept=".xlsx,.csv,.txt,.xls" disabled={trabajando}
          onChange={(e) => { void elegirArchivo(e.target.files?.[0]); e.target.value = ""; }} />
        <strong>{archivo || "Elige un archivo"}</strong>
        <span className="quieto pequeno" style={{ display: "block" }}>
          {archivo ? "Toca para elegir otro" : "o arrástralo aquí"}
        </span>
      </label>
      {driveConfigurado() && (
        <p style={{ margin: "12px 0 0" }}>
          <button className="boton secundario" type="button" onClick={elegirDeDrive} disabled={trabajando}>
            Elegir de Google Drive
          </button>
          <span className="quieto pequeno" style={{ marginLeft: 10 }}>Un Excel o una hoja de tu Drive, sin compartirla.</span>
        </p>
      )}

      {col && resultado && (
        <>
          <div className="fila" style={{ marginTop: 20 }}>
            {selectorCol("codigo", "Código de barras")}
            {selectorCol("nombre", "Descripción")}
            {selectorCol("precio", "Precio")}
          </div>
          <p>
            <strong>{resultado.lista.length.toLocaleString("es-DO")}</strong> productos válidos
            {resultado.descartados > 0 && <span className="quieto"> · {resultado.descartados.toLocaleString("es-DO")} filas sin código, nombre o precio (se omiten)</span>}
          </p>
          {resultado.lista.length > 0 && (
            <div className="desplazable">
              <table className="tabla">
                <thead><tr><th>Código</th><th>Descripción</th><th className="num">Precio</th></tr></thead>
                <tbody>
                  {resultado.lista.slice(0, 8).map((p) => (
                    <tr key={p.codigo}><td>{p.codigo}</td><td>{p.nombre}</td>
                      <td className="num">{moneda} {p.precio.toLocaleString("en-US", { minimumFractionDigits: 2 })}</td></tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <h2 style={{ marginTop: 24 }}>¿En qué inventario se guardan?</h2>
          <div className="opciones">
            <label className="opcion">
              <input type="radio" name="destino" checked={destino === "existente"} disabled={!inventarios.length}
                onChange={() => setDestino("existente")} />
              <span>Actualizar un inventario existente</span>
            </label>
            <label className="opcion">
              <input type="radio" name="destino" checked={destino === "nuevo"} onChange={() => setDestino("nuevo")} />
              <span>Crear un inventario nuevo</span>
            </label>
          </div>
          {destino === "existente" ? (
            <div style={{ marginTop: 16 }}>
              <div className="campo">
                <label htmlFor="inv">Inventario</label>
                <select id="inv" value={inventarioId} onChange={(e) => setInventarioId(e.target.value)}>
                  {inventarios.map((i) => (
                    <option key={i.id} value={i.id}>{i.nombre}{i.usos.length ? ` · lo usa: ${i.usos.join(", ")}` : ""}</option>
                  ))}
                </select>
              </div>
              <div className="opciones">
                <label className="opcion">
                  <input type="radio" name="modo" checked={modo === "actualizar"} onChange={() => setModo("actualizar")} />
                  <span>Actualizar: agrega los nuevos y cambia los precios; conserva los demás productos</span>
                </label>
                <label className="opcion">
                  <input type="radio" name="modo" checked={modo === "reemplazar"} onChange={() => setModo("reemplazar")} />
                  <span>Reemplazar todo: el inventario queda exactamente como este archivo</span>
                </label>
              </div>
            </div>
          ) : (
            <div className="campo" style={{ marginTop: 16 }}>
              <label htmlFor="nuevo">Nombre del inventario nuevo</label>
              <input id="nuevo" value={nombreNuevo} maxLength={80} onChange={(e) => setNombreNuevo(e.target.value)}
                placeholder="Ej.: Precios Sucursal Centro" />
              {nombreRepetido && <p className="pequeno" style={{ color: "var(--error)", marginTop: 6 }}>Ya existe un inventario con ese nombre.</p>}
            </div>
          )}

          {trabajando && (
            <div aria-live="polite">
              <div className="progreso"><span style={{ width: `${Math.round(Math.min(1, estado?.avance ?? 0.1) * 100)}%` }} /></div>
              <p className="quieto pequeno">{estado?.texto}</p>
            </div>
          )}
          <button className="boton" type="button" style={{ marginTop: 16 }}
            disabled={trabajando || !destinoListo || !resultado.lista.length || col.codigo < 0 || col.nombre < 0 || col.precio < 0}
            onClick={() => void publicar()}>
            {destino === "nuevo" ? "Crear inventario y publicar" : "Publicar en el inventario"}
          </button>
        </>
      )}
      {trabajando && !col && <p className="quieto pequeno" style={{ marginTop: 12 }}>{estado?.texto}</p>}
    </section>
  );
}
