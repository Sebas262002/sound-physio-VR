# Qué copiar en la universidad (desde el disco externo)

Checklist para el día de la recolección de datos reales. Todo lo que necesitas
está en `D:\PRESENTACION_FINAL` (copia de `C:\Tesis_Kevin`, sin `unity_projects/`).

## 1. Copiar y SOBRESCRIBIR en la PC de la universidad (`C:\Tesis_Kevin`)

- [ ] `python/` completo (ahí van los 3 archivos con los arreglos: Día repetido
      bloqueado, campo de preferencia bloqueado en Día 4/5, migración sin
      duplicados)
- [ ] `docker-compose.yml`
- [ ] `docker/`
- [ ] `README.md`, `documentacion/` (opcionales, no afectan que la app corra)

## 2. NO copiar / NO sobrescribir en la universidad

- [ ] `unity_projects/` — la universidad ya tiene su propia copia, no se toca
- [ ] `datos/` y `resultados/` — déjalas como están ahí; `limpiar_datos_piloto.py`
      se encarga de vaciarlas de forma segura (con respaldo primero)
- [ ] `.env` — solo revisa que la contraseña coincida, no lo sobrescribas sin
      comprobar primero
- [ ] `audio_estimulos/` — solo si cambió algo ahí, si no, ni falta

## 3. Orden del día

1. Hacer la prueba/demo con el inge, usando lo que ya está en la universidad
   (sin tocar nada todavía).
2. Copiar/sobrescribir el código del punto 1 desde el disco externo.
3. Correr `limpiar_datos_piloto.py` ahí mismo (borra la sesión de prueba del
   inge y cualquier otra que quede, con respaldo automático antes de borrar).
4. Confirmar que la base de datos quedó en 0 antes de empezar.
5. Empezar a registrar a los 15 estudiantes reales.

## 4. Cuando termine con los 15

Traer los datos a casa: primero **migrar** (`migrar_csv_a_sqlserver.py`, para
que queden copiados en la base de datos de casa), y recién después, si se
quiere, limpiar la de la universidad — nunca al revés, porque limpiar antes de
migrar borra esa sesión para siempre.
