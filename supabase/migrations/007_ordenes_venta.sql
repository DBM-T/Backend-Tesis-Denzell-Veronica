-- Fase 10: ordenes de venta derivadas del cierre de OT.
-- Se crea una cabecera con el costo de repuestos + costo de servicio y su detalle.

create sequence if not exists ordenes_venta_codigo_seq;

create table if not exists ordenes_venta (
  id uuid primary key default gen_random_uuid(),
  codigo_ov text not null unique default ('OV-' || lpad(nextval('ordenes_venta_codigo_seq')::text, 4, '0')),
  ot_id uuid not null unique references ordenes_trabajo(id) on delete restrict,
  sede_id uuid not null references sedes(id) on delete restrict,
  tecnico_id uuid references perfiles(id) on delete set null,
  costo_repuestos numeric(12,2) not null default 0,
  costo_servicio numeric(12,2) not null default 0,
  costo_total numeric(12,2) not null default 0,
  estado text not null default 'emitida' check (estado in ('emitida', 'anulada')),
  creado_por uuid references perfiles(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create unique index if not exists idx_ordenes_venta_ot_id on ordenes_venta(ot_id);
create index if not exists idx_ordenes_venta_codigo_ov on ordenes_venta(codigo_ov);
create index if not exists idx_ordenes_venta_estado on ordenes_venta(estado);

create table if not exists ordenes_venta_detalle (
  id uuid primary key default gen_random_uuid(),
  orden_venta_id uuid not null references ordenes_venta(id) on delete cascade,
  repuesto_id uuid not null references repuestos(id) on delete restrict,
  codigo_sku text not null,
  nombre_repuesto text not null,
  cantidad integer not null check (cantidad > 0),
  precio_unitario numeric(12,2) not null default 0,
  subtotal numeric(12,2) not null default 0,
  created_at timestamptz not null default now()
);

create index if not exists idx_ordenes_venta_detalle_ov_id on ordenes_venta_detalle(orden_venta_id);
create index if not exists idx_ordenes_venta_detalle_repuesto_id on ordenes_venta_detalle(repuesto_id);

alter table ordenes_venta enable row level security;
alter table ordenes_venta_detalle enable row level security;

drop policy if exists sel_ordenes_venta_roles on ordenes_venta;
create policy sel_ordenes_venta_roles
  on ordenes_venta
  for select
  using (fn_rol_actual() in ('administrador', 'asesor_servicio', 'tecnico', 'almacenero', 'logistica', 'gerencia'));

drop policy if exists ins_ordenes_venta_roles on ordenes_venta;
create policy ins_ordenes_venta_roles
  on ordenes_venta
  for insert
  with check (fn_rol_actual() in ('administrador', 'asesor_servicio', 'logistica'));

drop policy if exists upd_ordenes_venta_roles on ordenes_venta;
create policy upd_ordenes_venta_roles
  on ordenes_venta
  for update
  using (fn_rol_actual() in ('administrador', 'logistica'))
  with check (fn_rol_actual() in ('administrador', 'logistica'));

drop policy if exists sel_ordenes_venta_detalle_roles on ordenes_venta_detalle;
create policy sel_ordenes_venta_detalle_roles
  on ordenes_venta_detalle
  for select
  using (fn_rol_actual() in ('administrador', 'asesor_servicio', 'tecnico', 'almacenero', 'logistica', 'gerencia'));

drop policy if exists ins_ordenes_venta_detalle_roles on ordenes_venta_detalle;
create policy ins_ordenes_venta_detalle_roles
  on ordenes_venta_detalle
  for insert
  with check (fn_rol_actual() in ('administrador', 'asesor_servicio', 'logistica'));

drop policy if exists upd_ordenes_venta_detalle_roles on ordenes_venta_detalle;
create policy upd_ordenes_venta_detalle_roles
  on ordenes_venta_detalle
  for update
  using (fn_rol_actual() in ('administrador', 'logistica'))
  with check (fn_rol_actual() in ('administrador', 'logistica'));

create or replace function fn_set_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

drop trigger if exists trg_ordenes_venta_updated_at on ordenes_venta;
create trigger trg_ordenes_venta_updated_at
before update on ordenes_venta
for each row
execute function fn_set_updated_at();

create or replace function fn_generar_orden_venta(
  p_ot_id uuid,
  p_costo_servicio numeric default 0
)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  v_ot ordenes_trabajo%rowtype;
  v_existing ordenes_venta%rowtype;
  v_ov ordenes_venta%rowtype;
  v_costo_repuestos numeric(12,2) := 0;
  v_costo_servicio_norm numeric(12,2) := coalesce(p_costo_servicio, 0);
begin
  select * into v_ot
  from ordenes_trabajo
  where id = p_ot_id
  for update;

  if not found then
    raise exception 'OT no encontrada' using errcode = 'P0002';
  end if;

  if v_ot.estado <> 'tech_completed' then
    raise exception 'La OT debe estar en tech_completed para generar la orden de venta.' using errcode = '22000';
  end if;

  select * into v_existing
  from ordenes_venta
  where ot_id = p_ot_id;

  if found then
    return jsonb_build_object(
      'orden_venta_id', v_existing.id,
      'codigo_ov', v_existing.codigo_ov,
      'ot_id', v_existing.ot_id,
      'costo_repuestos', v_existing.costo_repuestos,
      'costo_servicio', v_existing.costo_servicio,
      'costo_total', v_existing.costo_total,
      'estado', v_existing.estado
    );
  end if;

  insert into ordenes_venta (
    ot_id,
    sede_id,
    tecnico_id,
    costo_repuestos,
    costo_servicio,
    costo_total,
    estado,
    creado_por
  ) values (
    p_ot_id,
    v_ot.sede_id,
    v_ot.tecnico_id,
    0,
    v_costo_servicio_norm,
    v_costo_servicio_norm,
    'emitida',
    coalesce(auth.uid(), v_ot.asesor_id)
  )
  returning * into v_ov;

  insert into ordenes_venta_detalle (
    orden_venta_id,
    repuesto_id,
    codigo_sku,
    nombre_repuesto,
    cantidad,
    precio_unitario,
    subtotal
  )
  select
    v_ov.id,
    req.repuesto_id,
    rep.codigo_sku,
    rep.nombre,
    sum(req.cantidad)::integer,
    coalesce(rep.precio, 0),
    (sum(req.cantidad) * coalesce(rep.precio, 0))::numeric(12,2)
  from ot_repuestos_requeridos req
  join repuestos rep on rep.id = req.repuesto_id
  where req.ot_id = p_ot_id
  group by req.repuesto_id, rep.codigo_sku, rep.nombre, rep.precio;

  select coalesce(sum(subtotal), 0)
  into v_costo_repuestos
  from ordenes_venta_detalle
  where orden_venta_id = v_ov.id;

  update ordenes_venta
  set costo_repuestos = v_costo_repuestos,
      costo_total = v_costo_repuestos + v_costo_servicio_norm
  where id = v_ov.id;

  update ordenes_trabajo
  set estado = 'cancelada',
      fecha_completado = coalesce(fecha_completado, now()),
      updated_at = now()
  where id = p_ot_id;

  return jsonb_build_object(
    'orden_venta_id', v_ov.id,
    'codigo_ov', v_ov.codigo_ov,
    'ot_id', v_ov.ot_id,
    'costo_repuestos', v_costo_repuestos,
    'costo_servicio', v_costo_servicio_norm,
    'costo_total', v_costo_repuestos + v_costo_servicio_norm,
    'estado', 'emitida'
  );
end;
$$;
