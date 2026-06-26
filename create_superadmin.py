"""Crea o recrea el superadmin usando la Admin API de Supabase."""

from database import supabase_admin
from services.user_store import sync_usuario_from_auth


EMAIL = "superadmin@calead.pe"
PASSWORD = "Calead@2025!"
NOMBRE = "Administrador Principal"


def main():
    admin = supabase_admin()

    result = admin.auth.admin.create_user(
        {
            "email": EMAIL,
            "password": PASSWORD,
            "email_confirm": True,
            "user_metadata": {
                "nombre_completo": NOMBRE,
                "rol": "superadmin",
            },
        }
    )

    user_id = result.user.id

    sync_usuario_from_auth(
        user_id=user_id,
        email=EMAIL,
        nombre_completo=NOMBRE,
        role_name="superadmin",
        activo=True,
    )

    print(f"Superadmin creado: {user_id}")


if __name__ == "__main__":
    main()
