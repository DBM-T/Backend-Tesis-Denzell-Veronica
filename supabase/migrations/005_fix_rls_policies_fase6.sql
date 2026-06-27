-- Fase 6: policies RLS para persistencia de inferencias ML request-scoped.

drop policy if exists ins_inferencias_ml_roles on inferencias_ml;
create policy ins_inferencias_ml_roles
  on inferencias_ml
  for insert
  with check (fn_rol_actual() in ('administrador', 'asesor_servicio', 'tecnico', 'logistica'));

drop policy if exists ins_pronosticos_demanda_roles on pronosticos_demanda;
create policy ins_pronosticos_demanda_roles
  on pronosticos_demanda
  for insert
  with check (fn_rol_actual() in ('administrador', 'logistica'));

drop policy if exists upd_pronosticos_demanda_roles on pronosticos_demanda;
create policy upd_pronosticos_demanda_roles
  on pronosticos_demanda
  for update
  using (fn_rol_actual() in ('administrador', 'logistica'))
  with check (fn_rol_actual() in ('administrador', 'logistica'));

drop policy if exists ins_riesgo_abastecimiento_ml_roles on riesgo_abastecimiento_ml;
create policy ins_riesgo_abastecimiento_ml_roles
  on riesgo_abastecimiento_ml
  for insert
  with check (fn_rol_actual() in ('administrador', 'logistica'));
