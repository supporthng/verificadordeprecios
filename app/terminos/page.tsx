import Link from "next/link";
import type { Metadata } from "next";

export const metadata: Metadata = { title: "Condiciones del servicio · Prezio" };

export default function Terminos() {
  return (
    <main className="contenido" style={{ maxWidth: 720 }}>
      <h1>Condiciones del servicio</h1>
      <p className="quieto pequeno">Última actualización: 26 de octubre de 2026</p>

      <h2>El servicio</h2>
      <p>
        Prezio ofrece a los comercios una herramienta para mostrar precios a sus clientes mediante verificadores y
        consulta desde el celular. El servicio se presta bajo la licencia contratada con tu proveedor de Prezio.
      </p>

      <h2>Tu responsabilidad</h2>
      <p>
        Eres responsable de que los precios y productos que cargas sean correctos, de la seguridad de tus claves de
        acceso y de tener derecho a usar los archivos y bases de datos que conectas.
      </p>

      <h2>Disponibilidad</h2>
      <p>
        Trabajamos para que el servicio esté siempre disponible, pero no garantizamos que funcione sin interrupciones.
        Prezio no se hace responsable de pérdidas causadas por precios mal cargados o por falta temporal del servicio.
      </p>

      <h2>Licencia y pagos</h2>
      <p>
        El uso de Prezio requiere una licencia vigente. Si vence o se suspende, podrás ver tus datos, pero no cambiarlos,
        y los verificadores dejarán de mostrar precios.
      </p>

      <h2>Cambios</h2>
      <p>Podemos actualizar estas condiciones. Los cambios importantes se avisarán en el panel.</p>

      <p style={{ marginTop: 28 }}><Link href="/privacidad">Política de privacidad</Link> · <Link href="/">‹ Volver a Prezio</Link></p>
    </main>
  );
}
