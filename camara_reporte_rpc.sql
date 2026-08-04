-- Función de resumen para el reporte de auditoría de cadena de frío.
-- Agrega en la base (rápido aunque haya cientos de miles de lecturas).
-- Ejecutar en: Supabase Dashboard → SQL Editor.

create or replace function reporte_camara(p_desde timestamp, p_hasta timestamp)
returns table (
    dispositivo   text,
    sensor_nombre text,
    sensor_key    text,
    lecturas      bigint,
    minimo        numeric,
    maximo        numeric,
    promedio      numeric,
    primera       timestamp,
    ultima        timestamp
)
language sql
stable
as $$
    select dispositivo,
           sensor_nombre,
           sensor_key,
           count(*)              as lecturas,
           min(valor)            as minimo,
           max(valor)            as maximo,
           round(avg(valor), 2)  as promedio,
           min(fecha)            as primera,
           max(fecha)            as ultima
    from camara_lecturas
    where fecha >= p_desde
      and fecha <= p_hasta
      and valor is not null
    group by dispositivo, sensor_nombre, sensor_key
    order by dispositivo, sensor_nombre;
$$;
