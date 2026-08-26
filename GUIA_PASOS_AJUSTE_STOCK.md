# Guía de pasos — Automatización DIGIO (FEDAFAR) con Playwright

App detectada: **GeneXus Web** (`wwpbaseobjects.seclogin.aspx`, form `MAINFORM`, controles `vXXX`).
Implica: postbacks con estado de servidor (`__EVENTTARGET`, `GXState`), navegación por eventos JS,
IDs estables pero **sin** `data-testid`. Los `waitFor` van por red/DOM, no por `sleep`.

Base URL: `http://192.168.0.35/fedafar/`
Stack propuesto: **Python + Playwright (sync API)** — decime si lo preferís en JS/TS y lo reescribo.

---

## PASO 1 — Entrar a la web

**Acción:** abrir la pantalla de login.

| Dato | Valor |
|---|---|
| URL | `http://192.168.0.35/fedafar/wwpbaseobjects.seclogin.aspx` |
| Espera | `wait_until="networkidle"` + `vSECUSERNAME` visible |
| Requisito de red | La IP es LAN → el script corre en una máquina dentro de la red (o con VPN) |

```python
page.goto(f"{BASE}wwpbaseobjects.seclogin.aspx", wait_until="networkidle")
page.wait_for_selector("#vSECUSERNAME", state="visible")
```

---

## PASO 2 — Cargar credenciales

**Acción:** completar usuario/contraseña y enviar.

Selectores confirmados leyendo el DOM real:

| Campo | Selector | Notas |
|---|---|---|
| Usuario | `#vSECUSERNAME` | `input[type=text]`, placeholder "Usuario" |
| Contraseña | `#vSECUSERPASSWORD` | `input[type=password]` |
| Botón | `#BTNENTER` | `input[type=button]` value "Iniciar sesión" → dispara postback JS, **no** es submit nativo |
| Form | `#MAINFORM` | method POST a la misma URL |

```python
import os
page.fill("#vSECUSERNAME", os.environ["DIGIO_USER"])
page.fill("#vSECUSERPASSWORD", os.environ["DIGIO_PASS"])
with page.expect_navigation(wait_until="networkidle"):
    page.click("#BTNENTER")
# verificación de login OK
assert "seclogin" not in page.url, "Login falló (sigue en la pantalla de login)"
```

**Credenciales:** van por variables de entorno o `.env` (nunca hardcodeadas en el script ni en este doc).

```bash
export DIGIO_USER="facu_usuario"
export DIGIO_PASS="********"
```

> Opcional recomendado: guardar la sesión una sola vez con
> `context.storage_state(path="digio_auth.json")` y reusarla en corridas siguientes
> (`browser.new_context(storage_state="digio_auth.json")`), así no re-logueás en cada ejecución.

---

## PASO 3 — Ir a "Almacén"

**Hallazgo clave:** "Almacén" **no es una página**, es un *dropdown* del menú lateral. No navega a ningún lado
por sí solo — hay que abrirlo y elegir un submenú. Y lo mejor: **cada submenú es un link con `href` real**,
así que en Playwright conviene ir **directo por URL** en vez de simular clicks en el menú (más rápido y no depende de hovers/animaciones).

### Selector del menú (si querés hacerlo por click)

```python
page.click("a.menu-dropdown:has-text('Almacén')")          # abre el dropdown
page.click("a[href='alm_articulosww.aspx']")               # elige el submenú
```

### Alternativa recomendada: navegación directa

```python
page.goto(f"{BASE}alm_articulosww.aspx", wait_until="networkidle")
```

### Submenús disponibles bajo Almacén

