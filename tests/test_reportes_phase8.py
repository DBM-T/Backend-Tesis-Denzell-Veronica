from app.services.reportes_service import _sanitize_filename, _serialize_rows


def test_serialize_rows_csv_contains_header():
    payload = _serialize_rows(
        [{"id": "1", "tipo": "activa", "mensaje": "hola"}],
        tipo_reporte="alertas",
        formato="csv",
    )

    text = payload.decode("utf-8")
    assert "id,tipo,severidad,estado,sede_id,mensaje,created_at" in text.splitlines()[0]


def test_sanitize_filename_removes_slashes():
    assert _sanitize_filename("a/b c\\d") == "a_b_c_d"
