-- Fase 5: habilitar inserciones request-scoped para cargas historicas e historial de consumo.

drop policy if exists ins_cargas_csv_logistica on cargas_csv;
create policy ins_cargas_csv_logistica
  on cargas_csv
  for insert
  with check (fn_rol_actual() in ('administrador', 'logistica'));

drop policy if exists upd_cargas_csv_logistica on cargas_csv;
create policy upd_cargas_csv_logistica
  on cargas_csv
  for update
  using (fn_rol_actual() in ('administrador', 'logistica'))
  with check (fn_rol_actual() in ('administrador', 'logistica'));

drop policy if exists ins_validaciones_csv_logistica on validaciones_csv;
create policy ins_validaciones_csv_logistica
  on validaciones_csv
  for insert
  with check (fn_rol_actual() in ('administrador', 'logistica'));

drop policy if exists ins_historial_consumo_operacion on historial_consumo;
create policy ins_historial_consumo_operacion
  on historial_consumo
  for insert
  with check (fn_rol_actual() in ('administrador', 'tecnico', 'logistica'));
