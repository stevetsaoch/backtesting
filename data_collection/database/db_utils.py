import psycopg
from psycopg import sql


def create_parent_table(conn_str, schema: sql.SQL):
    with psycopg.connect(conn_str) as conn:
        with conn.cursor() as cur:
            cur.execute(schema)


def create_tables(conn_str, querys: list[sql.SQL]):
    for q in querys:
        with psycopg.connect(conn_str) as conn:
            with conn.cursor() as cur:
                cur.execute(q)
