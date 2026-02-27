from typing import TypedDict

from pymysql.cursors import Cursor, DictCursor

from shared.utils.config import DB_HOST, DB_NAME, DB_PASSWORD, DB_PORT, DB_USER


class DBConfig(TypedDict, total=False):
    host: str
    user: str
    password: str
    database: str
    port: int
    charset: str
    cursorclass: type[Cursor]


DB_CONFIG: DBConfig = {
    "host": DB_HOST,
    "user": DB_USER,
    "password": DB_PASSWORD,
    "database": DB_NAME,
    "port": DB_PORT,
    "charset": "utf8mb4",
    "cursorclass": DictCursor,
}
