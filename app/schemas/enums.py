from enum import Enum


class UserRole(str, Enum):
    administrador = "administrador"
    asesor_servicio = "asesor_servicio"
    tecnico = "tecnico"
    almacenero = "almacenero"
    logistica = "logistica"
    gerencia = "gerencia"


class UserStatus(str, Enum):
    activo = "activo"
    inactivo = "inactivo"


class WorkOrderStatus(str, Enum):
    registrada = "registrada"
    diagnostico = "diagnostico"
    waiting_parts = "waiting_parts"
    in_progress = "in_progress"
    tech_completed = "tech_completed"
    completed = "completed"
    cancelada = "cancelada"


class PriorityML(str, Enum):
    ALTA = "ALTA"
    BAJA = "BAJA"


class PurchaseRequestStatus(str, Enum):
    generada = "generada"
    en_cotizacion = "en_cotizacion"
    aprobada = "aprobada"
    convertida_oc = "convertida_oc"
    cancelada = "cancelada"


class RFQStatus(str, Enum):
    enviada = "enviada"
    respondida = "respondida"
    vencida = "vencida"
    cancelada = "cancelada"


class PurchaseOrderStatus(str, Enum):
    pendiente_aprobacion = "pendiente_aprobacion"
    aprobada = "aprobada"
    enviada = "enviada"
    pendiente = "pendiente"
    retrasada = "retrasada"
    recibida_parcial = "recibida_parcial"
    recibida = "recibida"
    cerrada = "cerrada"
    rechazada = "rechazada"


class OrdenVentaStatus(str, Enum):
    creada = "creada"
    con_costo_servicio = "con_costo_servicio"
    cancelada = "cancelada"


class PurchaseChannel(str, Enum):
    local = "local"
    importacion = "importacion"
    distribuidor = "distribuidor"


class InventoryMoveType(str, Enum):
    entrada_compra = "entrada_compra"
    salida_consumo = "salida_consumo"
    ajuste_positivo = "ajuste_positivo"
    ajuste_negativo = "ajuste_negativo"
    transferencia = "transferencia"


class ReceptionConformity(str, Enum):
    conforme = "conforme"
    no_conforme = "no_conforme"


class MLModelType(str, Enum):
    xgboost_demanda = "xgboost_demanda"
    xgboost_proveedor = "xgboost_proveedor"
    xgboost_lead_time = "xgboost_lead_time"
    lightgbm_prioridad = "lightgbm_prioridad"


class CSVDataType(str, Enum):
    consumo = "consumo"
    movimientos = "movimientos"
    compras = "compras"
    proveedores = "proveedores"
    quiebres_stock = "quiebres_stock"


class CSVLoadStatus(str, Enum):
    cargado = "cargado"
    validado = "validado"
    con_errores = "con_errores"
    procesado = "procesado"


class AlertType(str, Enum):
    punto_reorden = "punto_reorden"
    riesgo_quiebre = "riesgo_quiebre"
    oc_retrasada = "oc_retrasada"
    oc_pendiente_aprobacion = "oc_pendiente_aprobacion"
    no_conformidad_proveedor = "no_conformidad_proveedor"


class AlertSeverity(str, Enum):
    baja = "baja"
    media = "media"
    alta = "alta"


class AlertStatus(str, Enum):
    activa = "activa"
    atendida = "atendida"
    descartada = "descartada"
