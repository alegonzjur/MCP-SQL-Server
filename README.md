# mcp-sql-server

Servidor MCP (Model Context Protocol) genérico de **solo lectura** sobre bases de datos SQL
(SQLite o PostgreSQL), construido con el SDK oficial de Python (`mcp`) y SQLAlchemy.

Es la evolución natural de `sql_tools.py` del proyecto **Marvel Intelligence Assistant**:
la misma lógica de guardrails (solo SELECT, whitelist de tablas, LIMIT forzado, timeout),
pero expuesta como **servidor MCP estándar** en vez de LangChain StructuredTools —
lo que significa que puede ser usado no solo por ese proyecto, sino por Claude Desktop,
Claude Code o cualquier otro cliente compatible con MCP, sin reescribir nada.

## Tools expuestas

| Tool | Descripción |
|---|---|
| `list_tables` | Lista las tablas disponibles (respetando whitelist si está configurada) |
| `describe_table(table_name)` | Devuelve columnas y tipos de una tabla |
| `run_query(sql, limit)` | Ejecuta un SELECT de solo lectura y devuelve resultado en tabla |

## Guardrails aplicados

1. Solo se permiten sentencias `SELECT` (bloquea INSERT/UPDATE/DELETE/DROP/ALTER/etc.)
2. No se permiten múltiples sentencias en una misma query
3. Whitelist opcional de tablas accesibles vía `ALLOWED_TABLES`
4. `LIMIT` forzado si el usuario no lo especifica (con tope máximo configurable)
5. Timeout de ejecución por query

## Instalación

```bash
python -m venv venv
# Windows: venv\Scripts\activate
source venv/bin/activate
pip install -r requirements.txt
```

## Configuración (variables de entorno)

| Variable | Descripción | Por defecto |
|---|---|---|
| `DB_URL` | Cadena de conexión SQLAlchemy | `sqlite:///./marvel.db` |
| `ALLOWED_TABLES` | Tablas permitidas, separadas por coma | todas |
| `QUERY_TIMEOUT_S` | Timeout por query (segundos) | `10` |
| `DEFAULT_LIMIT` | Límite de filas por defecto | `50` |
| `MAX_LIMIT` | Límite máximo de filas | `500` |

Ejemplos de `DB_URL`:
- SQLite: `sqlite:///C:/ruta/a/marvel.db`
- PostgreSQL: `postgresql+psycopg2://usuario:password@localhost:5432/mi_bd`

## Probar contra tu `marvel.db` real

```bash
export DB_URL="sqlite:///C:/ruta/a/tu/marvel.db"   # Windows: usa la sintaxis de tu shell
python server.py
```

## Conectarlo a Claude Desktop

Añade esto a tu `claude_desktop_config.json`
(Windows: `%APPDATA%\Claude\claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "sql-readonly": {
      "command": "C:\\ruta\\a\\mcp-sql-server\\venv\\Scripts\\python.exe",
      "args": ["C:\\ruta\\a\\mcp-sql-server\\server.py"],
      "env": {
        "DB_URL": "sqlite:///C:/ruta/a/marvel.db"
      }
    }
  }
}
```

Reinicia Claude Desktop y podrás preguntarle directamente sobre tu base de datos
("¿qué tablas hay?", "dime las 5 películas con más ingresos") usando estas tools.

## Relación con Marvel Intelligence Assistant

Este servidor reutiliza el mismo diseño de guardrails que `sql_guardrails.py` del proyecto
Marvel, pero desacoplado del router de LangChain. La idea de portfolio es poder decir:

> "Mi SQL agent en Marvel Intelligence Assistant usa LangChain StructuredTools de forma
> nativa. Además, construí una versión de esas mismas herramientas como servidor MCP
> independiente, reutilizable desde cualquier cliente compatible (Claude Desktop, Claude
> Code, u otros agentes), no solo desde mi router."

## Reutilización en otros proyectos (n8n + MCP + RAG)

Este mismo servidor (apuntando a otra BBDD  en vez de
Marvel) es la pieza de "datos estructurados en vivo" de otro proyecto combinado más adelante:
n8n dispara el flujo, el agente usa este MCP para consultar datos en tiempo real, y un
componente RAG aporta el contexto documental (informes técnicos, normativa) para el
análisis final.
