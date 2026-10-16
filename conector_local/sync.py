"""Sincronizador unidireccional: origen local -> tabla products de Supabase.
No borra productos ni altera tablas del sistema de facturación.
"""
import argparse
import json
import logging
import os
import time
from decimal import Decimal
from pathlib import Path

import requests

LOG = logging.getLogger('fuentes')


def load_config(path):
    config = json.loads(Path(path).read_text(encoding='utf-8'))
    if config.get('source') not in ('sqlserver','mysql','postgresql','firebird','sqlite','access','rest'):
        raise ValueError('Fuente no admitida')
    return config


def env(name):
    value = os.environ.get(name, '').strip()
    if not value:
        raise ValueError('Falta la variable de entorno ' + name)
    return value


def get_connection(config):
    kind = config['source']
    if kind == 'sqlite':
        import sqlite3
        return sqlite3.connect(config['database'])
    if kind == 'sqlserver' or kind == 'access':
        import pyodbc
        return pyodbc.connect(env('SOURCE_ODBC_CONNECTION_STRING'), timeout=15)
    if kind == 'mysql':
        import pymysql
        return pymysql.connect(host=config['host'], port=int(config.get('port',3306)),
                                 user=env('SOURCE_DB_USER'), password=env('SOURCE_DB_PASSWORD'),
                                 database=config['database'], connect_timeout=15)
    if kind == 'postgresql':
        import psycopg
        return psycopg.connect(host=config['host'], port=int(config.get('port',5432)),
                              user=env('SOURCE_DB_USER'), password=env('SOURCE_DB_PASSWORD'),
                              dbname=config['database'], connect_timeout=15)
    if kind == 'firebird':
        import firebird.driver as driver
        return driver.connect(database=config['database'], host=config['host'],
                              user=env('SOURCE_DB_USER'), password=env('SOURCE_DB_PASSWORD'),
                              port=int(config.get('port',3050)))
    raise ValueError('Fuente no compatible con conexión SQL')


def fetch_products(config):
    if config['source'] == 'rest':
        headers = {'Accept':'application/json'}
        token = os.environ.get('SOURCE_API_TOKEN','').strip()
        if token:
            headers['Authorization'] = 'Bearer ' + token
        response = requests.get(config['api_url'], headers=headers, timeout=30)
        response.raise_for_status()
        items = response.json()
        if isinstance(items, dict):
            items = items[config.get('items_key','items')]
        if not isinstance(items, list):
            raise ValueError('La API debe devolver una lista de productos')
        fields = config.get('fields', {'barcode':'barcode','name':'name','price':'price'})
        for item in items:
            yield {k:item.get(v) for k,v in fields.items()}
        return
    query = config.get('query', '')
    if not query.lstrip().lower().startswith('select'):
        raise ValueError('La consulta debe empezar por SELECT (solo lectura)')
    connection = get_connection(config)
    try:
        cursor = connection.cursor()
        cursor.execute(query)
        columns = [c[0].lower() for c in cursor.description]
        for row in cursor:
            item = dict(zip(columns, row))
            yield {key:item.get(key) for key in ('barcode','name','price')}
    finally:
        connection.close()


def normalize(item):
    barcode = str(item.get('barcode') or '').strip()
    name = str(item.get('name') or '').strip()
    raw_price = item.get('price')
    if not barcode or not name or raw_price is None:
        return None
    try:
        price = Decimal(str(raw_price))
        if not price.is_finite() or price < 0:
            return None
    except Exception:
        return None
    return {'barcode':barcode, 'name':name, 'price':float(price)}


def upload(rows, dry_run=False):
    if dry_run:
        LOG.info('SIMULACIÓN: %s productos válidos; no se enviaron datos',len(rows))
        return
    base = env('SUPABASE_URL').rstrip('/')
    key = env('SUPABASE_SERVICE_ROLE_KEY')
    headers = {'apikey':key,'Authorization':'Bearer '+key,'Content-Type':'application/json',
               'Prefer':'resolution=merge-duplicates,return=minimal'}
    for start in range(0,len(rows),250):
        batch = rows[start:start+250]
        response = requests.post(base+'/rest/v1/products?on_conflict=barcode',
                                 json=batch,headers=headers,timeout=40)
        response.raise_for_status()
        LOG.info('Sincronizados %s de %s',min(start+len(batch),len(rows)),len(rows))


def run(config, dry_run=False):
    products = {}
    rejected = 0
    for raw in fetch_products(config):
        product = normalize(raw)
        if product:
            products[product['barcode']] = product
        else:
            rejected += 1
    rows = list(products.values())
    LOG.info('Origen leído: %s válidos, %s rechazados',len(rows),rejected)
    if not rows:
        raise ValueError('No se obtuvieron productos válidos; no se modificó Supabase')
    upload(rows,dry_run=dry_run)


def main():
    parser = argparse.ArgumentParser(description='Sincroniza precios locales hacia Supabase')
    parser.add_argument('--config',default='config.json')
    parser.add_argument('--dry-run',action='store_true')
    parser.add_argument('--every',type=int,default=0,help='Intervalo en minutos (0=una ejecución)')
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s')
    if args.every < 0:
        parser.error('--every debe ser >= 0')
    config = load_config(args.config)
    while True:
        try:
            run(config,args.dry_run)
        except Exception:
            LOG.exception('Falló la sincronización')
            if not args.every:
                raise SystemExit(1)
        if not args.every:
            break
        time.sleep(args.every*60)


if __name__ == '__main__':
    main()
