"""
sync_cta_cte.py — Sincronización de estado de cuenta desde Genexus → Supabase

Uso:
    python sync_cta_cte.py 1248 1249 1250   # sincroniza esos clientes
    python sync_cta_cte.py --todos           # sincroniza todos los clientes activos en Supabase

Requisitos en .env:
    FEDAFAR_USER, FEDAFAR_PASS, SUPABASE_URL, SUPABASE_KEY
"""

import os
import re
import sys
import json
import time
import requests
import pandas as pd
from io import BytesIO
from typing import Optional
from datetime import datetime
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()

# ── Configuración ──────────────────────────────────────────────────────────────
BASE_URL     = "http://192.168.0.35/fedafar"
LOGIN_PATH   = "wwpbaseobjects.seclogin.aspx"
EXPORT_PATH  = "teso_comprobantesdecliente.aspx"
EXPORT_HASH  = "c01d04b1610243d2a2af23e7952e8b18c9c531f9d7a51341ad848140ec23a4e5"

FEDAFAR_USER = os.getenv("FEDAFAR_USER")
FEDAFAR_PASS = os.getenv("FEDAFAR_PASS")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")


# ── Sesión GeneXus ─────────────────────────────────────────────────────────────

class GeneXusSession:
    def __init__(self):
        self.http            = requests.Session()
        self.jwt             = None
        self.security_token  = None

    def _extract_security_token(self, html: str) -> str:
        """Busca el AJAX_SECURITY_TOKEN en el HTML (variable JS o hidden input)."""
        # Genexus suele exponerlo como: GxAjaxKey = "...";
        m = re.search(r'GxAjaxKey\s*=\s*["\']([^"\']+)["\']', html)
        if m:
            return m.group(1)
        # Alternativa: input hidden
        soup = BeautifulSoup(html, "html.parser")
        inp  = soup.find("input", {"name": re.compile("AJAX_SECURITY_TOKEN", re.I)})
        if inp:
            return inp.get("value", "")
        return ""

    def _extract_login_hash(self, html: str) -> str:
        """Extrae el hash del action del form de login en el HTML."""
        m = re.search(rf'{re.escape(LOGIN_PATH)}\?([a-f0-9]{{40,}})', html)
        if m:
            return m.group(1)
        # Si no encontramos, usamos el hash de exportación como fallback
        print("  [WARN] No se encontró hash de login en el HTML, usando fallback.")
        return EXPORT_HASH

    def login(self) -> bool:
        if not FEDAFAR_USER or not FEDAFAR_PASS:
            print("ERROR: FEDAFAR_USER o FEDAFAR_PASS no configurados en .env")
            return False

        print("Iniciando sesión en el sistema interno Fedafar...")

        # 1. GET página de login para obtener cookies iniciales y tokens
        try:
            r = self.http.get(f"{BASE_URL}/{LOGIN_PATH}", timeout=10)
            r.raise_for_status()
        except requests.RequestException as e:
            print(f"ERROR: No se pudo conectar al servidor interno: {e}")
            print("       Verificar que estás conectado a la red de Fedafar.")
            return False

        self.security_token = self._extract_security_token(r.text)
        login_hash          = self._extract_login_hash(r.text)

        # 2. POST login — patrón GeneXus AJAX estándar
        url  = f"{BASE_URL}/{LOGIN_PATH}?{login_hash},gx-no-cache={int(time.time()*1000)}"
        body = {
            "MPage":    False,
            "cmpCtx":   "",
            "parms":    [FEDAFAR_USER, FEDAFAR_PASS],
            "hsh":      [],
            "objClass": "wwpbaseobjects.seclogin",
            "pkgName":  "GeneXus.Programs",
            "events":   ["'ENTER'"],
            "grids":    {}
        }
        headers = {
            "GxAjaxRequest":      "1",
            "Content-Type":       "application/json",
            "AJAX_SECURITY_TOKEN": self.security_token,
        }

        try:
            r = self.http.post(url, json=body, headers=headers, timeout=10)
            r.raise_for_status()
        except requests.RequestException as e:
            print(f"ERROR en POST de login: {e}")
            return False

        # 3. Extraer JWT del body de respuesta
        try:
            data = r.json()
        except ValueError:
            print("ERROR: Respuesta de login no es JSON válido.")
            return False

        for cmd in data.get("gxCommands", []):
            if "setVar" in cmd and cmd["setVar"].get("varName") == "X-GXAUTH-TOKEN":
                self.jwt = cmd["setVar"]["value"]
                print("  Login exitoso.")
                return True

        # Revisar si hay mensaje de error en los comandos
        for cmd in data.get("gxCommands", []):
            if "setVar" in cmd:
                print(f"  setVar recibido: {cmd['setVar']}")

        print("ERROR: Login fallido. Verificar credenciales en .env")
        return False

    def export_cta_cte(self, genexus_client_id: int) -> Optional[pd.DataFrame]:
        """Exporta el estado de cuenta de un cliente y lo devuelve como DataFrame."""
        fecha_hasta = datetime.now().strftime("%Y/%m/%d 00:00:00")

        url  = f"{BASE_URL}/{EXPORT_PATH}?{EXPORT_HASH},gx-no-cache={int(time.time()*1000)}"
        body = {
            "MPage":    False,
            "cmpCtx":   "",
            "parms":    [False, genexus_client_id, "    /  /   00:00:00", fecha_hasta, True],
            "hsh":      [],
            "objClass": "teso_comprobantesdecliente",
            "pkgName":  "GeneXus.Programs",
            "events":   ["'DOUEXPORTAR'"],
            "grids":    {}
        }
        headers = {
            "GxAjaxRequest":      "1",
            "Content-Type":       "application/json",
            "AJAX_SECURITY_TOKEN": self.security_token,
            "X-GXAUTH-TOKEN":      self.jwt,
        }

        try:
            r = self.http.post(url, json=body, headers=headers, timeout=15)
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            print(f"    ERROR al solicitar exportación: {e}")
            return None

        # Extraer URL del .xlsx de la respuesta
        xlsx_rel_path = None
        for cmd in data.get("gxCommands", []):
            if "redirect" in cmd:
                xlsx_rel_path = cmd["redirect"]["url"]
                break

        if not xlsx_rel_path:
            print(f"    Sin archivo en respuesta para cliente {genexus_client_id}.")
            return None

        # GET inmediato del Excel (el servidor limpia el archivo temporal rápido)
        xlsx_url = f"{BASE_URL}/{xlsx_rel_path}"
        try:
            r2 = self.http.get(xlsx_url, timeout=10)
            if r2.status_code != 200:
                print(f"    ERROR descargando xlsx: HTTP {r2.status_code}")
                return None
        except requests.RequestException as e:
            print(f"    ERROR al descargar xlsx: {e}")
            return None

        # Parsear el Excel
        try:
            df = pd.read_excel(BytesIO(r2.content))
        except Exception as e:
            print(f"    ERROR leyendo Excel: {e}")
            return None

        # Normalizar nombres de columnas (por si el Excel tiene variantes)
        df.columns = [str(c).strip() for c in df.columns]
        print(f"    {len(df)} comprobantes encontrados.")
        return df


