# adaptive-sound-physio-vr

Sistema adaptativo para la evaluación de frecuencias terapéuticas y preferencias sonoras personales mediante respuestas fisiológicas (HR/HRV) en entornos inmersivos (Meta Quest 2). Trabajo de Integración Curricular — Kevin Sebastián Lechón Churuchumbi, ESPE.

Este README explica cómo levantar el proyecto de cero: base de datos, dependencias de Python, variables de entorno, y cómo correr y probar la app.

**Antes que nada: ubícate en la raíz del proyecto.** Todos los comandos de este README asumen que tu terminal está parada ahí:

```bash
cd C:\Tesis_Kevin
```

(En PowerShell/CMD es el mismo comando `cd`. Si tu clon del repo está en otra ruta, usa esa en vez de `C:\Tesis_Kevin`.)

## 1. Requisitos previos

- **Python 3.12** (o compatible 3.10+)
- **Docker Desktop** (para la base de datos SQL Server) — https://www.docker.com/products/docker-desktop/
- **ODBC Driver 17 (o 18) for SQL Server** — necesario para que `pyodbc` pueda conectarse. Para verificar si ya lo tienes:

  ```bash
  python -c "import pyodbc; print(pyodbc.drivers())"
  ```

  Si `'ODBC Driver 17 for SQL Server'` no aparece en la lista, descárgalo e instálalo desde:
  https://learn.microsoft.com/sql/connect/odbc/download-odbc-driver-for-sql-server
  (instalador de 64 bits, el que corresponde a la mayoría de instalaciones de Python en Windows).

- **Git Bash** — necesario para el comando que crea las tablas la primera vez (paso 3.4), porque usa redirección `<` de tipo Unix que PowerShell no soporta.
  - Si ya tienes Git instalado en Windows, ya tienes Git Bash: búscalo en el menú de inicio como "Git Bash".
  - Si no lo tienes, descarga "Git for Windows" desde https://git-scm.com/downloads/win e instálalo con las opciones por defecto (Git Bash se incluye automáticamente).
  - Alternativa sin instalar nada: usa `cmd.exe`, o el comando equivalente en PowerShell que se documenta en el paso 3.4.
  - **(Opcional, no es necesario para levantar el proyecto)** Si en esta PC vas a hacer `git commit`, configura tu identidad una sola vez:
    ```bash
    git config --global user.name "Kevin Lechon"
    git config --global user.email "kslechon@espe.edu.ec"
    ```

- **(Opcional) Sensor Wahoo TRACKR Heart Rate** — solo si vas a correr una sesión con hardware real (Bluetooth Low Energy).
- **(Opcional) Meta Quest 2 + Unity** — solo si vas a correr una sesión con el entorno VR; sin esto la app funciona igual, con el switch de VR apagado.

## 2. Instalar las dependencias de Python

Desde la raíz del proyecto (`C:\Tesis_Kevin`):

```bash
pip install -r python/requirements.txt
```

Esto instala, entre otras cosas:

| Paquete | Para qué |
|---|---|
| `bleak` | Conexión BLE al sensor Wahoo TRACKR |
| `sounddevice`, `soundfile`, `librosa` | Captura, reproducción y análisis de audio |
| `numpy`, `pandas`, `scipy` | Procesamiento de señales y métricas HR/HRV |
| `matplotlib` | Gráficas de los reportes |
| `pyodbc`, `python-dotenv` | Conexión a SQL Server y carga del `.env` |
| `flet`, `flet-charts`, `openpyxl` | Interfaz de escritorio y exportación a Excel |
| `reportlab`, `Pillow` | Generación del reporte PDF |
| `python-osc` | Puente OSC con Unity/Meta Quest 2 (solo control, no audio) |

## 3. Levantar la base de datos (Docker)

La base de datos vive en un contenedor Docker (SQL Server 2022) definido en `docker-compose.yml`, en la raíz del proyecto.

1. Abre Docker Desktop y espera a que esté corriendo.
2. Desde la raíz del proyecto (`C:\Tesis_Kevin`):

   ```bash
   docker compose up -d
   ```

