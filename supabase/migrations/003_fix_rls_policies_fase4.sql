-- Fase 4: completar policies RLS faltantes para permitir inserts request-scoped
-- sin usar service_role en el backend.

drop policy if exists ins_rfq_detalle_logistica on rfq_detalle;
create policy ins_rfq_detalle_logistica
  on rfq_detalle
  for insert
  with check (fn_rol_actual() in ('administrador', 'logistica'));

drop policy if exists ins_rfq_respuestas_logistica on rfq_respuestas;
create policy ins_rfq_respuestas_logistica
  on rfq_respuestas
  for insert
  with check (fn_rol_actual() in ('administrador', 'logistica'));

drop policy if exists ins_ranking_proveedores_autenticado on ranking_proveedores_ml;
create policy ins_ranking_proveedores_autenticado
  on ranking_proveedores_ml
  for insert
  with check (auth.role() = 'authenticated');

drop policy if exists ins_oc_detalle_logistica on oc_detalle;
create policy ins_oc_detalle_logistica
  on oc_detalle
  for insert
  with check (fn_rol_actual() in ('administrador', 'logistica'));