# ── Supabase ───────────────────────────────────────────────────────────────────

def get_supabase_client():
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("ERROR: SUPABASE_URL o SUPABASE_KEY no configurados en .env")
        return None
    from supabase import create_client
    return create_client(SUPABASE_URL, SUPABASE_KEY)


def upload_to_supabase(genexus_client_id: int, df: pd.DataFrame):
    """Reemplaza los comprobantes del cliente en Supabase con datos frescos."""
    sb = get_supabase_client()
    if not sb:
        return

    # Borrar registros anteriores del cliente
    sb.table("cuenta_corriente") \
      .delete() \
      .eq("genexus_client_id", genexus_client_id) \
      .execute()

    if df.empty:
        print(f"    Sin comprobantes para subir.")
        return

    # Mapeo flexible de columnas (el Excel puede traer nombres con variaciones)
    col_map = {
        "fecha_comprobante": ["Fecha de Comprobante", "FechaComprobante", "Fecha Comprobante"],
        "comprobante":       ["Comprobante"],
        "fecha_vencimiento": ["Fecha de Vencimiento", "FechaVencimiento", "Fecha Vencimiento"],
        "importe":           ["Importe"],
        "saldo":             ["Saldo"],
    }

    def find_col(df, candidates):
        for c in candidates:
            if c in df.columns:
                return c
        return None

    records = []
    now = datetime.now().isoformat()

    for _, row in df.iterrows():
        record = {"genexus_client_id": genexus_client_id, "actualizado_en": now}
        for field, candidates in col_map.items():
            col = find_col(df, candidates)
            if col:
                val = row[col]
                if field in ("importe", "saldo"):
                    try:
                        record[field] = float(val) if pd.notna(val) else 0.0
                    except (ValueError, TypeError):
                        record[field] = 0.0
                else:
                    record[field] = str(val) if pd.notna(val) else ""
            else:
                record[field] = 0.0 if field in ("importe", "saldo") else ""
        records.append(record)

    sb.table("cuenta_corriente").insert(records).execute()
    print(f"    {len(records)} registros subidos a Supabase.")


def get_all_client_ids() -> list:
    """Obtiene todos los genexus_client_id activos desde Supabase."""
    sb = get_supabase_client()
    if not sb:
        return []
    res = sb.table("clientes") \
            .select("genexus_client_id, nombre") \
            .eq("activo", True) \
            .not_.is_("genexus_client_id", "null") \
            .execute()
    return res.data or []


# ── Main ───────────────────────────────────────────────────────────────────────

def sync_clientes(client_ids: list):
    """Sincroniza una lista de IDs con una sola sesión (más eficiente)."""
    if not client_ids:
        print("Sin clientes para sincronizar.")
        return

    session = GeneXusSession()
    if not session.login():
        return

    total = len(client_ids)
    for i, cid in enumerate(client_ids, 1):
        print(f"[{i}/{total}] Sincronizando cliente {cid}...")
        df = session.export_cta_cte(cid)
        if df is not None:
            upload_to_supabase(cid, df)

    print(f"\nSincronización completada: {total} cliente(s).")


if __name__ == "__main__":
    args = sys.argv[1:]

    if not args:
        print(__doc__)
        sys.exit(0)

    if args[0] == "--todos":
        print("Obteniendo lista de clientes desde Supabase...")
        clientes = get_all_client_ids()
        if not clientes:
            print("No se encontraron clientes activos en Supabase.")
            sys.exit(1)
        ids = [c["genexus_client_id"] for c in clientes]
        print(f"Clientes a sincronizar: {[c['nombre'] for c in clientes]}")
        sync_clientes(ids)
    else:
        try:
            ids = [int(x) for x in args]
        except ValueError:
            print("ERROR: Los IDs deben ser números. Ej: python sync_cta_cte.py 1248 1249")
            sys.exit(1)
        sync_clientes(ids)
