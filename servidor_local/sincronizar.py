"""Sincronización manual: simulación predeterminada; --apply actualiza Supabase."""
import argparse
import os
import sys
import requests
from sqlalchemy import text
from app import cfg, sql_connection, checked_select, normalize


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--apply',action='store_true',help='ACTUALIZA precios reales en Supabase')
    args=parser.parse_args()
    c=cfg()
    if c['engine'] in ('api_rest','supabase'):
        sys.exit('Sincronización masiva para API REST/Supabase no implementada: use una fuente SQL.')
    query=checked_select(c['sql_sync'])
    engine=sql_connection(c)
    try:
        with engine.connect() as conn:
            rows=[normalize(row) for row in conn.execute(text(query)).mappings()]
    finally:
        engine.dispose()
    rows=[r for r in rows if r['barcode']]
    if not rows:
        sys.exit('Sin productos. No se actualizó Supabase.')
    print(f'Productos encontrados: {len(rows)}')
    print('Muestra (máximo 3):',rows[:3])
    if not args.apply:
        print('SIMULACIÓN: no se modificó ningún producto. Use --apply para sincronizar.')
        return
    url=os.getenv('SUPABASE_URL','').rstrip('/')
    key=os.getenv('SUPABASE_SERVICE_ROLE_KEY','')
    if not url or not key:
        sys.exit('Faltan SUPABASE_URL y SUPABASE_SERVICE_ROLE_KEY en variables de entorno')
    if input('Escriba ACTUALIZAR para sobrescribir precios en Supabase: ') != 'ACTUALIZAR':
        sys.exit('Cancelado')
    headers={'apikey':key,'Authorization':'Bearer '+key,'Content-Type':'application/json','Prefer':'resolution=merge-duplicates,return=minimal'}
    batch_size=min(max(int(c.get('sync_batch_size',200)),1),500)
    for i in range(0,len(rows),batch_size):
        response=requests.post(url+'/rest/v1/products?on_conflict=barcode',json=rows[i:i+batch_size],headers=headers,timeout=30)
        response.raise_for_status()
        print('Sincronizados:',min(i+batch_size,len(rows)),'/',len(rows))
    print('Sincronización completada. No se eliminaron productos ausentes del origen.')


if __name__=='__main__':
    main()
