-- Compañero WhatsApp — fase 1 (lector)
-- Correr en Supabase > SQL Editor.

create table if not exists wa_mensajes (
  id               text primary key,          -- id del mensaje de WhatsApp (único, sirve para deduplicar)
  chat_id          text not null,             -- id del chat (xxx@lid / xxx@c.us)
  chat_nombre      text,
  telefono         text,
  from_me          boolean not null default false,  -- true = lo mandó FEDAFAR (cualquier dispositivo)
  t                timestamptz not null,      -- hora del mensaje
  tipo             text not null,             -- chat, image, ptt (audio), document, video, sticker...
  texto            text,
  mimetype         text,
  duracion         integer,
  cita_id          text,                      -- mensaje al que responde
  recibido_en      timestamptz not null default now(),
  -- clasificación (la completa el clasificador, fase siguiente)
  categoria        text,
  prioridad        smallint,
  espera_respuesta boolean,
  resumen          text,
  clasificado_en   timestamptz
);

create index if not exists wa_mensajes_chat_t on wa_mensajes (chat_id, t desc);
create index if not exists wa_mensajes_t on wa_mensajes (t desc);
create index if not exists wa_mensajes_sin_clasificar on wa_mensajes (t) where clasificado_en is null;

create table if not exists wa_contactos (
  chat_id            text primary key,
  nombre             text,
  telefono           text,
  genexus_client_id  text,                    -- vínculo con el cliente (se completa después)
  notas              text,
  actualizado_en     timestamptz not null default now()
);

-- Estado de cada chat: último entrante / último saliente → "sin responder"
create or replace view wa_chats_estado as
select
  chat_id,
  max(chat_nombre)                          as chat_nombre,
  max(t) filter (where not from_me)         as ultimo_entrante,
  max(t) filter (where from_me)             as ultimo_saliente,
  max(t)                                    as ultimo_mensaje,
  (max(t) filter (where not from_me)) > coalesce(max(t) filter (where from_me), '-infinity'::timestamptz) as sin_responder
from wa_mensajes
group by chat_id;

-- Toda tabla nueva nace con RLS → los inserts fallan en silencio. Deshabilitar (igual que el resto).
alter table wa_mensajes  disable row level security;
alter table wa_contactos disable row level security;

-- ── Sugerencias de respuesta (fase 4) ─────────────────────────────────────────
-- Cuando entra un mensaje que espera respuesta, el Compañero redacta una
-- sugerencia. Solo se envía si Facundo la aprueba en el panel; la extensión
-- toma las aprobadas y las manda desde WhatsApp Web.
-- estado: pendiente → aprobada → enviando → enviada | error
--         pendiente → descartada | reemplazada (llegó otro mensaje) | respondida (el equipo contestó)
--         aprobada  → vencida (la extensión no la tomó a tiempo)
--         sin_sugerencia (el Compañero decidió que no corresponde responder)
create table if not exists wa_sugerencias (
  id            bigserial primary key,
  chat_id       text not null,
  mensaje_id    text not null unique,     -- mensaje del cliente que la disparó
  chat_nombre   text,
  telefono      text,
  texto_cliente text,
  sugerencia    text,
  nota          text,                     -- comentario del Compañero para Facundo
  texto_final   text,                     -- lo que Facundo aprobó (puede haberlo editado)
  estado        text not null default 'pendiente',
  creado_en     timestamptz not null default now(),
  aprobado_en   timestamptz,
  enviado_en    timestamptz,
  wa_msg_id     text,
  error         text
);
create index if not exists wa_sugerencias_estado on wa_sugerencias (estado, creado_en desc);
alter table wa_sugerencias disable row level security;

-- ── Aprendizajes (cómo responde FEDAFAR) ─────────────────────────────────────
-- Reglas que Facundo le enseña al Compañero (en la Charla o al descartar una
-- sugerencia). Se inyectan en cada sugerencia y en la Charla.
-- chat_id null = regla general; con chat_id = solo para ese cliente.
create table if not exists wa_aprendizajes (
  id         bigserial primary key,
  regla      text not null,
  chat_id    text,
  chat_nombre text,
  origen     text not null default 'facundo',   -- facundo | descarte
  activo     boolean not null default true,
  creado_en  timestamptz not null default now()
);
alter table wa_aprendizajes disable row level security;
