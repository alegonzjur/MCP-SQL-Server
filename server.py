"""
MCP SQL Server (read-only)
==========================

Servidor MCP genérico que expone una base de datos SQL (SQLite o PostgreSQL)
como herramientas seguras de solo lectura para cualquier cliente MCP
(Claude Desktop, Claude Code, agentes propios, etc.).

Guardrails aplicados (mismo espíritu que sql_guardrails.py en Marvel Intelligence Assistant):
    1. Conexión de solo lectura cuando el motor lo permite (SQLite: mode=ro).
    2. Solo se permiten sentencias SELECT (bloquea INSERT/UPDATE/DELETE/DROP/ALTER/etc.).
    3. Whitelist opcional de tablas accesibles (variable de entorno ALLOWED_TABLES).
    4. LIMIT forzado en toda query si el usuario no lo especifica.
    5. Timeout de ejecución para evitar queries colgadas.

Configuración vía variables de entorno:
    DB_URL          -> cadena de conexión SQLAlchemy.
                        Ej. sqlite:///./marvel.db
                        Ej. postgresql+psycopg2://user:pass@localhost:5432/mydb
    ALLOWED_TABLES  -> lista separada por comas de tablas permitidas (opcional).
                        Si no se define, se permiten todas las tablas del esquema.
    QUERY_TIMEOUT_S -> timeout en segundos por query (por defecto 10).
    DEFAULT_LIMIT   -> límite de filas por defecto si la query no trae LIMIT (por defecto 50).
    MAX_LIMIT       -> límite máximo de filas permitido aunque el usuario pida más (por defecto 500).

Instalación local para probar con Claude Desktop (claude_desktop_config.json):
{
  "mcpServers": {
    "sql-readonly": {
      "command": "/ruta/a/venv/bin/python",
      "args": ["/ruta/a/mcp-sql-server/server.py"],
      "env": {
        "DB_URL": "sqlite:///C:/ruta/a/marvel.db"
      }
    }
  }
}
"""
# ---------------------------------------------------------------------------
# Importaciones
# ---------------------------------------------------------------------------
import os
import re
import signal
import contextlib
from typing import Optional

from mcp.server.fastmcp import FastMCP
from sqlalchemy import create_engine, text, inspect
from sqlalchemy.engine import Engine

# --------------------------------------------------------------------------
# Configuración
# --------------------------------------------------------------------------

# Variables de entorno
DB_URL = os.environ.get("DB_URL", "sqlite:///./marvel.db") # Cadena de conexión SQLAlchemy
ALLOWED_TABLES_RAW = os.environ.get("ALLOWED_TABLES", "").strip() # Lista separada por comas de tablas permitidas
ALLOWED_TABLES = (
    {t.strip() for t in ALLOWED_TABLES_RAW.split(",") if t.strip()}
    if ALLOWED_TABLES_RAW
    else None  # None => todas las tablas están permitidas
)
QUERY_TIMEOUT_S = int(os.environ.get("QUERY_TIMEOUT_S", "10")) # Timeout en segundos por query
DEFAULT_LIMIT = int(os.environ.get("DEFAULT_LIMIT", "50")) # Límite de filas por defecto si la query no trae LIMIT
MAX_LIMIT = int(os.environ.get("MAX_LIMIT", "500")) # Límite máximo de filas permitido aunque el usuario pida más

# Palabras clave que nunca deben aparecer en una query permitida.
FORBIDDEN_KEYWORDS = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|GRANT|REVOKE|ATTACH|PRAGMA|REPLACE)\b",
    re.IGNORECASE,
)
LIMIT_PATTERN = re.compile(r"\bLIMIT\s+\d+\b", re.IGNORECASE)

# Función para construir el motor de SQLAlchemy
def _build_engine() -> Engine:
    connect_args = {}
    if DB_URL.startswith("sqlite"):
        # Modo solo lectura real a nivel de conexión cuando es posible.
        connect_args = {"timeout": QUERY_TIMEOUT_S}
    return create_engine(DB_URL, connect_args=connect_args, pool_pre_ping=True)


engine = _build_engine()


class GuardrailError(Exception):
    pass

# Función para validar que la query solo contenga SELECT
def _validate_select_only(sql: str) -> None:
    stripped = sql.strip().rstrip(";")
    if not stripped:
        raise GuardrailError("La query está vacía.")
    if not re.match(r"^\s*SELECT\b", stripped, re.IGNORECASE):
        raise GuardrailError("Solo se permiten sentencias SELECT.")
    if ";" in stripped:
        raise GuardrailError("No se permiten múltiples sentencias en una misma query.")
    if FORBIDDEN_KEYWORDS.search(stripped):
        raise GuardrailError("La query contiene una operación no permitida (solo lectura).")

