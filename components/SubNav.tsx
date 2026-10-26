import Link from "next/link";
import { SoloWeb } from "./EnApp";
import { supabaseServidor } from "@/lib/supabase/server";
import { estadoLicencia, fechaCorta, type DatosLicencia } from "@/lib/licencia";

const SECCIONES = [
  { clave: "resumen", texto: "Resumen", ruta: "" },
  { clave: "sucursales", texto: "Sucursales", ruta: "/sucursales" },
  { clave: "inventarios", texto: "Inventarios", ruta: "/inventarios" },
  { clave: "apariencia", texto: "Apariencia", ruta: "/apariencia" },
  { clave: "equipos", texto: "Equipos", ruta: "/equipos" },
  { clave: "usuarios", texto: "Usuarios", ruta: "/usuarios" },
] as const;

/** Pestañas del panel de un negocio (y el aviso si la plataforma lo suspendió). */
export async function SubNav({ slug, activa }: { slug: string; activa: string }) {
  const supabase = await supabaseServidor();
  const { data } = await supabase.from("negocios").select("plan, prueba_hasta, pagado_hasta, licencia").eq("slug", slug).maybeSingle();
  const lic = data ? estadoLicencia(data as DatosLicencia) : null;
  const licencia = (data as DatosLicencia | null)?.licencia ?? "";
  return (
    <>
    {lic?.estado === "suspendida" && (
      <p className="aviso error" role="alert">
        Este negocio está suspendido: puedes ver tus datos, pero no cambiarlos, y los verificadores no muestran precios.
        Comunícate con tu proveedor de Prezio.
      </p>
    )}
    {lic?.estado === "vencida" && (
      <p className="aviso error" role="alert">
        {(data as DatosLicencia).plan === "prueba" ? "Terminó tu prueba de 30 días." : `Tu licencia venció el ${fechaCorta(lic.vence!)}.`}{" "}
        Para seguir usando Prezio, realiza el pago a tu proveedor indicando tu licencia <strong>{licencia}</strong>. Mientras
        tanto puedes ver tus datos, pero no cambiarlos, y los verificadores no muestran precios.
      </p>
    )}
    {lic && !lic.bloqueado && lic.dias !== null && lic.dias <= 7 && (
      <p className="aviso nota" role="status">
        {lic.estado === "prueba" ? "Tu prueba termina" : "Tu licencia vence"} en {lic.dias} {lic.dias === 1 ? "día" : "días"} ({fechaCorta(lic.vence!)}).
        Realiza el pago a tu proveedor indicando tu licencia <strong>{licencia}</strong> para no interrumpir el servicio.
      </p>
    )}
    <nav className="subnav" aria-label="Secciones del negocio">
      {SECCIONES.map((s) => (
        <Link key={s.clave} href={`/n/${slug}${s.ruta}`} aria-current={activa === s.clave ? "page" : undefined}>
          {s.texto}
        </Link>
      ))}
      <SoloWeb><Link href={`/v/${slug}`} className="subnav-verificador" target="_blank">Abrir verificador ›</Link></SoloWeb>
    </nav>
    </>
  );
}
