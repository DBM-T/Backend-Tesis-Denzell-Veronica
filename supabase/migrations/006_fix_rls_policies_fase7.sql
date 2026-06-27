-- Fase 7: permitir crear alertas desde el backend request-scoped y atender recomendaciones.

drop policy if exists ins_alertas_roles on alertas;
create policy ins_alertas_roles
  on alertas
  for insert
  with check (fn_rol_actual() in ('administrador', 'almacenero', 'logistica'));

drop policy if exists upd_recomendaciones_compra_roles on recomendaciones_compra;
create policy upd_recomendaciones_compra_roles
  on recomendaciones_compra
  for update
  using (fn_rol_actual() in ('administrador', 'logistica'))
  with check (fn_rol_actual() in ('administrador', 'logistica'));
