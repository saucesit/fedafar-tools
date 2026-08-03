-- Tabla de histórico de temperaturas de la cámara de frío (ESPDesign).
-- Retención permanente (ESP solo guarda ~3 meses). Poblada por camara_captura.py.
-- Ejecutar en: Supabase Dashboard → SQL Editor.

create table camara_lecturas (
    id            bigserial   primary key,
    lectura_id    text        unique,          -- id único de la lectura en ESP (dedup)
    dispositivo   text,                        -- ej: "Equipo 2 004905 Atrás"
    sensor_nombre text,                        -- alias amigable, ej: "Cámara"
    sensor_key    text,                        -- ej: "temp1"
    valor         numeric,                     -- temperatura en °C
    fecha         timestamp,                   -- momento de la lectura (hora local ESP)
    capturado_en  timestamptz default now()
);

create index idx_camara_fecha     on camara_lecturas(fecha);
create index idx_camara_disp_fecha on camara_lecturas(dispositivo, fecha);

-- IMPORTANTE: sin esto los inserts fallan por RLS (como el resto de las tablas del proyecto)
alter table camara_lecturas disable row level security;
