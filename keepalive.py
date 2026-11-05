"""
keepalive.py - Mantiene despierto el servicio de Render.

El plan free de Render duerme el servicio tras 15 minutos sin trafico, y el
arranque en frio (importar pandas, supabase, etc.) lo paga el primer cliente
que entra: por eso "la app tarda muchisimo en mostrar el catalogo".

Pega a /api/health, que es liviano y ademas dispara el precalentado del
catalogo en el worker, asi el cache ya esta armado cuando entra una farmacia.

Uso: python keepalive.py
Tarea programada: "FEDAFAR - Keepalive Render", cada 10 min de 8 a 20 hs.
"""
import sys
from datetime import datetime

URL = 'https://fedafar-tools.onrender.com/api/health'

def main():
    import time
    import requests
    t0 = time.time()
    sello = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    try:
        r = requests.get(URL, timeout=90)
        d = r.json() if r.ok else {}
        pre = d.get('precalentado', {})
        print(f"{sello}  {r.status_code}  {time.time()-t0:.1f}s  "
              f"cache={d.get('catalogo_en_cache')}  "
              f"precalentado={pre.get('estado')} {pre.get('detalle','')}")
        # Si tardo mucho, era un arranque en frio: lo dejamos anotado.
        if time.time() - t0 > 10:
            print(f"{sello}  [AVISO] respuesta lenta: el servicio estaba dormido.")
    except Exception as e:
        print(f"{sello}  ERROR tras {time.time()-t0:.1f}s: {type(e).__name__}: {e}")
        return 1
    return 0

if __name__ == '__main__':
    sys.exit(main())
