# Database Configuration
import os

# SQLite Configuration (easier for development)
DB_CONFIG = {
    "database": os.path.join(os.path.dirname(__file__), "appointments.db"),
    "type": "sqlite"
}

# PostgreSQL Configuration (uncomment if you want to use PostgreSQL)
# DB_CONFIG = {
#     "dbname": "healthcare_db",
#     "user": "postgres",
#     "password": "root",
#     "host": "localhost",
#     "port": "5432",
#     "type": "postgresql"
# }