/* Formas equivalentes de un código de barras (copia exacta de shared.variantes_codigo).
   Un mismo producto puede estar guardado como UPC-E (8), UPC-A (12), EAN-13 (13)
   o sin los ceros iniciales que borra Excel: se prueban todas, la exacta primero. */
(function (global) {
  "use strict";

  function digitoControl(cuerpo) {
    let suma = 0;
    for (let i = 0; i < cuerpo.length; i++) {
      const d = +cuerpo[cuerpo.length - 1 - i];
      suma += d * (i % 2 === 0 ? 3 : 1);
    }
    return String((10 - (suma % 10)) % 10);
  }

  function esDigitos(t) { return /^\d+$/.test(t); }

  function upceAUpca(upce) {
    if (upce.length !== 8 || !esDigitos(upce) || "01".indexOf(upce[0]) < 0) return null;
    const ns = upce[0], d = upce.slice(1, 7), control = upce[7], ultimo = d[5];
    let cuerpo;
    if ("012".indexOf(ultimo) >= 0) cuerpo = d.slice(0, 2) + ultimo + "0000" + d.slice(2, 5);
    else if (ultimo === "3") cuerpo = d.slice(0, 3) + "00000" + d.slice(3, 5);
    else if (ultimo === "4") cuerpo = d.slice(0, 4) + "00000" + d[4];
    else cuerpo = d.slice(0, 5) + "0000" + ultimo;
    const upca = ns + cuerpo + control;
    return digitoControl(upca.slice(0, 11)) === control ? upca : null;
  }

  function upcaAUpce(upca) {
    if (upca.length !== 12 || !esDigitos(upca) || "01".indexOf(upca[0]) < 0) return [];
    const ns = upca[0], fab = upca.slice(1, 6), prod = upca.slice(6, 11), control = upca[11];
    const cand = [];
    if ("012".indexOf(fab[2]) >= 0 && fab.slice(3) === "00" && prod.slice(0, 2) === "00")
      cand.push(fab.slice(0, 2) + prod.slice(2, 5) + fab[2]);
    if (fab.slice(3) === "00" && prod.slice(0, 3) === "000") cand.push(fab.slice(0, 3) + prod.slice(3, 5) + "3");
    if (fab[4] === "0" && prod.slice(0, 4) === "0000") cand.push(fab.slice(0, 4) + prod[4] + "4");
    if (prod.slice(0, 4) === "0000" && "56789".indexOf(prod[4]) >= 0) cand.push(fab + prod[4]);
    return cand.map(function (d) { return ns + d + control; })
               .filter(function (e) { return upceAUpca(e) === upca; });
  }

  function variantes(codigo) {
    codigo = String(codigo == null ? "" : codigo).trim();
    let formas = [codigo];
    if (!esDigitos(codigo)) return formas;
    let upca = null;
    if (codigo.length === 13 && codigo[0] === "0") upca = codigo.slice(1);
    else if (codigo.length === 12) upca = codigo;
    else if (codigo.length === 8) upca = upceAUpca(codigo);
    if (upca) formas = formas.concat([upca, "0" + upca], upcaAUpce(upca));
    formas = formas.concat(formas.map(function (f) { return f.replace(/^0+/, ""); })
                                 .filter(function (f) { return f.length >= 6; }));
    const vistas = new Set(), unicas = [];
    formas.forEach(function (f) { if (f && !vistas.has(f)) { vistas.add(f); unicas.push(f); } });
    return unicas;
  }

  global.Codigos = { variantes: variantes, upceAUpca: upceAUpca, upcaAUpce: upcaAUpce };
})(typeof self !== "undefined" ? self : globalThis);