3. Espera a que el contenedor esté saludable (puede tardar 10-30 segundos la primera vez):

   ```bash
   docker inspect --format="{{.State.Health.Status}}" tesiskevin-sql
   ```

   Repite hasta que diga `healthy`.

4. La primera vez que arranca el contenedor (volumen nuevo), la base `TesisKevin` y sus tablas **no existen todavía** — hay que crearlas corriendo el script de esquema una sola vez. **Este paso se corre en Git Bash o en `cmd.exe`, no en PowerShell** (PowerShell no soporta la redirección `<` que usa este comando):

   ```bash
   docker exec -i tesiskevin-sql /opt/mssql-tools18/bin/sqlcmd -S localhost -U sa -P "Fesa2026/*" -C -i /dev/stdin < docker/init_schema.sql
   ```

   (Si usas Git Bash en Windows y el comando falla por traducción de rutas, antepón `MSSQL_NO_PATHCONV=1` o `MSYS_NO_PATHCONV=1` al comando.)

   **Si prefieres no usar Git Bash**, este es el equivalente en PowerShell:

   ```powershell
   Get-Content docker/init_schema.sql -Raw | docker exec -i tesiskevin-sql /opt/mssql-tools18/bin/sqlcmd -S localhost -U sa -P "Fesa2026/*" -C -i /dev/stdin
   ```

**Notas:**
- El contenedor queda con `restart: unless-stopped` — normalmente no hace falta repetir `docker compose up -d` después de reiniciar la PC, Docker Desktop lo vuelve a levantar solo (si Docker Desktop está configurado para iniciar con Windows).
- Los datos persisten en un volumen Docker (`tesiskevin_sql_data`) aunque el contenedor se reinicie — solo se pierden si lo borras explícitamente con `docker compose down -v`.
- Si prefieres usar un SQL Server Express instalado directo en Windows en vez de Docker, es compatible — solo cambia `DB_SERVER` en el `.env` (ver paso 4). El esquema de tablas es el mismo (`docker/init_schema.sql` documenta también el DDL).

## 4. Configurar el archivo `.env`

Las credenciales viven en un archivo `.env` en la **raíz del proyecto**, nunca en el código (está en `.gitignore`, no se sube a git). Cópialo desde la plantilla si no lo tienes:

```bash
cp .env.example .env
```

Contenido esperado para la base en Docker (valores por default del `docker-compose.yml`):

```
DB_SERVER=localhost,1433
DB_DATABASE=TesisKevin
DB_USER=sa
DB_PASSWORD=Fesa2026/*
DB_DRIVER=ODBC Driver 17 for SQL Server
```

## 5. Probar la conexión a la base

```bash
python python/database/bd_sqlserver.py
```

Esto conecta, registra un participante de prueba (`P999`), crea una sesión con pruebas, consulta lo insertado, y **borra todo al final** — no deja basura en la base. Si termina sin errores, la conexión está bien configurada.

Más detalle de la base de datos (migración de sesiones piloto en CSV, esquema completo, etc.) en `python/database/README.md`.

## 6. Correr la app

```bash
python python/interfaz/app_investigador.py
```

Se abre una ventana de escritorio (Flet) con 5 vistas: Inicio, Nueva sesión, Sesión en vivo, Cuestionario, Análisis.

**Nota sobre la carpeta:** este comando (y el del paso 5) en realidad funcionan desde cualquier carpeta en la que estés parado — el código resuelve sus propios archivos (`.env`, base de datos, carpetas de audio/resultados) con rutas absolutas fijas a `C:\Tesis_Kevin\...`, no con rutas relativas a donde ejecutes `python`. Aun así, para no tener que escribir la ruta completa cada vez, es más cómodo seguir parado en la raíz del proyecto (`cd C:\Tesis_Kevin`) y usar la ruta corta `python/interfaz/app_investigador.py` como está arriba.

## 7. Cómo probar el flujo completo

