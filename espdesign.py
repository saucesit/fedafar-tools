#!/usr/bin/env python3
"""
espdesign.py — Cliente de la API de ESPDesign (monitoreo de temperatura de la
cámara de frío). Login → token → getMainData. Devuelve el estado actual de cada
equipo/sensor: temperatura, última lectura, si está reportando y si tiene alerta.

API tipo RPC: POST https://espdesign.com.ar/api con {action, token, ...}.
Credenciales en .env: ESPDESIGN_USER / ESPDESIGN_PASS.
"""

import os, json, time
import requests

API = 'https://espdesign.com.ar/api'
_HDR = {'Content-Type': 'application/json'}
_token_cache = {'token': None, 'ts': 0}
_TTL = 600  # 10 min: reusar el token para no loguear en cada consulta


def _post(payload, timeout=20):
    r = requests.post(API, data=json.dumps(payload), headers=_HDR, timeout=timeout)
    r.raise_for_status()
    return r.json()


def _login():
    user = os.environ.get('ESPDESIGN_USER', '')
    clave = os.environ.get('ESPDESIGN_PASS', '')
    if not user or not clave:
        raise RuntimeError('Faltan ESPDESIGN_USER / ESPDESIGN_PASS en el entorno')
    d = _post({'action': 'login', 'usuario': user, 'clave': clave})
    if not d.get('success') or not d.get('token'):
        raise RuntimeError('Login ESPDesign fallido')
    return d['token']


def _get_token(forzar=False):
    now = time.time()
    if not forzar and _token_cache['token'] and (now - _token_cache['ts'] < _TTL):
        return _token_cache['token']
    tok = _login()
    _token_cache.update(token=tok, ts=now)
    return tok


def _llamar(action, extra=None, reintentar=True):
    """Llama una acción con el token; si el token venció, reloguea una vez."""
    payload = {'action': action, 'token': _get_token()}
    if extra:
        payload.update(extra)
    d = _post(payload)
    if d.get('success') is False and reintentar:
        payload['token'] = _get_token(forzar=True)
        d = _post(payload)
    return d


def estado_actual():
    """Estado en vivo de todos los equipos y sensores de la cámara de frío."""
    d = _llamar('getMainData', {'data': {}})
    equipos = []
    for m in d.get('machines', []):
        sensores, reportando = [], False
        for s in m.get('sensores', []):
            ld = s.get('last_data') or []
            fmt = (s.get('last_date_format') or '').strip()
            reporta = bool(fmt) and fmt.lower() != 'sin datos'
            if reporta:
                reportando = True
            nombre = (s.get('nombre_view') or s.get('nombre') or '').strip()
            sensores.append({
                'nombre':   nombre,
                'temp':     (ld[0] if ld else None) if reporta else None,
                'fecha':    fmt,
                'reporta':  reporta,
                'alerta':   bool(s.get('alerta')),
                'sin_uso':  'SIN USO' in nombre.upper(),
            })
        equipos.append({
            'nombre':     (m.get('nombre') or '').strip(),
            'uid':        m.get('uid'),
            'reportando': reportando,
            'sensores':   sensores,
        })
    rep = d.get('report') or {}
    return {'equipos': equipos, 'alertas': len(rep.get('alertas', []) or [])}


def machines():
    """Lista de equipos (getMachines). Cada uno: {_id, uid, nombre, ...}."""
    return _llamar('getMachines').get('data') or []


def historico(desde_iso, hasta_iso, machine):
    """Trae lecturas entre desde y hasta. OJO de la API de ESP: `machine` es
    OBLIGATORIO (sin él tira 500) aunque NO filtra (devuelve todos los equipos),
    y hay un tope de ~3000 filas por respuesta (las más recientes hasta `hasta`).
    Por eso el backfill se hace paginando hacia atrás con `hasta`.
    Cada fila: {id, fecha, dispositivo, nombre, sensor, valor}."""
    d = _llamar('getHistoryData', {'filter': {'desde': desde_iso, 'hasta': hasta_iso,
                                              'machine': machine}})
    return d.get('data') or []


if __name__ == '__main__':
    import sys
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    from dotenv import load_dotenv
    from pathlib import Path
    load_dotenv(Path(__file__).parent / '.env')
    est = estado_actual()
    print(f"Alertas: {est['alertas']}")
    for e in est['equipos']:
        estado = 'REPORTANDO' if e['reportando'] else 'SIN DATOS'
        print(f"\n[{estado}] {e['nombre']}")
        for s in e['sensores']:
            t = f"{s['temp']}°C" if s['temp'] is not None else '—'
            print(f"   {s['nombre']:26} {t:9} {s['fecha']}")