| Submenú | URL | Nivel |
|---|---|---|
| Artículos | `alm_articulosww.aspx` | 1 |
| Movimientos de Stock | `alm_movimientosstockww.aspx` | 1 |
| Lotes de Artículos | `alm_articulosdepositostockww.aspx` | 1 |
| **Reportes** ▸ | *(dropdown)* | 1 |
| ├ Artículos Por Depósito | `alm_articulospordeposito.aspx` | 2 |
| ├ Movimientos de Artículos | `alm_movimientoarticulosreporte.aspx` | 2 |
| └ Medicamentos por Vencer | `alm_medicamentosporvencer.aspx` | 2 |
| **Configuración** ▸ | *(dropdown)* | 1 |
| ├ Depósitos | `alm_depositosww.aspx` | 2 |
| ├ Familias de Artículos | `alm_familiasww.aspx` | 2 |
| ├ Tipos de Artículos | `alm_tipoarticuloww.aspx` | 2 |
| ├ Tipos de Movimiento de Stock | `alm_tipomovimientostockww.aspx` | 2 |
| ├ Laboratorios | `alm_laboratoriosww.aspx` | 2 |
| └ Tipos de Venta de M… | *(truncado — lo confirmo si lo necesitás)* | 2 |

> Nota: los submenús de nivel 2 están dentro de dropdowns anidados ("Reportes", "Configuración"),
> así que por click harían falta **dos** aperturas. Otro motivo para ir por URL directa.

---

## PASO 4 — Movimientos de Stock

**URL directa:** `alm_movimientosstockww.aspx` — title `Movimientos de Stock`
Es un **Work With** de GeneXus: barra de búsqueda + filtros dinámicos + grilla paginada.

```python
page.goto(f"{BASE}alm_movimientosstockww.aspx", wait_until="networkidle")
page.wait_for_selector("#GridContainerTbl tr", state="visible")
```

### Controles de la pantalla

| Control | Selector | Notas |
|---|---|---|
| Buscar (texto libre) | `#vFILTERFULLTEXT` | placeholder "Buscar" |
| Agregar (alta) | `#BTNINSERT` | botón "Agregar" |
| Grilla | `#GridContainerTbl` | fila 0 = headers |
| Paginación | `input[type=number]` (sin id) | nro. de página |

### Filtros dinámicos (hay 3 slots: sufijo `1`, `2`, `3`)

Cada slot funciona igual, sólo cambia el número final:

| Control | Selector (slot 1) | Valores |
|---|---|---|
| Campo a filtrar | `#vDYNAMICFILTERSSELECTOR1` | `MOVSTOCKFECHA` (Fecha) · `TIPOMOVSTOCKDESCRIPCION` (Tipo Movimiento) |
| Operador | `#vDYNAMICFILTERSOPERATOR1` | `0` = Período |
| Fecha desde | `#vMOVSTOCKFECHA1` | máscara `dd/mm/aaaa` |
| Fecha hasta | `#vMOVSTOCKFECHA_TO1` | máscara `dd/mm/aaaa` |
| Tipo movimiento | `#vTIPOMOVSTOCKDESCRIPCION1` | texto libre |

```python
# ejemplo: filtrar por rango de fechas
page.select_option("#vDYNAMICFILTERSSELECTOR1", "MOVSTOCKFECHA")
page.fill("#vMOVSTOCKFECHA1", "01/08/2026")
page.fill("#vMOVSTOCKFECHA_TO1", "26/08/2026")
page.keyboard.press("Tab")            # dispara el postback del filtro
page.wait_for_load_state("networkidle")
```

> ⚠️ **Campos de fecha:** vienen con máscara (`  /  /    `). Si `fill()` no la respeta,
> usar `page.type("#vMOVSTOCKFECHA1", "01082026", delay=50)` (sólo dígitos) y verificar el valor resultante.
> ⚠️ **Postbacks:** los filtros de GeneXus disparan refresh al perder foco (`Tab`) o al cambiar el select.
> Siempre esperar `networkidle` después de tocar un filtro, nunca encadenar dos `fill` sin esperar.

### Columnas de la grilla

`Nro.` · `Fecha` · `Id` · `Depósito` · `Id` · `Tipo Mov.` · `Detalle` · `Usuario`
(Los headers traen texto de ordenamiento pegado, ej. `"FechaOrdenar de A a Z"` → **limpiar al parsear**.)

