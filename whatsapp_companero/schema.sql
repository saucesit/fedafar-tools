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
