-- Ajuste del flujo de ordenes de venta.
-- La OV nace en estado "creada", luego pasa a "con_costo_servicio" al cargar el costo del servicio,
-- y puede ser cancelada solo por roles autorizados.

alter table if exists ordenes_venta
  drop constraint if exists ordenes_venta_estado_check;

alter table ordenes_venta
  add constraint ordenes_venta_estado_check
  check (estado in ('creada', 'con_costo_servicio', 'cancelada'));

update ordenes_venta
set estado = 'creada'
where estado = 'emitida';

update ordenes_venta
set estado = 'cancelada'
where estado = 'anulada';

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

  if v_ot.estado not in ('tech_completed', 'completed') then
    raise exception 'La OT debe estar en tech_completed o completed para generar la orden de venta.' using errcode = '22000';
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

  update ordenes_trabajo
  set estado = 'completed',
      fecha_completado = coalesce(fecha_completado, now()),
      updated_at = now()
  where id = p_ot_id;

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
    'creada',
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
      costo_total = v_costo_repuestos + v_costo_servicio_norm,
      estado = 'creada'
  where id = v_ov.id
  returning * into v_ov;

  return jsonb_build_object(
    'orden_venta_id', v_ov.id,
    'codigo_ov', v_ov.codigo_ov,
    'ot_id', v_ov.ot_id,
    'costo_repuestos', v_costo_repuestos,
    'costo_servicio', v_costo_servicio_norm,
    'costo_total', v_costo_repuestos + v_costo_servicio_norm,
    'estado', 'creada'
  );
end;
$$;

create or replace function fn_actualizar_orden_venta_costo_servicio(
  p_ov_id uuid,
  p_costo_servicio numeric
)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  v_ov ordenes_venta%rowtype;
  v_costo_repuestos numeric(12,2) := 0;
  v_costo_servicio_norm numeric(12,2) := coalesce(p_costo_servicio, 0);
begin
  if fn_rol_actual() not in ('administrador', 'tecnico', 'asesor_servicio', 'gerencia') then
    raise exception 'No autorizado' using errcode = '42501';
  end if;

  select * into v_ov
  from ordenes_venta
  where id = p_ov_id
  for update;

  if not found then
    raise exception 'Orden de venta no encontrada' using errcode = 'P0002';
  end if;

  if v_ov.estado = 'cancelada' then
    raise exception 'No se puede modificar una orden de venta cancelada.' using errcode = '22000';
  end if;

  select coalesce(sum(subtotal), 0)
  into v_costo_repuestos
  from ordenes_venta_detalle
  where orden_venta_id = v_ov.id;

  update ordenes_venta
  set costo_servicio = v_costo_servicio_norm,
      costo_total = v_costo_repuestos + v_costo_servicio_norm,
      estado = 'con_costo_servicio'
  where id = v_ov.id
  returning * into v_ov;

  return jsonb_build_object(
    'orden_venta_id', v_ov.id,
    'estado', v_ov.estado,
    'costo_servicio', v_ov.costo_servicio,
    'costo_total', v_ov.costo_total
  );
end;
$$;

create or replace function fn_cancelar_orden_venta(
  p_ov_id uuid
)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  v_ov ordenes_venta%rowtype;
begin
  if fn_rol_actual() not in ('administrador', 'asesor_servicio', 'gerencia') then
    raise exception 'No autorizado' using errcode = '42501';
  end if;

  select * into v_ov
  from ordenes_venta
  where id = p_ov_id
  for update;

  if not found then
    raise exception 'Orden de venta no encontrada' using errcode = 'P0002';
  end if;

  if v_ov.estado <> 'con_costo_servicio' then
    raise exception 'Solo se puede cancelar una orden de venta con costo de servicio.' using errcode = '22000';
  end if;

  update ordenes_venta
  set estado = 'cancelada'
  where id = v_ov.id
  returning * into v_ov;

  return jsonb_build_object(
    'orden_venta_id', v_ov.id,
    'estado', v_ov.estado
  );
end;
$$;