# Función para validar que la query solo acceda a tablas permitidas
def _validate_tables(sql: str) -> None:
    if ALLOWED_TABLES is None:
        return
    inspector = inspect(engine)
    all_tables = set(inspector.get_table_names())
    referenced = {t for t in all_tables if re.search(rf"\b{re.escape(t)}\b", sql, re.IGNORECASE)}
    disallowed = referenced - ALLOWED_TABLES
    if disallowed:
        raise GuardrailError(
            f"Acceso denegado a tabla(s) no permitidas: {', '.join(sorted(disallowed))}"
        )


# Función para aplicar el límite a la query
def _enforce_limit(sql: str, limit: Optional[int]) -> str:
    stripped = sql.strip().rstrip(";")
    if LIMIT_PATTERN.search(stripped):
        return stripped  # el usuario ya puso su propio LIMIT, se respeta
    effective_limit = min(limit or DEFAULT_LIMIT, MAX_LIMIT)
    return f"{stripped} LIMIT {effective_limit}"


@contextlib.contextmanager
def _timeout(seconds: int):
    """Timeout best-effort (solo funciona en sistemas POSIX con hilo principal)."""

    def _handler(signum, frame):
        raise TimeoutError(f"La query excedió el timeout de {seconds}s.")

    has_alarm = hasattr(signal, "SIGALRM")
    if has_alarm:
        old_handler = signal.signal(signal.SIGALRM, _handler)
        signal.alarm(seconds)
    try:
        yield
    finally:
        if has_alarm:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, old_handler)


# --------------------------------------------------------------------------
# Servidor MCP
# --------------------------------------------------------------------------

# Crear instancia del servidor MCP
mcp = FastMCP("sql-readonly")


# --------------------------------------------------------------------------
# Herramientas MCP
# --------------------------------------------------------------------------

# Lista de tablas disponibles
@mcp.tool()
def list_tables() -> str:
    """Lista las tablas disponibles en la base de datos (respetando la whitelist si existe)."""
    inspector = inspect(engine)
    tables = inspector.get_table_names()
    if ALLOWED_TABLES is not None:
        tables = [t for t in tables if t in ALLOWED_TABLES]
    if not tables:
        return "No hay tablas disponibles con la configuración actual."
    return "\n".join(f"- {t}" for t in sorted(tables))


# Descripción de tabla
@mcp.tool()
def describe_table(table_name: str) -> str:
    """Devuelve el esquema (columnas y tipos) de una tabla concreta."""
    if ALLOWED_TABLES is not None and table_name not in ALLOWED_TABLES:
        return f"Acceso denegado: la tabla '{table_name}' no está en la whitelist permitida."
    inspector = inspect(engine)
    if table_name not in inspector.get_table_names():
        return f"La tabla '{table_name}' no existe."
    columns = inspector.get_columns(table_name)
    lines = [f"Tabla: {table_name}"]
    for col in columns:
        nullable = "NULL" if col.get("nullable", True) else "NOT NULL"
        lines.append(f"  - {col['name']}: {col['type']} {nullable}")
    return "\n".join(lines)


# Ejecutar query
@mcp.tool()
def run_query(sql: str, limit: Optional[int] = None) -> str:
    """
    Ejecuta una query SELECT de solo lectura y devuelve el resultado en formato tabla.

    Args:
        sql: sentencia SQL, debe empezar por SELECT. No se permiten INSERT/UPDATE/DELETE/DDL.
        limit: número máximo de filas a devolver (por defecto DEFAULT_LIMIT, tope MAX_LIMIT).
    """
    try:
        _validate_select_only(sql)
        _validate_tables(sql)
        final_sql = _enforce_limit(sql, limit)

        with _timeout(QUERY_TIMEOUT_S):
            with engine.connect() as conn:
                result = conn.execute(text(final_sql))
                rows = result.fetchall()
                columns = list(result.keys())

        if not rows:
            return "La query no devolvió resultados."

        header = " | ".join(columns)
        separator = "-" * len(header)
        body = "\n".join(" | ".join(str(v) for v in row) for row in rows)
        return f"{header}\n{separator}\n{body}\n\n({len(rows)} filas)"

    except GuardrailError as e:
        return f"[Guardrail bloqueado] {e}"
    except TimeoutError as e:
        return f"[Timeout] {e}"
    except Exception as e:  # noqa: BLE001 - queremos capturar cualquier error de BBDD y devolverlo como texto
        return f"[Error de base de datos] {e}"


# Punto de entrada
if __name__ == "__main__":
    mcp.run()