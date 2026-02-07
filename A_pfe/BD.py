import sqlite3
import os

DB_NAME = "database.db"

def create_db():
    con = sqlite3.connect(DB_NAME)
    cur = con.cursor()

    # =====================================================
    # COMPANIES
    # =====================================================
    cur.execute("""
    CREATE TABLE IF NOT EXISTS companies (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # =====================================================
    # USERS (RH / CHEF / RESSOURCE)
    # =====================================================
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        first_name TEXT NOT NULL,
        last_name TEXT NOT NULL,
        email TEXT NOT NULL UNIQUE,
        password TEXT NOT NULL,
        role TEXT CHECK(role IN ('RH','CHEF','RESSOURCE')) NOT NULL,
        company_id INTEGER NOT NULL,
        profile_img TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (company_id) REFERENCES companies(id)
    )
    """)

    # =====================================================
    # CHEF PROFILE
    # =====================================================
    cur.execute("""
    CREATE TABLE IF NOT EXISTS chef_profiles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chef_id INTEGER UNIQUE NOT NULL,
        charge_affectee INTEGER DEFAULT 0,
        score INTEGER DEFAULT 40,
        disponibilite_hebdo INTEGER DEFAULT 40,
        FOREIGN KEY (chef_id) REFERENCES users(id)
    )
    """)

    # =====================================================
    # RESSOURCE PROFILE
    # =====================================================
    cur.execute("""
    CREATE TABLE IF NOT EXISTS ressource_profiles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ressource_id INTEGER UNIQUE NOT NULL,
        chef_id INTEGER NOT NULL,
        niveau_experience INTEGER NOT NULL,
        disponibilite_hebdo INTEGER DEFAULT 40,
        cout_horaire REAL NOT NULL,
        charge_affectee INTEGER DEFAULT 0,
        competence_moyenne REAL DEFAULT 50,
        score INTEGER DEFAULT 50,
        FOREIGN KEY (ressource_id) REFERENCES users(id),
        FOREIGN KEY (chef_id) REFERENCES users(id)
    )
    """)

    con.commit()
    con.close()
    print("✅ Logical Database created successfully")

if __name__ == "__main__":
    create_db()
