-- Esquema de TesisKevin para el SQL Server en Docker.
-- Mismo esquema que ya documenta python/database/bd_sqlserver.py (ver
-- "ESQUEMA DE LA BASE" en su docstring) -- este script solo lo recrea
-- desde cero en el contenedor nuevo.

IF DB_ID('TesisKevin') IS NULL
BEGIN
    CREATE DATABASE TesisKevin;
END
GO

USE TesisKevin;
GO

IF OBJECT_ID('dbo.pruebas', 'U') IS NOT NULL DROP TABLE dbo.pruebas;
IF OBJECT_ID('dbo.sesiones', 'U') IS NOT NULL DROP TABLE dbo.sesiones;
IF OBJECT_ID('dbo.participantes', 'U') IS NOT NULL DROP TABLE dbo.participantes;
GO

CREATE TABLE participantes (
    id_participante        VARCHAR(10)     NOT NULL PRIMARY KEY,
    edad                    INT             NULL,
    genero                  VARCHAR(10)     NULL,
    fecha_registro          DATETIME        NOT NULL,
    consentimiento          BIT             NULL,
    observaciones           VARCHAR(500)    NULL,
    ruta_preferencia_wav    NVARCHAR(500)   NULL
);
GO

CREATE TABLE sesiones (
    id_sesion           INT IDENTITY(1,1) NOT NULL PRIMARY KEY,
    id_participante     VARCHAR(10)       NOT NULL REFERENCES participantes(id_participante),
    fecha_hora          DATETIME          NOT NULL,
    duracion_seg        INT               NULL,
    hr_baseline         FLOAT             NULL,
    rmssd_baseline      FLOAT             NULL,
    sdnn_baseline       FLOAT             NULL,
    notas               VARCHAR(500)      NULL,
    usa_vr              BIT               NOT NULL DEFAULT 0,
    dia_sesion          INT               NULL,
    valida              BIT               NOT NULL DEFAULT 1
);
GO

CREATE TABLE pruebas (
    id_prueba           INT IDENTITY(1,1) NOT NULL PRIMARY KEY,
    id_sesion           INT               NOT NULL REFERENCES sesiones(id_sesion),
    id_participante     VARCHAR(10)       NOT NULL REFERENCES participantes(id_participante),
    tipo_estimulo        VARCHAR(20)      NOT NULL,
    frecuencia_hz        FLOAT            NULL,
    duracion_seg          INT             NULL,
    hr_promedio          FLOAT            NULL,
    hr_min               FLOAT            NULL,
    hr_max               FLOAT            NULL,
    rmssd                FLOAT            NULL,
    sdnn                 FLOAT            NULL,
    pnn50                FLOAT            NULL,
    resp_por_min         FLOAT            NULL,
    preferencia          VARCHAR(20)      NULL,
    likert_relajacion    INT              NULL,
    likert_confort       INT              NULL,
    fecha_hora           DATETIME         NOT NULL
);
GO
