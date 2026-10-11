from sqlalchemy import inspect, text
from clinic.database import engine


def init_admin_tables() -> None:
    """Create only the extra admin-related tables. Existing clinic tables are untouched."""
    statements = [
        """
        CREATE TABLE IF NOT EXISTS admin_users (
            id INT AUTO_INCREMENT PRIMARY KEY,
            username VARCHAR(120) NOT NULL UNIQUE,
            password_hash VARCHAR(255) NOT NULL,
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            role VARCHAR(20) NOT NULL DEFAULT 'admin',
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """,
        """
        CREATE TABLE IF NOT EXISTS admin_doctor_profiles (
            id INT AUTO_INCREMENT PRIMARY KEY,
            doctor_id INT NOT NULL UNIQUE,
            qualification VARCHAR(255) NULL,
            experience_years INT NULL,
            phone VARCHAR(40) NULL,
            email VARCHAR(255) NULL,
            consultation_fee DECIMAL(10,2) NULL,
            about TEXT NULL,
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            INDEX idx_admin_doctor_profile_doctor_id (doctor_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """,
        """
        CREATE TABLE IF NOT EXISTS admin_booking_status (
            id INT AUTO_INCREMENT PRIMARY KEY,
            booking_id INT NOT NULL UNIQUE,
            status VARCHAR(40) NOT NULL DEFAULT 'booked',
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            INDEX idx_admin_booking_status_booking_id (booking_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """,
    ]
    with engine.begin() as conn:
        for statement in statements:
            conn.execute(text(statement))
        # Upgrade existing MySQL admin tables without discarding accounts.
        columns = {c['name'] for c in inspect(conn).get_columns('admin_users')}
        if 'role' not in columns:
            conn.execute(text("ALTER TABLE admin_users ADD COLUMN role VARCHAR(20) NOT NULL DEFAULT 'admin'"))
