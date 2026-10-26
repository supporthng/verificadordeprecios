"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { Pantalla, type EstadoPantalla } from "@/components/Pantalla";
import { supabaseNavegador } from "@/lib/supabase/browser";
import { variantes } from "@/lib/codigos";
import type { Apariencia } from "@/lib/apariencia";

type Props = { sucursalId: string; sucursal: string; negocio: string; slug: string; apariencia: Apariencia; moneda: string };
type Respuesta = { encontrado: boolean; codigo: string; nombre?: string; precio?: number | string; sin_fuente?: boolean };

/** Verificador en línea: el lector escribe el código + Enter en un cuadro invisible siempre activo. */
export function Verificador({ sucursalId, sucursal, negocio, slug, apariencia, moneda }: Props) {
  const [estado, setEstado] = useState<EstadoPantalla>({ tipo: "espera" });
  const [error, setError] = useState("");
  const [cerrado, setCerrado] = useState(false);
  const entrada = useRef<HTMLInputElement>(null);
  const temporizador = useRef<ReturnType<typeof setTimeout> | null>(null);
  const vez = useRef(0);
  const supabase = useRef(supabaseNavegador());

  const enfocar = useCallback(() => { entrada.current?.focus({ preventScroll: true }); }, []);
  useEffect(() => {
    enfocar();
    const t = setInterval(() => { if (document.activeElement !== entrada.current) enfocar(); }, 700);
    return () => clearInterval(t);
  }, [enfocar]);

  const volverLuego = (segundos: number) => {
    if (temporizador.current) clearTimeout(temporizador.current);
    temporizador.current = setTimeout(() => setEstado({ tipo: "espera" }), segundos * 1000);
  };

  /** Cierra el verificador sin pasar por el panel: sale de pantalla completa y cierra la ventana.
   *  Si el navegador no deja cerrarla (pestaña abierta a mano), queda una pantalla de «cerrado». */
  function cerrar() {
    if (temporizador.current) clearTimeout(temporizador.current);
    if (document.fullscreenElement) void document.exitFullscreen().catch(() => {});
    window.close();
    setTimeout(() => setCerrado(true), 250);
  }

  async function consultar(leido: string) {
    const codigo = leido.trim();
    if (!codigo || codigo.length > 64) return;
    setError("");
    setEstado({ tipo: "buscando", codigo });
    const { data, error: e } = await supabase.current.rpc("consultar_precio", {
      p_sucursal: sucursalId, p_formas: variantes(codigo).slice(0, 16),
    });
    if (e) {
      setEstado({ tipo: "espera" });
      setError(/JWT|session|auth/i.test(e.message) ? "La sesión venció: vuelve a entrar." : "Sin conexión. Intenta de nuevo.");
      volverLuego(6);
      return;
    }
    const r = data as Respuesta;
    if (r.encontrado) {
      vez.current += 1;
      setEstado({ tipo: "producto", codigo: r.codigo, nombre: r.nombre ?? "", precio: Number(r.precio) || 0, vez: vez.current });
      volverLuego(apariencia.segundos);
    } else {
      setEstado(r.sin_fuente ? { tipo: "sin_fuente", codigo } : { tipo: "no", codigo });
      volverLuego(6);
    }
  }

  return (
    <div className="verificador" onClick={enfocar}>
      <Pantalla apariencia={apariencia} moneda={moneda} negocio={negocio} sucursal={sucursal} estado={estado}>
        <input ref={entrada} className="pz-lector" aria-label="Código de barras" inputMode="none" autoComplete="off"
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              const v = e.currentTarget.value;
              e.currentTarget.value = "";
              void consultar(v);
            }
          }} />
      </Pantalla>
      {error && <p className="verificador-error" role="alert">{error}</p>}
      <div className="verificador-esquina">
        <button type="button" title="Cerrar" aria-label="Cerrar el verificador"
          onClick={(e) => { e.stopPropagation(); cerrar(); }}>✕</button>
        <button type="button" title="Pantalla completa" aria-label="Pantalla completa"
          onClick={(e) => { e.stopPropagation(); void document.documentElement.requestFullscreen?.().catch(() => {}); }}>⛶</button>
        <Link href={`/n/${slug}`} title="Volver al panel" aria-label="Volver al panel">⚙</Link>
      </div>
      {cerrado && (
        <div className="verificador-cerrado" role="dialog" aria-label="Verificador cerrado">
          <p>Verificador cerrado</p>
          <span>Ya puedes cerrar esta ventana.</span>
          <button type="button" onClick={(e) => { e.stopPropagation(); setCerrado(false); enfocar(); }}>Volver a abrir</button>
        </div>
      )}
    </div>
  );
}
