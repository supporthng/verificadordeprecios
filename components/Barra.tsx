import Link from "next/link";
import { Marca } from "./Marca";
import { BotonSalir, NavegacionApp, SoloWeb } from "./EnApp";
import { supabaseServidor } from "@/lib/supabase/server";

/** Barra superior del panel: logotipo, negocio actual y salir. «Cambiar de negocio» solo para quien tiene varios
 *  negocios (o la plataforma) y nunca dentro de la app Prezio Administrador, que es de un solo negocio. */
export async function Barra({ negocio }: { negocio?: { nombre: string; slug: string } }) {
  let variosNegocios = false;
  if (negocio) {
    const supabase = await supabaseServidor();
    const { data: quien } = await supabase.auth.getUser();
    if (quien.user) {
      const [{ count }, { data: plataforma }] = await Promise.all([
        supabase.from("miembros").select("negocio_id", { count: "exact", head: true }).eq("user_id", quien.user.id),
        supabase.rpc("es_plataforma"),
      ]);
      variosNegocios = (count ?? 0) > 1 || Boolean(plataforma);
    }
  }
  return (
    <header className="barra">
      <nav>
        <SoloWeb><Link href="/negocios" style={{ textDecoration: "none" }}><Marca tamano={24} /></Link></SoloWeb>
        <NavegacionApp />
        {negocio && <span className="chip">{negocio.nombre}</span>}
      </nav>
      <nav>
        {negocio && variosNegocios && <SoloWeb><Link className="boton secundario" href="/negocios">Cambiar de negocio</Link></SoloWeb>}
        <BotonSalir />
      </nav>
    </header>
  );
}
