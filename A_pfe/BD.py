import sqlite3
import os
DB_NAME = "database.db"

def create_db():
    con = sqlite3.connect(DB_NAME)
    cur = con.cursor()
    cur.execute("PRAGMA foreign_keys = ON;")

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
        FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE
    )
    """)

    # =====================================================
    # CHEF PROFILE 
    # =====================================================
    cur.execute("""
    CREATE TABLE IF NOT EXISTS chef_profiles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chef_id INTEGER UNIQUE NOT NULL,
        charge_affectee REAL DEFAULT 0 CHECK(charge_affectee >= 0 AND charge_affectee <= 100),
        score INTEGER DEFAULT 50 CHECK(score >= 0 AND score <= 100),
        disponibilite_hebdo INTEGER DEFAULT 40 CHECK(disponibilite_hebdo >= 0 AND disponibilite_hebdo <= 168),
        FOREIGN KEY (chef_id) REFERENCES users(id) ON DELETE CASCADE
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
        niveau_experience INTEGER NOT NULL CHECK(niveau_experience >= 0 AND niveau_experience <= 20),
        disponibilite_hebdo INTEGER DEFAULT 40 CHECK(disponibilite_hebdo >= 0 AND disponibilite_hebdo <= 168),
        cout_horaire REAL NOT NULL CHECK(cout_horaire >= 0),
        charge_affectee INTEGER DEFAULT 0 CHECK(charge_affectee >= 0 AND charge_affectee <= 100),
        competence_moyenne REAL DEFAULT 50 CHECK(competence_moyenne >= 0 AND competence_moyenne <= 100),
        score INTEGER DEFAULT 50 CHECK(score >= 0 AND score <= 100),
        FOREIGN KEY (ressource_id) REFERENCES users(id) ON DELETE CASCADE,
        FOREIGN KEY (chef_id) REFERENCES users(id) ON DELETE CASCADE
    )
    """)

    # =====================================================
    # PROJECTS (estimated_hours)
    # =====================================================
    cur.execute("""
    CREATE TABLE IF NOT EXISTS projects (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        description TEXT,
        difficulty TEXT CHECK(difficulty IN ('easy','medium','hard')),
        estimated_hours INTEGER NOT NULL CHECK(estimated_hours > 0),
        start_date TEXT NOT NULL,
        end_date TEXT NOT NULL,
        duration_days INTEGER CHECK(duration_days >= 0),
        days_remaining INTEGER DEFAULT 0,
        status TEXT CHECK(status IN ('planned','active','finished')) DEFAULT 'planned',
        company_id INTEGER NOT NULL,
        chef_id INTEGER NOT NULL,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE,
        FOREIGN KEY (chef_id) REFERENCES users(id) ON DELETE CASCADE
    )
    """)

    # =====================================================
    # TASKS 
    # =====================================================
    cur.execute("""
    CREATE TABLE IF NOT EXISTS tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER NOT NULL,
        ressource_id INTEGER,
        title TEXT NOT NULL,
        description TEXT,
        priority TEXT CHECK(priority IN ('low','medium','high','urgent')) DEFAULT 'medium',
        status TEXT CHECK(status IN ('todo','in_progress','review','done')) DEFAULT 'todo',
        estimated_hours REAL DEFAULT 0,
        actual_hours REAL DEFAULT 0,
        start_date TEXT,
        end_date TEXT,
        completed_at TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
        FOREIGN KEY (ressource_id) REFERENCES users(id) ON DELETE SET NULL
    )
    """)

    # =====================================================
    # TASK COMMENTS 
    # =====================================================
    cur.execute("""
    CREATE TABLE IF NOT EXISTS task_comments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        comment TEXT NOT NULL,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE,
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
    )
    """)

    # =====================================================
    # TASK ATTACHMENTS 
    # =====================================================
    cur.execute("""
    CREATE TABLE IF NOT EXISTS task_attachments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id INTEGER NOT NULL,
        filename TEXT NOT NULL,
        uploaded_by INTEGER NOT NULL,
        uploaded_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE,
        FOREIGN KEY (uploaded_by) REFERENCES users(id) ON DELETE CASCADE
    )
    """)

    # =====================================================
    # NOTIFICATIONS 
    # =====================================================
    cur.execute("""
    CREATE TABLE IF NOT EXISTS notifications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        title TEXT NOT NULL,
        message TEXT NOT NULL,
        type TEXT CHECK(type IN ('task_assigned','deadline_near','project_created','status_change')) NOT NULL,
        is_read BOOLEAN DEFAULT 0,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
    )
    """)

    # =====================================================
    # ACTIVITY LOG 
    # =====================================================
    cur.execute("""
    CREATE TABLE IF NOT EXISTS activity_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        action TEXT NOT NULL,
        entity_type TEXT CHECK(entity_type IN ('task','project','user','comment')) NOT NULL,
        entity_id INTEGER NOT NULL,
        details TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
    )
    """)

    # =====================================================
    # INDEXES 
    # =====================================================
    cur.execute("CREATE INDEX IF NOT EXISTS idx_users_email ON users(email)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_users_company ON users(company_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_users_role ON users(role)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_projects_chef ON projects(chef_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_projects_status ON projects(status)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_projects_company ON projects(company_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_ressource_chef ON ressource_profiles(chef_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_tasks_project ON tasks(project_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_tasks_ressource ON tasks(ressource_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_notifications_user ON notifications(user_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_activity_user ON activity_log(user_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_comments_task ON task_comments(task_id)")

    con.commit()
    con.close()
    print("✅ database is created")

if __name__ == "__main__":
    if os.path.exists(DB_NAME):
        confirm = input("you want to delete DB(yes/no): ")
        if confirm.lower() == "yes":
            os.remove(DB_NAME)
            print("🗑️  database is deleted")
        else:
            print("❌ no")
            exit()  
    create_db()