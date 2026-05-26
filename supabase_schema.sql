-- ============================================================
-- Schema de Supabase para Fedafar Tools
-- Ejecutar en: Supabase Dashboard → SQL Editor
-- ============================================================

-- Tabla de clientes (farmacias)
create table clientes (
    id                  uuid        default gen_random_uuid() primary key,
    username            text        unique not null,
    password_hash       text        not null,
    nombre              text        not null,                          -- nombre de la farmacia
    tipo_precio         text        not null default 'contado'         -- 'contado' o 'cta-cte'
                        check (tipo_precio in ('contado', 'cta-cte')),
    genexus_client_id   integer     unique,                            -- código numérico en el sistema interno (ej: 1248)
    activo              boolean     default true,
    created_at          timestamptz default now()
);

-- Tabla de estado de cuenta
create table cuenta_corriente (
    id                  bigserial   primary key,
    genexus_client_id   integer     not null references clientes(genexus_client_id),
    fecha_comprobante   text,
    comprobante         text,
    fecha_vencimiento   text,
    importe             numeric(12,2),
    saldo               numeric(12,2),
    actualizado_en      timestamptz default now()
);

create index idx_cta_cte_client on cuenta_corriente(genexus_client_id);

-- ── Row Level Security (RLS) ──────────────────────────────────────────────────
-- Solo habilitar cuando se implemente auth en la app.
-- Por ahora se accede con la service key desde el script de sync.

-- alter table clientes          enable row level security;
-- alter table cuenta_corriente  enable row level security;
