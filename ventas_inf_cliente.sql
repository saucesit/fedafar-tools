-- Agrega el nombre del cliente (opcional) a VENTA INF, para identificar la
-- venta cuando se quiere. Si se deja vacío, no cambia nada de lo actual.
-- Ejecutar en: Supabase Dashboard → SQL Editor.

alter table ventas_inf add column if not exists cliente_nombre text;
