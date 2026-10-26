import Link from "next/link";
import type { Metadata } from "next";

export const metadata: Metadata = { title: "Política de privacidad · Prezio" };

export default function Privacidad() {
  return (
    <main className="contenido" style={{ maxWidth: 720 }}>
      <h1>Política de privacidad</h1>
      <p className="quieto pequeno">Última actualización: 26 de octubre de 2026</p>

      <h2>Qué es Prezio</h2>
      <p>Prezio permite a un comercio mostrar a sus clientes el precio de un producto al escanear su código de barras.</p>

      <h2>Qué datos guardamos</h2>
      <p>
        De cada negocio guardamos su nombre, sus sucursales, la lista de productos (código, nombre y precio), los
        usuarios que lo administran (correo y nombre) y el estado de sus equipos verificadores. También guardamos un
        conteo de las consultas de precios, sin datos personales de quien consulta.
      </p>

      <h2>Google Drive</h2>
      <p>
        Si eliges un archivo desde Google Drive, Prezio solicita únicamente el permiso <strong>drive.file</strong>: solo
        puede ver el archivo que tú eliges, nunca el resto de tu Drive. Ese permiso es temporal, dura cerca de una hora
        y no se guarda. Prezio lee el archivo para cargar sus precios. Si lo compartes por enlace para que se actualice
        solo, Prezio vuelve a leerlo periódicamente. Puedes dejar de compartirlo en Google Drive cuando quieras.
      </p>
      <p>
        El uso que Prezio hace de la información recibida de las API de Google cumple con la{" "}
        <a href="https://developers.google.com/terms/api-services-user-data-policy" target="_blank" rel="noopener noreferrer">
          Política de datos de usuario de los servicios de API de Google
        </a>
        , incluidos los requisitos de uso limitado.
      </p>

      <h2>Claves de bases de datos</h2>
      <p>
        Las claves de las bases de datos del comercio se guardan cifradas en el equipo donde se conectan y nunca se
        envían a Prezio.
      </p>

      <h2>Uso y compartición</h2>
      <p>
        Usamos los datos solo para prestar el servicio. No los vendemos ni los compartimos con terceros, salvo con los
        proveedores técnicos necesarios para operar Prezio (alojamiento y base de datos).
      </p>

      <h2>Tus derechos</h2>
      <p>Puedes pedir en cualquier momento que corrijamos o eliminemos los datos de tu negocio escribiendo a tu proveedor de Prezio.</p>

      <p style={{ marginTop: 28 }}><Link href="/">‹ Volver a Prezio</Link></p>
    </main>
  );
}