Fila de ejemplo real:
`10067 | 26/08/2026 | 1 | DEPOSITO | 2 | EGRESO | stock | miguel FARFAN`

```python
def leer_filas(page):
    filas = []
    for tr in page.query_selector_all("#GridContainerTbl tr")[1:]:
        celdas = [td.inner_text().strip() for td in tr.query_selector_all("td")]
        if celdas and celdas[3:]:
            filas.append({
                "nro": celdas[3], "fecha": celdas[4], "dep_id": celdas[5],
                "deposito": celdas[6], "tipo_id": celdas[7], "tipo_mov": celdas[8],
                "detalle": celdas[9], "usuario": celdas[10],
            })
    return filas
```
> Las 3 primeras celdas de cada fila están vacías (columnas de acción/iconos) — de ahí que el parseo arranque en el índice 3.

---

## PASO 5 — Click en "Agregar" (alta de movimiento)

```python
with page.expect_navigation(wait_until="networkidle"):
    page.click("#BTNINSERT")
assert "alm_movimientosstock.aspx" in page.url
```

Abre: `alm_movimientosstock.aspx?INS,0` — title **"Ajustes de Stock"**
Es el formulario de alta (modo INS). Tiene **cabecera + grilla de detalle de 5 renglones**.

### Cabecera

| Campo | Selector | Tipo | Default / Valores |
|---|---|---|---|
| Nro. | `#MOVSTOCKID` | text | `0` (lo asigna el sistema — **no tocar**) |
| Fecha | `#MOVSTOCKFECHA` | text | precargado con hoy (`26/08/2026`) |
| Tipo Movimiento | `#TIPOMOVSTOCKID` | select | `0`=(Ninguno) · `1`=INGRESO · `2`=EGRESO · `3`=DEVOLUCION DE ENTREGAS · `4`=DESCARTE POR VENCIMIENTO |
| Tipo | `#TIPOMOVSTOCKTIPO` | select | `I`=Ingreso · `E`=Egreso — **se autocompleta** al elegir Tipo Movimiento |
| Depósito | `#DEPOSITOID` | select | `0`=(Ninguno) · `1`=DEPOSITO |
| Detalle | `#MOVSTOCKDETALLE` | text | libre |

### Detalle — 5 renglones (sufijo `_0001` … `_0005`)

| Campo | Selector (renglón 1) |
|---|---|
| Artículo | `#vARTICULOID_0001` |
| Lote / stock | `#ARTICULODEPOSITOSTOCKID_0001` (select, **se puebla dinámicamente** al cargar el artículo) |
| Cantidad | `#MOVSTOCKDETCANTIDAD_0001` (default `0`) |

```python
def cargar_renglon(page, i, articulo_id, cantidad, lote=None):
    s = f"_{i:04d}"
    page.fill(f"#vARTICULOID{s}", str(articulo_id))
    page.keyboard.press("Tab")                  # postback: valida artículo y puebla el select de lote
    page.wait_for_load_state("networkidle")
    if lote:
        page.select_option(f"#ARTICULODEPOSITOSTOCKID{s}", str(lote))
        page.wait_for_load_state("networkidle")
    page.fill(f"#MOVSTOCKDETCANTIDAD{s}", str(cantidad))
    page.keyboard.press("Tab")
    page.wait_for_load_state("networkidle")
```

### Botones de la transacción

| Botón | Selector | Efecto |
|---|---|---|
| Confirmar | `#BTNTRN_ENTER` | **graba el movimiento — irreversible, impacta stock** |
| Cancelar | `#BTNTRN_CANCEL` | descarta y vuelve al Work With |
| Eliminar | `#BTNTRN_DELETE` | borra (sólo en modo update) |

