#!/usr/bin/env python3
"""
barrido_gtin_duplicados.py — Busca artículos de Genexus que comparten GTIN
(o código de barras). Un GTIN repetido hace que la absorción de traza ANMAT
mande series al artículo equivocado (caso Densulin R: stock partido entre el
artículo bueno y un duplicado de la migración).

Solo lectura: recorre Almacén > Artículos y abre cada ficha en modo DSP.

Uso:
    python barrido_gtin_duplicados.py [--workers 4]
Salida: gtin_duplicados.xlsx + resumen por consola.
"""
import os
import re
import sys
import json
import asyncio
import argparse
from collections import defaultdict
from dotenv import load_dotenv
from playwright.async_api import async_playwright

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

load_dotenv()
BASE_URL = "http://192.168.0.35/fedafar"
USER = os.getenv("FEDAFAR_USER")
PASS = os.getenv("FEDAFAR_PASS")
AQUI = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(AQUI, "_gtin_cache.json")


async def login(page):
    await page.goto(f"{BASE_URL}/wwpbaseobjects.seclogin.aspx")
    await page.fill("#vSECUSERNAME", USER)
    await page.fill("#vSECUSERPASSWORD", PASS)
    await page.click("#BTNENTER")
    await page.wait_for_function("() => !location.href.includes('seclogin')", timeout=15000)


async def listar_ids(page):
    """Recorre todas las páginas del listado de artículos y junta
    {id: {codigo, nombre, existencia, familia}}."""
    await page.goto(f"{BASE_URL}/alm_articulosww.aspx")
    await page.wait_for_load_state("networkidle")
    filtro = page.locator("#vFILTERFULLTEXT")
    if await filtro.input_value():
        await filtro.fill("")
        await page.keyboard.press("Enter")
        await page.wait_for_load_state("networkidle")
    arts, pagina_ant = {}, None
    while True:
        await page.wait_for_timeout(600)
        filas = await page.evaluate("""() => Array.from(document.querySelectorAll('#GridContainerTbl tr')).slice(1).map(tr => {
            const a = tr.querySelector("a[href*='alm_articulosview.aspx']");
            const tds = Array.from(tr.querySelectorAll('td')).map(td => td.innerText.trim());
            return {href: a ? a.getAttribute('href') : null, tds};
        })""")
        for f in filas:
            m = re.search(r"\?(\d+)", f["href"] or "")
            if not m:
                continue
            t = f["tds"]  # [icons x3, ID, Codigo, Nombre, Existencia, FamId, Familia, SubId, Subfamilia, ...]
            arts[m.group(1)] = {"codigo": t[4], "nombre": t[5], "existencia": t[6], "familia": t[8]}
        txt = await page.evaluate("() => document.body.innerText")
        mp = re.search(r"Página (\d+) de (\d+)", txt)
        actual, total = (int(mp.group(1)), int(mp.group(2))) if mp else (1, 1)
        print(f"  listado: página {actual}/{total} — {len(arts)} artículos", flush=True)
        if actual >= total or actual == pagina_ant:
            break
        pagina_ant = actual
        sig = page.locator("text=Sig").last
        await sig.click()
        await page.wait_for_load_state("networkidle")
    return arts


async def leer_ficha(ctx, aid):
    page = await ctx.new_page()
    try:
        await page.goto(f"{BASE_URL}/alm_articulos.aspx?DSP,{aid}", timeout=30000)
        await page.wait_for_load_state("networkidle", timeout=30000)
        return await page.evaluate("""() => {
            const v = id => { const e = document.getElementById(id); if (!e) return null;
                              return e.type === 'checkbox' ? e.checked : e.value; };
            return {gtin: v('ARTICULOGTIN'), barras: v('ARTICULOCODIGOBARRAS'),
                    trazable: v('ARTICULOTRAZABLE'), activo: v('ARTICULOACTIVO')};
        }""")
    finally:
        await page.close()


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()

    cache = json.load(open(CACHE, encoding="utf-8")) if os.path.exists(CACHE) else {}
    async with async_playwright() as p:
        b = await p.chromium.launch(headless=True)
        ctx = await b.new_context()
        page = await ctx.new_page()
        await login(page)
        print("1) Juntando artículos del listado...")
        arts = await listar_ids(page)
        print(f"   {len(arts)} artículos.\n2) Leyendo GTIN de cada ficha...")

        pend = [a for a in arts if a not in cache]
        cola = asyncio.Queue()
        for a in pend:
            cola.put_nowait(a)
        hechos = 0

        async def worker():
            nonlocal hechos
            while not cola.empty():
                aid = await cola.get()
                for intento in range(2):
                    try:
                        cache[aid] = await leer_ficha(ctx, aid)
                        break
                    except Exception as e:
                        if intento == 1:
                            print(f"   (no pude leer {aid}: {e})")
                hechos += 1
                if hechos % 50 == 0:
                    print(f"   {hechos}/{len(pend)}", flush=True)
                    json.dump(cache, open(CACHE, "w", encoding="utf-8"))

        await asyncio.gather(*[worker() for _ in range(args.workers)])
        json.dump(cache, open(CACHE, "w", encoding="utf-8"))
        await b.close()

    # 3) Agrupar por GTIN y por código de barras (normalizando ceros a la izquierda)
    def norm(x):
        x = (x or "").strip()
        return x.lstrip("0") if x.isdigit() else x.upper()

    grupos = {"GTIN": defaultdict(list), "Cod. barras": defaultdict(list)}
    for aid, a in arts.items():
        f = cache.get(aid) or {}
        a.update(f, id=aid)
        if norm(f.get("gtin")):
            grupos["GTIN"][norm(f["gtin"])].append(a)
        if norm(f.get("barras")):
            grupos["Cod. barras"][norm(f["barras"])].append(a)
        # un GTIN que coincide con el código de barras de OTRO artículo también choca
    filas = []
    for tipo, g in grupos.items():
        for clave, lista in g.items():
            if len(lista) < 2:
                continue
            for a in lista:
                filas.append({"Tipo choque": tipo, "Valor": clave, "ID": a["id"], "Código": a["codigo"],
                              "Nombre": a["nombre"], "Existencia": a["existencia"], "Familia": a["familia"],
                              "GTIN": a.get("gtin"), "Cod. barras": a.get("barras"),
                              "Trazable": a.get("trazable"), "Activo": a.get("activo")})

    import pandas as pd
    df = pd.DataFrame(filas)
    out = os.path.join(AQUI, "gtin_duplicados.xlsx")
    df.to_excel(out, index=False)
    n_gtin = sum(1 for l in grupos["GTIN"].values() if len(l) > 1)
    n_bar = sum(1 for l in grupos["Cod. barras"].values() if len(l) > 1)
    print(f"\n=== RESUMEN ===\nArtículos revisados: {len(arts)}")
    print(f"GTIN compartidos: {n_gtin} grupos · Códigos de barras compartidos: {n_bar} grupos")
    print(f"Detalle: {out}")
    if not df.empty:
        print(df[df["Tipo choque"] == "GTIN"].to_string(index=False, max_colwidth=45))


if __name__ == "__main__":
    asyncio.run(main())
