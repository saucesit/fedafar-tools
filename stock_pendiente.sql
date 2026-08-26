-- Pendientes de impactar en stock (Fase 3 de VENTA INF).
-- Cuando el EGRESO en Genexus no alcanza a cubrir lo vendido/consumido porque
-- no hay stock suficiente en los lotes, se egresa lo que hay y se registra acá
-- lo que quedó pendiente, para alertarlo en la app.
-- Ejecutar en: Supabase Dashboard → SQL Editor.

create table stock_pendiente (
    id               uuid        default gen_random_uuid() primary key,
    articulo_nombre  text        not null,
    articulo_codigo  text,                       -- código Genexus si se conoce
    cantidad         numeric(12,2) not null,     -- unidades que faltaron egresar
    fecha            date        not null,       -- día del movimiento al que corresponde
    motivo           text        default 'stock insuficiente en lotes',
    resuelto         boolean     default false,  -- ya se egresó manualmente / se repuso
    resuelto_en      timestamptz,
    resuelto_por     text,
    creado_en        timestamptz default now()
);

create index idx_stock_pendiente_resuelto on stock_pendiente(resuelto);
create index idx_stock_pendiente_fecha    on stock_pendiente(fecha);

alter table stock_pendiente disable row level security;