**A. Sesión simulada (sin hardware real) — Día 1:**
1. En "Nueva sesión", deja los switches de sensor real y VR apagados.
2. Ingresa un ID de prueba (ej. `P999`), edad, género, marca el consentimiento.
3. Elige Día 1 y registra.
4. Deja correr la sesión simulada hasta el final (el bloque de estímulo dura 300s).
5. Completa el cuestionario post-sesión.
6. En "Análisis", confirma que la sesión quedó guardada.

**B. Día 2 (pide canción de preferencia):**
1. Vuelve a escribir el mismo ID (`P999`) — debería autocompletar los datos y sugerir Día 2.
2. Intenta registrar sin poner ruta de audio: el botón debe quedar deshabilitado con el error correspondiente.
3. Pon la ruta a un `.wav` real, registra y corre la sesión.

**C. Día 3** (mismo flujo que A, con el otro tipo de estímulo sorteado).

**D. Día 4 (canción de preferencia DISTINTA a la de Día 2):**
1. Mismo ID — debería sugerir Día 4 tras completar 1, 2 y 3.
2. Verifica que pida la ruta de la **segunda** canción de preferencia y que sea obligatoria.
3. Corre la sesión.

**E. Resultado de 2 grupos (el resultado central de la tesis):**
1. Con las 4 sesiones de `P999` registradas, ve a "Análisis" → pestaña "Recomendación".
2. Selecciona `P999` y calcula — debe aparecer primero la comparación de 2 grupos (frecuencias terapéuticas Días 1+3 vs. preferencia Días 2+4), y debajo el detalle por sesión.
3. Genera el reporte PDF del participante y confirma que las Páginas 1 y 3 muestren esa misma comparación.

**F. (Opcional) Hardware real:**
- **Sensor Wahoo:** activa el switch de sensor real antes de registrar — el escaneo BLE tarda unos 12 segundos en detectarlo.
- **Meta Quest 2 / Unity:** activa el switch de VR, abre el proyecto de Unity (`unity_projects/`) con el Quest conectado y presiona Play antes de registrar — la app espera confirmación de Unity (ping) para habilitar el switch.

## 8. Estructura del proyecto (resumen)

```
C:\Tesis_Kevin\
├── .env                      # credenciales (no se sube a git)
├── docker-compose.yml        # base de datos SQL Server en Docker
├── docker/init_schema.sql    # esquema de tablas (participantes/sesiones/pruebas)
├── python/
│   ├── requirements.txt
│   ├── interfaz/              # app_investigador.py (GUI Flet), reporte_pdf.py
│   ├── database/              # bd_sqlserver.py (única puerta a SQL Server)
│   ├── sensor/                # captura BLE del Wahoo TRACKR
│   ├── audio/                 # generación/reproducción de estímulos sonoros
│   ├── analisis/              # recomendador.py, análisis de métricas HR/HRV
│   ├── vr/                    # puente OSC con Unity (solo control)
│   └── sesion_completa.py     # orquestador de una sesión completa
├── unity_projects/            # proyecto de Unity para el entorno VR
├── audio_estimulos/           # WAVs de estímulos terapéuticos y de preferencia
├── datos/                     # sesiones capturadas (CSV/JSON), backups de BD
└── resultados/                # exportados (Excel, PDF, gráficas)
```

## 9. Problemas comunes

- **`pyodbc.InterfaceError` / no conecta:** revisa que Docker esté corriendo (`docker ps`) y que el `.env` tenga `DB_SERVER=localhost,1433`.
- **El driver ODBC no aparece:** instálalo (ver paso 1) y reinicia la terminal.
- **El sensor Wahoo no se detecta:** el escaneo BLE necesita ~12 segundos reales — si tarda menos y falla, probablemente el sensor está apagado o fuera de rango.
- **VR no responde:** confirma que el proyecto de Unity esté en Play y que el switch de VR se haya intentado activar después de eso (la app hace un ping a Unity al encender el switch).
- **Contenedor Docker "unhealthy" o caído:** `docker compose up -d` de nuevo; si persiste, revisa logs con `docker logs tesiskevin-sql`.
