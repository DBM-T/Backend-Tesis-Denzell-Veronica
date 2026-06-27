from app.services.ml_service import _validate_csv_rows


def test_validate_csv_rows_accepts_normalized_rows():
    rows = [
        {
            "repuesto_id": "11111111-1111-1111-1111-111111111111",
            "sede_id": "22222222-2222-2222-2222-222222222222",
            "cantidad_consumida": "3",
            "fecha_consumo": "2026-06-27",
            "vehiculo_marca": "Toyota",
        }
    ]

    clean_rows, issues = _validate_csv_rows(rows)

    assert len(clean_rows) == 1
    assert issues == []
    assert clean_rows[0]["cantidad_consumida"] == 3
    assert clean_rows[0]["vehiculo_marca"] == "Toyota"


def test_validate_csv_rows_detects_duplicate_and_format_errors():
    rows = [
        {
            "repuesto_id": "not-a-uuid",
            "sede_id": "22222222-2222-2222-2222-222222222222",
            "cantidad_consumida": "0",
            "fecha_consumo": "2026-06-27",
        },
        {
            "repuesto_id": "not-a-uuid",
            "sede_id": "22222222-2222-2222-2222-222222222222",
            "cantidad_consumida": "0",
            "fecha_consumo": "2026-06-27",
        },
    ]

    clean_rows, issues = _validate_csv_rows(rows)

    assert clean_rows == []
    assert any(issue.tipo_incidencia == "formato_invalido" for issue in issues)
    assert any(issue.tipo_incidencia == "duplicado" for issue in issues)
