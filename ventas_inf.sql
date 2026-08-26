-- Tabla de VENTA INF: ventas informales + consumo personal del personal.
-- Ejecutar en: Supabase Dashboard → SQL Editor.

create table ventas_inf (
    id              uuid        default gen_random_uuid() primary key,
    tipo            text        not null check (tipo in ('venta', 'consumo')),
    empleado_id     uuid,                       -- quién la cargó / de quién es el consumo
    empleado_nombre text,
    items           jsonb       not null,       -- [{name, lab, cantidad, precio_unit, subtotal}]
    total           numeric(12,2),
    impactado_stock boolean     default false,  -- ya se descontó en Genexus? (Fase 3)
    creado_en       timestamptz default now()
);

create index idx_ventas_inf_fecha on ventas_inf(creado_en);
create index idx_ventas_inf_emp   on ventas_inf(empleado_id);

alter table ventas_inf disable row level security;