> ⚠️ **`ARTICULODEPOSITOSTOCKID_000X` arranca vacío** (`opts: []`). Sólo se llena después del postback
> que dispara la carga del artículo. Si el script hace `select_option` antes, falla. Por eso el `Tab` + espera.
> ⚠️ **`#TIPOMOVSTOCKTIPO` no se setea a mano**: lo define el Tipo Movimiento elegido. Setearlo puede
> quedar pisado por el postback.
> ⚠️ **`#BTNTRN_ENTER` es el punto de no retorno.** En desarrollo, correr siempre con `DRY_RUN=1`
> y frenar antes de ese click (o cerrar con `#BTNTRN_CANCEL`) hasta validar el flujo completo.

---

## PASO 6 — Cabecera por TAB (probado en vivo ✅)

**Regla de oro del sistema (confirmada):** en GeneXus el `TAB` no sólo mueve el foco —
dispara el `onblur` que **commitea el valor y ejecuta las reglas del servidor**.
Cambiar un valor por JS/`fill()` **sin** el TAB posterior = el sistema no se entera.

### Orden de TAB real medido

Trazando `focusin` mientras se presionaba TAB:

| # | Foco | Nota |
|---|---|---|
| — | `#MOVSTOCKFECHA` | punto de partida (viene con la fecha de hoy) |
| TAB 1 | `#TIPOMOVSTOCKID` | Tipo Movimiento |
| TAB 2 | `#DEPOSITOID` | Depósito (ya viene en DEPOSITO) |
| TAB 3 | `#MOVSTOCKDETALLE` | Detalle |
| TAB 4 | `#vARTICULOID_0001` | **primera fila de Artículo** |

> **`#TIPOMOVSTOCKTIPO` (campo "Tipo") NO está en el orden de TAB** — es readonly.
> Se autocompleta solo: al elegir EGRESO + TAB, pasó a `E` / "Egreso" sin intervención.

### Secuencia probada

1. Foco en Fecha → **TAB** → Tipo Movimiento
2. Seleccionar **EGRESO** (`value="2"`) → **TAB**
   → verificado: `TIPOMOVSTOCKID=2`, `TIPOMOVSTOCKTIPO=E` ✅
3. **TAB** (saltea Depósito, queda `1`=DEPOSITO) → Detalle
4. Escribir **`BALANCE IA DIARIO`** → **TAB**
   → verificado: `MOVSTOCKDETALLE="BALANCE IA DIARIO"` ✅
5. Foco queda en `#vARTICULOID_0001` ✅ — listo para cargar el primer artículo

### Código Playwright equivalente

```python
DETALLE_FIJO = "BALANCE IA DIARIO"

def cargar_cabecera(page, tipo_mov="2"):      # "2" = EGRESO
    page.focus("#MOVSTOCKFECHA")
    page.keyboard.press("Tab")                 # -> Tipo Movimiento
    page.select_option("#TIPOMOVSTOCKID", tipo_mov)
    page.keyboard.press("Tab")                 # commit -> autocompleta "Tipo"
    page.wait_for_load_state("networkidle")
    assert page.input_value("#TIPOMOVSTOCKTIPO") == "E", "El tipo no se autocompletó"

    page.keyboard.press("Tab")                 # Depósito -> Detalle
    page.keyboard.type(DETALLE_FIJO)
    page.keyboard.press("Tab")                 # commit -> foco a fila 1
    page.wait_for_load_state("networkidle")

    assert page.evaluate("document.activeElement.id") == "vARTICULOID_0001"
```

> 💡 **Mantener el manejo por teclado, no por click.** Emular el TAB reproduce exactamente
> el flujo que dispara las reglas del servidor. Setear valores por `fill()` salteándose el TAB
> es la causa #1 de que estos formularios graben incompletos.

> ⚠️ **Campos obligatorios:** Tipo Movimiento y Detalle están marcados con `*`. Al tabular
> con Tipo Movimiento en "(Ninguno)", el sistema **devolvió el foco** a ese campo automáticamente.
> Buen chequeo defensivo: después de cada TAB, verificar dónde quedó el foco.

---

## PASO 7 — (pendiente): carga de artículo + lote + cantidad en la fila
