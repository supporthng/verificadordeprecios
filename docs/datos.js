/* Almacenamiento del equipo (IndexedDB): precios, configuración y consultas por subir.
   Sobrevive a reinicios y funciona sin internet. */
(function (global) {
  "use strict";
  const NOMBRE = "verificador-precios";
  let abierta = null;

  function abrir() {
    if (abierta) return abierta;
    abierta = new Promise(function (ok, mal) {
      const r = indexedDB.open(NOMBRE, 2);   // 2: almacén de fotos de productos
      r.onupgradeneeded = function () {
        const db = r.result;
        if (!db.objectStoreNames.contains("kv")) db.createObjectStore("kv");
        if (!db.objectStoreNames.contains("registro")) db.createObjectStore("registro", { autoIncrement: true });
        if (!db.objectStoreNames.contains("fotos")) db.createObjectStore("fotos");
      };
      r.onsuccess = function () { ok(r.result); };
      r.onerror = function () { abierta = null; mal(r.error); };
    });
    return abierta;
  }

  function hacer(almacenes, modo, trabajo) {
    return abrir().then(function (db) {
      return new Promise(function (ok, mal) {
        const t = db.transaction(almacenes, modo);
        let resultado;
        t.oncomplete = function () { ok(resultado); };
        t.onerror = t.onabort = function () { mal(t.error || new Error("IndexedDB")); };
        trabajo(t, function (v) { resultado = v; });
      });
    });
  }

  /* Lee varias claves de una vez: {clave: valor}. */
  function leer(claves) {
    return hacer(["kv"], "readonly", function (t, fin) {
      const salida = {}, kv = t.objectStore("kv");
      claves.forEach(function (c) { kv.get(c).onsuccess = function (e) { salida[c] = e.target.result; }; });
      fin(salida);
    });
  }

  /* Guarda varias claves en UNA transacción: o se guarda todo o nada.
     Un valor null borra la clave. */
  function guardar(pares) {
    return hacer(["kv"], "readwrite", function (t) {
      const kv = t.objectStore("kv");
      Object.keys(pares).forEach(function (c) {
        if (pares[c] === null || pares[c] === undefined) kv.delete(c); else kv.put(pares[c], c);
      });
    });
  }

  function borrarTodo() {
    return hacer(["kv", "registro", "fotos"], "readwrite", function (t) {
      t.objectStore("kv").clear();
      t.objectStore("registro").clear();
      t.objectStore("fotos").clear();
    });
  }

  /* ---- Registro de consultas pendientes de subir ---- */
  function anotar(fila) {
    return hacer(["registro"], "readwrite", function (t) { t.objectStore("registro").add(fila); });
  }

  function pendientes(cantidad) {
    return hacer(["registro"], "readonly", function (t, fin) {
      const filas = [];
      t.objectStore("registro").openCursor().onsuccess = function (e) {
        const c = e.target.result;
        if (c && filas.length < cantidad) { filas.push({ id: c.key, fila: c.value }); c.continue(); }
      };
      fin(filas);
    });
  }

  function quitar(ids) {
    return hacer(["registro"], "readwrite", function (t) {
      const r = t.objectStore("registro");
      ids.forEach(function (id) { r.delete(id); });
    });
  }

  function contar() {
    return hacer(["registro"], "readonly", function (t, fin) {
      t.objectStore("registro").count().onsuccess = function (e) { fin(e.target.result); };
    });
  }

  /* No acumular sin límite si el equipo pasa meses sin internet. */
  function recortar(maximo) {
    return contar().then(function (n) {
      if (n <= maximo) return;
      return hacer(["registro"], "readwrite", function (t) {
        let sobran = n - maximo;
        t.objectStore("registro").openCursor().onsuccess = function (e) {
          const c = e.target.result;
          if (c && sobran > 0) { c.delete(); sobran--; c.continue(); }
        };
      });
    });
  }

  /* ---- Fotos de productos (archivo -> Blob) ---- */
  function fotoGuardar(archivo, blob) {
    return hacer(["fotos"], "readwrite", function (t) { t.objectStore("fotos").put(blob, archivo); });
  }
  function fotoLeer(archivo) {
    return hacer(["fotos"], "readonly", function (t, fin) {
      t.objectStore("fotos").get(archivo).onsuccess = function (e) { fin(e.target.result || null); };
    });
  }
  function fotoClaves() {
    return hacer(["fotos"], "readonly", function (t, fin) {
      t.objectStore("fotos").getAllKeys().onsuccess = function (e) { fin(e.target.result || []); };
    });
  }
  function fotoBorrar(archivos) {
    return hacer(["fotos"], "readwrite", function (t) {
      const f = t.objectStore("fotos");
      archivos.forEach(function (a) { f.delete(a); });
    });
  }

  global.BD = { leer: leer, guardar: guardar, borrarTodo: borrarTodo, anotar: anotar,
                pendientes: pendientes, quitar: quitar, contar: contar, recortar: recortar,
                fotoGuardar: fotoGuardar, fotoLeer: fotoLeer, fotoClaves: fotoClaves, fotoBorrar: fotoBorrar };
})(self);
