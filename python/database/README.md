# Base de datos (SQL Server)

Persistencia de participantes, sesiones y pruebas en SQL Server 2022, vía `bd_sqlserver.py` (pyodbc puro, sin ORM). Ningún otro módulo del proyecto debe conectarse a la base directamente — todo pasa por `BaseDatosTesis`.

## 1. Instalar el ODBC Driver 17 for SQL Server

Windows normalmente ya trae un driver de SQL Server, pero **pyodbc necesita el "ODBC Driver 17 for SQL Server"** específicamente (o el 18). Para verificar si ya lo tienes instalado:

```bash
python -c "import pyodbc; print(pyodbc.drivers())"
```

Si `'ODBC Driver 17 for SQL Server'` no aparece en la lista, descárgalo e instálalo desde Microsoft:
https://learn.microsoft.com/sql/connect/odbc/download-odbc-driver-for-sql-server

(Instalador directo de 64 bits, el que corresponde a la mayoría de instalaciones de Python en Windows.)

## 2. Configurar el archivo `.env`

Las credenciales viven en un archivo `.env` en la **raíz del proyecto** (`C:\Tesis_Kevin\.env`), nunca en el código. Cópialo desde la plantilla:

```bash
cp C:/Tesis_Kevin/.env.example C:/Tesis_Kevin/.env
```

Y edítalo con tus datos reales:

```
DB_SERVER=DESKTOP-059IB6K\SQLEXPRESS
DB_DATABASE=TesisKevin
DB_USER=sa
DB_PASSWORD=tu_password
DB_DRIVER=ODBC Driver 17 for SQL Server
```

`.env` está en `.gitignore` — nunca se sube a git. `.env.example` sí se versiona, como plantilla sin credenciales reales.

## 3. Instalar dependencias Python

```bash
pip install -r C:/Tesis_Kevin/python/requirements.txt
```

## 4. Probar la conexión

```bash
python C:/Tesis_Kevin/python/database/bd_sqlserver.py
```

Esto conecta, registra un participante de prueba (`P999`), crea una sesión con 4 pruebas (Solfeggio 432/528/639Hz + Preferencia), consulta lo insertado, y **borra todo al final** — no deja basura en la base.

## 5. Migrar sesiones piloto ya guardadas en CSV

Si tienes sesiones de `datos/sesiones/*.csv` de antes de tener SQL Server integrado (P01–P12, etc.), este script las migra:

```bash
python C:/Tesis_Kevin/python/database/migrar_csv_a_sqlserver.py
```

**Antes de correrlo en serio:** edita `DEMOGRAFIA_PARTICIPANTES` al inicio de `migrar_csv_a_sqlserver.py` con la edad/género/mano dominante real de cada participante — los CSV nunca capturaron esos datos, así que sin completarlos quedan en `NULL` (con una observación que lo deja explícito, no se inventan valores).

## Uso normal (integrado en `sesion_completa.py`)

Al correr una sesión completa con `ejecutar_sesion_completa(..., guardar_en_bd=True)` (default), al terminar se guarda automáticamente en SQL Server además de los 3 archivos locales (CSV/WAV/JSON) — los archivos locales **siempre se conservan** como respaldo, SQL Server es un agregado en paralelo, no un reemplazo.
