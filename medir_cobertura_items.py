"""
medir_cobertura_items.py — Cobertura del detalle de facturas pendientes.

Responde: de las facturas que una farmacia ve como pendientes en la app,
¿cuántas pueden mostrar sus productos? Es el dato que decide si el botón de
descarga del PDF se puede habilitar.

Uso:
    python medir_cobertura_items.py
"""
import os
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import api_app as A


def traer_todo(sb, tabla, select, filtro=None):
    """Pagina de a 1000: Supabase corta ahí y si no, se miden datos parciales."""
    out, off = [], 0
    while True:
        q = sb.table(tabla).select(select)
        if filtro:
            q = filtro(q)
        d = q.range(off, off + 999).execute().data or []
        out += d
        if len(d) < 1000:
            return out
        off += 1000


def main():
    sb = A.get_sb()

    pend = traer_todo(sb, 'cuenta_corriente',
                      'genexus_client_id,comprobante,genexus_factura_id,saldo',
                      lambda q: q.gt('saldo', 0))
    items = traer_todo(sb, 'comprobante_items', 'genexus_factura_id,item_num')
    clientes = {c['genexus_client_id']: c['nombre']
                for c in traer_todo(sb, 'clientes', 'genexus_client_id,nombre')
                if c.get('genexus_client_id')}

    por_factura = Counter(x['genexus_factura_id'] for x in items)
    con_items = set(por_factura)

    g = defaultdict(lambda: [0, 0, 0])   # [pendientes, con_detalle, renglones]
    for p in pend:
        k = p['genexus_client_id']
        g[k][0] += 1
        fid = p.get('genexus_factura_id')
        if fid in con_items:
            g[k][1] += 1
            g[k][2] += por_factura[fid]

    print('%-34s %7s %7s %9s %9s' % ('CLIENTE', 'PEND', 'C/DET', 'COBERT', 'RENGLONES'))
    print('-' * 70)
    for k, (t, c, r) in sorted(g.items(), key=lambda x: -x[1][0]):
        pct = f'{100*c/t:.0f}%' if t else '-'
        alerta = '  <-- SIN DETALLE' if c == 0 else ('' if c == t else '  <-- parcial')
        print('%-34s %7d %7d %9s %9d%s' % (clientes.get(k, f'cliente {k}')[:34], t, c, pct, r, alerta))
    print('-' * 70)
    tp = sum(v[0] for v in g.values())
    tc = sum(v[1] for v in g.values())
    print('%-34s %7d %7d %9s %9d' % ('TOTAL', tp, tc, f'{100*tc/tp:.0f}%' if tp else '-',
                                     sum(v[2] for v in g.values())))

    sin_id = [p for p in pend if not p.get('genexus_factura_id')]
    print(f'\npendientes sin ID interno de Genexus: {len(sin_id)}')
    for p in sin_id[:10]:
        print(f"   {p['comprobante']} (cliente {p['genexus_client_id']})")

    # ¿Quedó rastro del truncamiento en 15? Antes había un salto a 88 facturas
    # con exactamente 15 renglones y CERO por encima.
    dist = Counter(por_factura.values())
    print('\n--- renglones por factura (todas las facturas con detalle) ---')
    en_15 = dist.get(15, 0)
    mas_15 = sum(v for k, v in dist.items() if k > 15)
    for n in sorted(dist):
        marca = '  <-- sospechoso' if n == 15 and mas_15 == 0 else ''
        print('   %3d renglones -> %4d facturas%s' % (n, dist[n], marca))
    print(f'\n   con exactamente 15: {en_15}   |   con MAS de 15: {mas_15}')
    print('   ' + ('TRUNCAMIENTO RESUELTO (hay facturas de mas de 15)' if mas_15
                   else 'OJO: sigue sin haber ninguna de mas de 15'))


if __name__ == '__main__':
    main()
