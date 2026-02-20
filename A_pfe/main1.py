from flask import Flask, request, jsonify, send_from_directory
import sqlite3, os, uuid, bcrypt, jwt
from functools import wraps
from dotenv import load_dotenv as do
from datetime import datetime, timedelta
import score 
from apscheduler.schedulers.background import BackgroundScheduler

do()

# =========================
# CONFIGURATION
# =========================
MAX_IMAGE_SIZE = 3 * 1024 * 1024  # Maximum image size: 3MB
DB_NAME = "database.db"
SECRET = os.getenv("SECRET")
UPLOAD_FOLDER = os.getenv("folder", "images")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

app = Flask(__name__)

# =========================
# DATABASE HELPER
# =========================
def get_db():
    """
    Create database connection with Row factory for dict-like access
    Returns: connection and cursor objects
    """
    con = sqlite3.connect(DB_NAME, timeout=10, check_same_thread=False)
    con.row_factory = sqlite3.Row
    return con, con.cursor()

# =========================
# JWT VERIFICATION DECORATOR
# =========================
def verify_token(f):
    """
    Decorator to verify JWT token in Authorization header
    Extracts user data from token and passes to wrapped function
    """
    @wraps(f)
    def wrapper(*args, **kwargs):
        # Get Authorization header
        auth = request.headers.get("Authorization")
        if not auth:
            return jsonify({"error": "Authorization required"}), 401
        
        # Parse Bearer token
        parts = auth.split()
        if len(parts) != 2 or parts[0] != "Bearer":
            return jsonify({"error": "Invalid token format"}), 401
        
        token = parts[1]
        
        # Decode and verify token
        try:
            data = jwt.decode(token, SECRET, algorithms=["HS256"])
        except:
            return jsonify({"error": "Invalid or expired token"}), 401
        
        return f(data, *args, **kwargs)
    return wrapper

# =========================
# IMAGE UPLOAD HELPER
# =========================
def save_profile_img(file):
    """
    Validate and save uploaded profile image
    
    Args:
        file: FileStorage object from request.files
    
    Returns:
        tuple: (filename, error_message)
    """
    if not file or file.filename == "":
        return None, None
    
    # Validate file extension
    if '.' not in file.filename:
        return None, "Invalid file format"
    
    ext = file.filename.rsplit('.', 1)[-1].lower()
    if ext not in {"png", "jpg", "jpeg"}:
        return None, "Only PNG, JPG, JPEG allowed"

    # Validate file size
    file.seek(0, os.SEEK_END)
    size = file.tell()
    file.seek(0)  # Reset file pointer

    if size > MAX_IMAGE_SIZE:
        return None, "Image too large (max 3MB)"

    # Save file with unique name
    filename = f"{uuid.uuid4().hex}.{ext}"
    path = os.path.join(UPLOAD_FOLDER, filename)
    
    try:
        file.save(path)
        return filename, None
    except Exception as e:
        return None, f"Failed to save image: {str(e)}"

# =========================
# CHEF CHARGE CALCULATION (FIXED VERSION)
# =========================
def calculate_chef_charge(cur, chef_id):
    """
    Calculate chef's workload percentage
    
    Method: Calculate charge based on total estimated hours vs weekly capacity
    
    Args:
        cur: database cursor
        chef_id: ID of the chef
    
    Returns:
        float: Charge percentage (0-100)
    """
    # Step 1: Get team's total weekly capacity
    cur.execute("""
        SELECT disponibilite_hebdo
        FROM ressource_profiles
        WHERE chef_id=?
    """, (chef_id,))
    ressources = cur.fetchall()
    
    if not ressources:
        return 0
    
    # Total weekly capacity in hours
    weekly_capacity = sum(r["disponibilite_hebdo"] for r in ressources)
    
    if weekly_capacity == 0:
        return 0

    # Step 2: Get all active and planned projects
    cur.execute("""
        SELECT estimated_hours, start_date, end_date
        FROM projects
        WHERE chef_id=? AND status IN ('planned','active')
    """, (chef_id,))
    projects = cur.fetchall()
    
    if not projects:
        return 0

    try:
        # Step 3: Find the overall project timeline
        all_starts = []
        all_ends = []
        
        for p in projects:
            start = datetime.strptime(p["start_date"], "%Y-%m-%d")
            end = datetime.strptime(p["end_date"], "%Y-%m-%d")
            all_starts.append(start)
            all_ends.append(end)
        
        # Get earliest start and latest end date
        earliest_start = min(all_starts)
        latest_end = max(all_ends)
        
        # Calculate number of weeks in this period
        total_days = (latest_end - earliest_start).days + 1
        total_weeks = total_days / 7.0
        
        if total_weeks == 0:
            return 0
        
        # Step 4: Calculate total capacity for this period
        total_capacity = weekly_capacity * total_weeks
        
        # Step 5: Calculate total hours from all projects
        total_hours = sum(p["estimated_hours"] for p in projects)
        
        # Step 6: Calculate charge percentage
        charge = (total_hours / total_capacity) * 100
        
        # Cap at 100%
        return round(min(charge, 100), 2)
        
    except Exception as e:
        print(f"Error calculating charge: {e}")
        return 0
# =========================
# AUTOMATIC PROJECT STATUS & CHARGE UPDATE
# =========================
def update_projects_and_charge():
    """
    Background scheduler task that runs every 2 minutes to:
    1. Update project status based on dates (planned → active → finished)
    2. Update days_remaining for all projects
    3. Recalculate charge for all chefs
    """
    con, cur = get_db()
    try:
        today_date = datetime.now().date()
        
        # =========================
        # Step 1: Update project statuses
        # =========================
        cur.execute("SELECT * FROM projects")
        projects = cur.fetchall()

        for proj in projects:
            proj_id = proj["id"]
            status = proj["status"]

            # Parse project dates
            try:
                start_date = datetime.strptime(proj["start_date"], "%Y-%m-%d").date()
                end_date = datetime.strptime(proj["end_date"], "%Y-%m-%d").date()
            except Exception:
                continue

            new_status = status

            # Status transition logic
            if status == "planned":
                if today_date < start_date:
                    new_status = "planned"
                elif start_date <= today_date <= end_date:
                    new_status = "active"
                else:
                    new_status = "finished"

            elif status == "active":
                if today_date > end_date:
                    new_status = "finished"

            # Calculate days remaining
            if new_status == "planned":
                days_remaining = max((start_date - today_date).days, 0)
            elif new_status == "active":
                days_remaining = max((end_date - today_date).days, 0)
            else:  # finished
                days_remaining = 0

            # Update project
            cur.execute("""
                UPDATE projects
                SET status=?, days_remaining=?
                WHERE id=?
            """, (new_status, days_remaining, proj_id))

        # =========================
        # Step 2: Recalculate charge for all chefs
        # =========================
        cur.execute("SELECT id FROM users WHERE role='CHEF'")
        chefs = cur.fetchall()

        for chef in chefs:
            chef_id = chef["id"]
            new_charge = calculate_chef_charge(cur, chef_id)

            cur.execute("""
                UPDATE chef_profiles
                SET charge_affectee=?
                WHERE chef_id=?
            """, (new_charge, chef_id))

        con.commit()
        print(f"✅ Scheduler updated at {datetime.now()}")

    except Exception as e:
        print(f"❌ Scheduler Error: {e}")
    finally:
        con.close()

# =========================
# REGISTER COMPANY + RH
# =========================
@app.route("/register", methods=["POST"])
def register_company():
    """
    Register a new company with first RH (HR) user
    
    Form fields:
        - company_name: Company name
        - first_name, last_name: RH user name
        - email, password: RH credentials
        - profile_img: Optional profile image
    
    Returns:
        201: Company and RH created successfully
        400: Missing data or validation error
    """
    # Get form data
    company_name = request.form.get("company_name")
    first_name = request.form.get("first_name")
    last_name = request.form.get("last_name")
    email = request.form.get("email")
    password = request.form.get("password")
    profile_img = request.files.get("profile_img")

    # Validate required fields
    if not all([company_name, first_name, last_name, email, password]):
        return jsonify({"error": "Missing data"}), 400

    # Save profile image if provided
    filename, error = save_profile_img(profile_img)
    if error:
        return jsonify({"error": error}), 400

    # Hash password
    hashed_pw = bcrypt.hashpw(password.encode(), bcrypt.gensalt())

    con, cur = get_db()
    try:
        # Create company
        cur.execute("INSERT INTO companies (name) VALUES (?)", (company_name,))
        company_id = cur.lastrowid

        # Create RH user
        cur.execute("""
            INSERT INTO users (first_name, last_name, email, password, role, company_id, profile_img)
            VALUES (?,?,?,?,?,?,?)
        """, (first_name, last_name, email, hashed_pw, "RH", company_id, filename))
        
        con.commit()
        return jsonify({"msg": "Company & RH created"}), 201
    except sqlite3.IntegrityError as e:
        return jsonify({"error": str(e)}), 400
    finally:
        con.close()

# =========================
# LOGIN
# =========================
@app.route("/login", methods=["POST"])
def login():
    """
    User login with email and password
    
    Form fields:
        - email: User email
        - password: User password
    
    Returns:
        200: JWT token
        400: Missing credentials
        401: Invalid password
        404: User not found
    """
    email = request.form.get("email")
    password = request.form.get("password")
    
    if not email or not password:
        return jsonify({"error": "Missing email or password"}), 400

    con, cur = get_db()
    cur.execute("SELECT * FROM users WHERE email=?", (email,))
    user = cur.fetchone()
    con.close()

    if not user:
        return jsonify({"error": "User not found"}), 404
    
    if not bcrypt.checkpw(password.encode(), user["password"]):
        return jsonify({"error": "Invalid password"}), 401

    # Generate JWT token (valid for 24 hours)
    token = jwt.encode({
        "id": user["id"],
        "role": user["role"],
        "company_id": user["company_id"],
        "exp": datetime.utcnow() + timedelta(hours=24)
    }, SECRET, algorithm="HS256")

    return jsonify({"token": token}), 200

# =========================
# RH → ADD CHEF
# =========================
@app.route("/chef", methods=["POST"])
@verify_token
def add_chef(user):
    """
    RH adds a new CHEF to the company
    
    Required role: RH
    
    Form fields:
        - first_name, last_name: Chef name
        - email, password: Chef credentials
        - disponibilite_hebdo: Weekly availability hours (default: 100)
        - profile_img: Optional profile image
    
    Returns:
        201: Chef created successfully
        400: Missing data or validation error
        403: Permission denied (not RH)
    """
    # Verify RH permission
    if user["role"] != "RH":
        return jsonify({"error": "Permission denied"}), 403

    # Get form data
    first_name = request.form.get("first_name")
    last_name = request.form.get("last_name")
    email = request.form.get("email")
    password = request.form.get("password")
    dispo = request.form.get("disponibilite_hebdo", 100)
    profile_img = request.files.get("profile_img")

    # Validate required fields
    if not all([first_name, last_name, email, password]):
        return jsonify({"error": "Missing data"}), 400

    # Save profile image
    filename, error = save_profile_img(profile_img)
    if error:
        return jsonify({"error": error}), 400

    # Hash password
    hashed_pw = bcrypt.hashpw(password.encode(), bcrypt.gensalt())

    con, cur = get_db()
    try:
        # Create chef user
        cur.execute("""
            INSERT INTO users (first_name, last_name, email, password, role, company_id, profile_img)
            VALUES (?,?,?,?,?,?,?)
        """, (first_name, last_name, email, hashed_pw, "CHEF", user["company_id"], filename))
        chef_id = cur.lastrowid

        # Create chef profile
        cur.execute("""
            INSERT INTO chef_profiles (chef_id, charge_affectee, score, disponibilite_hebdo)
            VALUES (?,?,?,?)
        """, (chef_id, 0, 50, int(dispo)))
        
        con.commit()
        return jsonify({"msg": "Chef created"}), 201
    except sqlite3.IntegrityError as e:
        return jsonify({"error": str(e)}), 400
    finally:
        con.close()

# =========================
# ADD RESSOURCE (WITH AUTOMATIC CHARGE UPDATE)
# =========================
@app.route("/ressource", methods=["POST"])
@verify_token
def add_ressource(user):
    """
    Add a new resource to a chef's team
    
    Allowed roles: RH (can assign to any chef), CHEF (assigns to self)
    
    Form fields:
        - first_name, last_name: Resource name
        - email, password: Resource credentials
        - experience: Years of experience
        - cost_hour: Hourly cost
        - disponibilite_hebdo: Weekly availability hours
        - charge_affectee: Current workload percentage
        - competence_moyenne: Average skill level
        - chef_id: Required if called by RH
        - profile_img: Optional profile image
    
    Returns:
        201: Resource created, chef charge updated
        400: Missing data or validation error
        403: Permission denied
        404: Chef not found
    """
    # Get form data
    first_name = request.form.get("first_name")
    last_name = request.form.get("last_name")
    email = request.form.get("email")
    password = request.form.get("password")
    experience = int(request.form.get("experience", 5))
    cost_hour = float(request.form.get("cost_hour", 5))
    dispo = int(request.form.get("disponibilite_hebdo", 40))
    charge_affectee = int(request.form.get("charge_affectee", 0))
    competence_moyenne = float(request.form.get("competence_moyenne", 50))
    profile_img = request.files.get("profile_img")

    # Validate required fields
    if not all([first_name, last_name, email, password]):
        return jsonify({"error": "Missing data"}), 400

    # Determine chef_id based on user role
    if user["role"] == "RH":
        # RH must specify which chef
        chef_id = request.form.get("chef_id")
        if not chef_id:
            return jsonify({"error": "chef_id required"}), 400

        # Verify chef exists and belongs to same company
        con, cur = get_db()
        cur.execute("""
            SELECT * FROM users
            WHERE id=? AND role='CHEF' AND company_id=?
        """, (chef_id, user["company_id"]))
        chef = cur.fetchone()
        con.close()

        if not chef:
            return jsonify({"error": "Chef not found"}), 404

    elif user["role"] == "CHEF":
        # Chef adds resource to their own team
        chef_id = user["id"]
    else:
        return jsonify({"error": "Permission denied"}), 403

    # Calculate resource score
    new_score = score.ressource_score(
        experience, cost_hour, dispo, charge_affectee, competence_moyenne
    )

    # Save profile image
    filename, error = save_profile_img(profile_img)
    if error:
        return jsonify({"error": error}), 400

    # Hash password
    hashed_pw = bcrypt.hashpw(password.encode(), bcrypt.gensalt())

    con, cur = get_db()
    try:
        # Create resource user
        cur.execute("""
            INSERT INTO users
            (first_name, last_name, email, password, role, company_id, profile_img)
            VALUES (?,?,?,?,?,?,?)
        """, (first_name, last_name, email, hashed_pw, "RESSOURCE", user["company_id"], filename))

        res_id = cur.lastrowid

        # Create resource profile
        cur.execute("""
            INSERT INTO ressource_profiles (
                ressource_id, chef_id, niveau_experience, disponibilite_hebdo,
                cout_horaire, charge_affectee, competence_moyenne, score
            )
            VALUES (?,?,?,?,?,?,?,?)
        """, (res_id, chef_id, experience, dispo, cost_hour, charge_affectee, 
              competence_moyenne, round(new_score)))

        # 🔥 Recalculate chef's charge after adding new resource
        new_charge = calculate_chef_charge(cur, chef_id)
        cur.execute("""
            UPDATE chef_profiles
            SET charge_affectee=?
            WHERE chef_id=?
        """, (new_charge, chef_id))

        con.commit()

        return jsonify({
            "msg": "Ressource created",
            "chef_id": chef_id,
            "new_chef_charge": new_charge
        }), 201

    except sqlite3.IntegrityError as e:
        return jsonify({"error": str(e)}), 400
    finally:
        con.close()

# =========================
# UPDATE USER (WITH AUTOMATIC CHARGE UPDATE)
# =========================
@app.route("/user/update/<int:user_id>", methods=["PUT"])
@verify_token
def update_user(user, user_id):
    """
    Update user information
    
    Permissions:
        - RH: Can update anyone
        - CHEF: Can only update their own resources
    
    Form fields depend on user role being updated
    
    Returns:
        200: User updated successfully
        400: Validation error
        403: Permission denied
        404: User not found
    """
    con, cur = get_db()
    try:
        # Get target user data
        cur.execute("SELECT * FROM users WHERE id=?", (user_id,))
        target_user = cur.fetchone()
        
        if not target_user:
            return jsonify({"error": "User not found"}), 404

        # Verify permissions
        if user["role"] == "RH":
            pass  # RH can edit anyone
        elif user["role"] == "CHEF":
            # Chef can only edit their own resources
            if target_user["role"] != "RESSOURCE":
                return jsonify({"error": "Permission denied"}), 403
            
            cur.execute("""
                SELECT * FROM ressource_profiles 
                WHERE ressource_id=? AND chef_id=?
            """, (user_id, user["id"]))
            
            if not cur.fetchone():
                return jsonify({"error": "Permission denied"}), 403
        else:
            return jsonify({"error": "Permission denied"}), 403

        # Get updated data (keep existing if not provided)
        first_name = request.form.get("first_name", target_user["first_name"])
        last_name = request.form.get("last_name", target_user["last_name"])
        email = request.form.get("email", target_user["email"])
        password = request.form.get("password")
        profile_img = request.files.get("profile_img")

        # Handle profile image
        if profile_img:
            filename, error = save_profile_img(profile_img)
            if error:
                return jsonify({"error": error}), 400
        else:
            filename = target_user["profile_img"]

        # Handle password
        if password:
            hashed_pw = bcrypt.hashpw(password.encode(), bcrypt.gensalt())
        else:
            hashed_pw = target_user["password"]

        # Update users table
        cur.execute("""
            UPDATE users 
            SET first_name=?, last_name=?, email=?, password=?, profile_img=?
            WHERE id=?
        """, (first_name, last_name, email, hashed_pw, filename, user_id))

        # Update company name if RH updating themselves
        if target_user["role"] == "RH" and user["id"] == user_id:
            company_name = request.form.get("company_name")
            if company_name:
                cur.execute("""
                    UPDATE companies SET name=? WHERE id=?
                """, (company_name, target_user["company_id"]))

        # Update resource profile
        if target_user["role"] == "RESSOURCE":
            cur.execute("""
                SELECT chef_id FROM ressource_profiles 
                WHERE ressource_id=?
            """, (user_id,))
            profile = cur.fetchone()
            chef_id = profile["chef_id"] if profile else None

            experience = int(request.form.get("experience", 0))
            cost_hour = float(request.form.get("cost_hour", 0))
            dispo = int(request.form.get("disponibilite_hebdo", 40))
            charge_affectee = int(request.form.get("charge_affectee", 0))
            competence_moyenne = float(request.form.get("competence_moyenne", 50))

            new_score = score.ressource_score(
                experience, cost_hour, dispo, charge_affectee, competence_moyenne
            )

            cur.execute("""
                UPDATE ressource_profiles
                SET niveau_experience=?, disponibilite_hebdo=?, cout_horaire=?,
                    charge_affectee=?, competence_moyenne=?, score=?
                WHERE ressource_id=?
            """, (experience, dispo, cost_hour, charge_affectee, 
                  competence_moyenne, round(new_score), user_id))

            # 🔥 Recalculate chef's charge after updating resource
            if chef_id:
                new_charge = calculate_chef_charge(cur, chef_id)
                cur.execute("""
                    UPDATE chef_profiles
                    SET charge_affectee=?
                    WHERE chef_id=?
                """, (new_charge, chef_id))

        # Update chef profile
        elif target_user["role"] == "CHEF":
            dispo = int(request.form.get("disponibilite_hebdo", 40))
            cur.execute("""
                UPDATE chef_profiles 
                SET disponibilite_hebdo=?
                WHERE chef_id=?
            """, (dispo, user_id))

        con.commit()
        return jsonify({"msg": "User updated"}), 200

    except sqlite3.IntegrityError as e:
        return jsonify({"error": str(e)}), 400
    finally:
        con.close()

# =========================
# DELETE USER (WITH AUTOMATIC CHARGE UPDATE)
# =========================
@app.route("/user/delete/<int:user_id>", methods=["DELETE"])
@verify_token
def delete_user(user, user_id):
    """
    Delete a user
    
    Permissions:
        - RH: Can delete anyone except themselves
        - CHEF: Can only delete their own resources
    
    Returns:
        200: User deleted successfully
        403: Permission denied or trying to delete self (RH)
        404: User not found
    """
    con, cur = get_db()
    try:
        # Get target user
        cur.execute("SELECT * FROM users WHERE id=?", (user_id,))
        target_user = cur.fetchone()
        
        if not target_user:
            return jsonify({"error": "User not found"}), 404

        # RH cannot delete themselves
        if user["role"] == "RH" and target_user["role"] == "RH" and user["id"] == user_id:
            return jsonify({"error": "Cannot delete your own RH account"}), 403

        chef_id_to_update = None

        # Verify permissions
        if user["role"] == "RH":
            pass  # RH can delete anyone
        elif user["role"] == "CHEF":
            # Chef can only delete their own resources
            if target_user["role"] != "RESSOURCE":
                return jsonify({"error": "Permission denied"}), 403
            
            cur.execute("""
                SELECT chef_id FROM ressource_profiles 
                WHERE ressource_id=? AND chef_id=?
            """, (user_id, user["id"]))
            profile = cur.fetchone()
            
            if not profile:
                return jsonify({"error": "Permission denied"}), 403
            
            chef_id_to_update = profile["chef_id"]
        else:
            return jsonify({"error": "Permission denied"}), 403

        # Delete related profiles
        if target_user["role"] == "CHEF":
            cur.execute("DELETE FROM chef_profiles WHERE chef_id=?", (user_id,))
            
        elif target_user["role"] == "RESSOURCE":
            # Get chef_id before deletion
            if not chef_id_to_update:
                cur.execute("""
                    SELECT chef_id FROM ressource_profiles 
                    WHERE ressource_id=?
                """, (user_id,))
                profile = cur.fetchone()
                if profile:
                    chef_id_to_update = profile["chef_id"]
            
            cur.execute("DELETE FROM ressource_profiles WHERE ressource_id=?", (user_id,))

        # Delete user
        cur.execute("DELETE FROM users WHERE id=?", (user_id,))

        # 🔥 Recalculate chef's charge after deleting resource
        if chef_id_to_update:
            new_charge = calculate_chef_charge(cur, chef_id_to_update)
            cur.execute("""
                UPDATE chef_profiles
                SET charge_affectee=?
                WHERE chef_id=?
            """, (new_charge, chef_id_to_update))

        con.commit()
        return jsonify({"msg": "User deleted"}), 200

    finally:
        con.close()

# =========================
# DASHBOARD RESOURCES
# =========================
@app.route("/dashboard/resources", methods=["GET"])
@verify_token
def dashboard_resources(user):
    """
    Get resources dashboard
    
    For RH: Returns all chefs with their resources
    For CHEF: Returns only their own resources
    
    Returns:
        200: Resources data
        403: Permission denied
    """
    con, cur = get_db()
    try:
        if user["role"] == "RH":
            # RH sees all chefs with their resources
            cur.execute("""
                SELECT
                    c.id AS chef_id,
                    c.first_name AS chef_first_name,
                    c.last_name AS chef_last_name,
                    c.email AS chef_email,
                    c.profile_img AS chef_profile_img,
                    cp.charge_affectee AS chef_charge,
                    cp.disponibilite_hebdo AS chef_disponibilite,
                    cp.score AS chef_score,

                    u.id AS ressource_id,
                    u.first_name AS ressource_first_name,
                    u.last_name AS ressource_last_name,
                    u.email AS ressource_email,
                    u.profile_img AS ressource_profile_img,

                    rp.niveau_experience,
                    rp.disponibilite_hebdo,
                    rp.cout_horaire,
                    rp.charge_affectee,
                    rp.competence_moyenne,
                    rp.score AS ressource_score

                FROM users c
                LEFT JOIN chef_profiles cp ON cp.chef_id = c.id
                LEFT JOIN ressource_profiles rp ON rp.chef_id = c.id
                LEFT JOIN users u ON u.id = rp.ressource_id
                WHERE c.role = 'CHEF' AND c.company_id = ?
                ORDER BY c.id
            """, (user["company_id"],))

            rows = cur.fetchall()
            chefs = {}

            # Group resources by chef
            for r in rows:
                chef_id = r["chef_id"]

                if chef_id not in chefs:
                    chefs[chef_id] = {
                        "chef": {
                            "id": chef_id,
                            "first_name": r["chef_first_name"],
                            "last_name": r["chef_last_name"],
                            "email": r["chef_email"],
                            "profile_img": r["chef_profile_img"],
                            "charge_affectee": r["chef_charge"],
                            "disponibilite_hebdo": r["chef_disponibilite"],
                            "score": r["chef_score"]
                        },
                        "resources": []
                    }

                if r["ressource_id"]:
                    chefs[chef_id]["resources"].append({
                        "id": r["ressource_id"],
                        "first_name": r["ressource_first_name"],
                        "last_name": r["ressource_last_name"],
                        "email": r["ressource_email"],
                        "profile_img": r["ressource_profile_img"],
                        "niveau_experience": r["niveau_experience"],
                        "disponibilite_hebdo": r["disponibilite_hebdo"],
                        "cout_horaire": r["cout_horaire"],
                        "charge_affectee": r["charge_affectee"],
                        "competence_moyenne": r["competence_moyenne"],
                        "score": r["ressource_score"]
                    })

            return jsonify(list(chefs.values())), 200

        elif user["role"] == "CHEF":
            # Chef sees only their resources
            cur.execute("""
                SELECT
                    u.id, u.first_name, u.last_name, u.email, u.profile_img,
                    rp.niveau_experience, rp.disponibilite_hebdo, rp.cout_horaire,
                    rp.charge_affectee, rp.competence_moyenne, rp.score
                FROM users u
                JOIN ressource_profiles rp ON rp.ressource_id = u.id
                WHERE rp.chef_id = ?
            """, (user["id"],))

            resources = [dict(row) for row in cur.fetchall()]
            return jsonify(resources), 200

        else:
            return jsonify({"error": "Permission denied"}), 403

    finally:
        con.close()

# =========================
# CREATE PROJECT (WITH IMPROVED VALIDATION)
# =========================
@app.route("/project/create", methods=["POST"])
@verify_token
def create_project(user):
    """
    Create a new project
    Required role: RH only
    
    Validates that adding this project won't overload the chef (>100%)
    Uses the SAME calculation method as calculate_chef_charge()
    """
    if user["role"] != "RH":
        return jsonify({"error": "Permission denied"}), 403

    # Get form data
    name = request.form.get("name")
    description = request.form.get("description", "")
    difficulty = request.form.get("difficulty", "medium")
    estimated_hours = request.form.get("estimated_hours")
    chef_id = request.form.get("chef_id")
    start_date = request.form.get("start_date")
    end_date = request.form.get("end_date")

    # Validate required fields
    if not all([name, estimated_hours, chef_id, start_date, end_date]):
        return jsonify({"error": "Missing data"}), 400

    # Parse data types
    try:
        estimated_hours = int(estimated_hours)
        chef_id = int(chef_id)
    except ValueError:
        return jsonify({"error": "Invalid data types"}), 400
    
    # Parse dates
    try:
        d1 = datetime.strptime(start_date, "%Y-%m-%d").date()
        d2 = datetime.strptime(end_date, "%Y-%m-%d").date()
    except:
        return jsonify({"error": "Invalid date format"}), 400

    if d2 <= d1:
        return jsonify({"error": "End date must be after start date"}), 400

    today = datetime.now().date()

    con, cur = get_db()

    try:
        # Step 1: Verify chef exists
        cur.execute("""
            SELECT id FROM users
            WHERE id=? AND role='CHEF' AND company_id=?
        """, (chef_id, user["company_id"]))

        if not cur.fetchone():
            return jsonify({"error": "Chef not found"}), 404

        # Step 2: Get chef's team capacity
        cur.execute("""
            SELECT disponibilite_hebdo
            FROM ressource_profiles
            WHERE chef_id=?
        """, (chef_id,))

        ressources = cur.fetchall()
        
        if not ressources:
            return jsonify({
                "error": "Chef has no resources",
                "suggestion": "Add resources first"
            }), 400

        # Calculate weekly capacity
        weekly_capacity = sum(r["disponibilite_hebdo"] for r in ressources)
        
        if weekly_capacity == 0:
            return jsonify({"error": "Team has no capacity"}), 400

        # Step 3: Get all existing active/planned projects
        cur.execute("""
            SELECT estimated_hours, start_date, end_date
            FROM projects
            WHERE chef_id=? AND status IN ('active','planned')
        """, (chef_id,))
        
        existing_projects = cur.fetchall()

        # Step 4: Calculate FUTURE charge (if we add this project)
        # Simulate adding the new project temporarily
        try:
            all_starts = [datetime.strptime(start_date, "%Y-%m-%d")]
            all_ends = [datetime.strptime(end_date, "%Y-%m-%d")]
            total_hours = estimated_hours
            
            # Add existing projects
            for p in existing_projects:
                start = datetime.strptime(p["start_date"], "%Y-%m-%d")
                end = datetime.strptime(p["end_date"], "%Y-%m-%d")
                all_starts.append(start)
                all_ends.append(end)
                total_hours += p["estimated_hours"]
            
            # Calculate overall timeline
            earliest_start = min(all_starts)
            latest_end = max(all_ends)
            
            total_days = (latest_end - earliest_start).days + 1
            total_weeks = total_days / 7.0
            
            # Calculate future capacity and charge
            future_capacity = weekly_capacity * total_weeks
            future_charge = (total_hours / future_capacity) * 100
            
            print(f"""
            ===== PROJECT CREATION VALIDATION =====
            Chef ID: {chef_id}
            Weekly Capacity: {weekly_capacity} hours
            New Project: {estimated_hours} hours ({start_date} to {end_date})
            Existing Projects: {len(existing_projects)}
            Future Timeline: {earliest_start.date()} to {latest_end.date()}
            Total Weeks: {total_weeks:.2f}
            Future Capacity: {future_capacity:.2f} hours
            Total Hours (if added): {total_hours}
            Future Charge: {future_charge:.2f}%
            =======================================
            """)
            
            # Validate: prevent overload
            if future_charge > 100:
                return jsonify({
                    "error": "Chef will be overloaded",
                    "current_charge": calculate_chef_charge(cur, chef_id),
                    "future_charge": round(future_charge, 2),
                    "available_hours": round(future_capacity - (total_hours - estimated_hours), 2),
                    "weekly_capacity": weekly_capacity
                }), 400
            
        except Exception as e:
            print(f"❌ Validation error: {e}")
            return jsonify({"error": f"Validation failed: {str(e)}"}), 500

        # Step 5: Determine initial project status
        if today < d1:
            status = "planned"
            days_remaining = (d1 - today).days
        elif d1 <= today <= d2:
            status = "active"
            days_remaining = (d2 - today).days
        else:
            status = "finished"
            days_remaining = 0

        duration = (d2 - d1).days

        # Step 6: Create the project
        cur.execute("""
            INSERT INTO projects
            (name, description, estimated_hours, chef_id, company_id,
             start_date, end_date, duration_days, days_remaining, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            name,
            description,
            estimated_hours,
            chef_id,
            user["company_id"],
            start_date,
            end_date,
            duration,
            days_remaining,
            status
        ))

        project_id = cur.lastrowid

        # Step 7: Recalculate chef's actual charge
        new_charge = calculate_chef_charge(cur, chef_id)

        cur.execute("""
            UPDATE chef_profiles
            SET charge_affectee=?
            WHERE chef_id=?
        """, (new_charge, chef_id))

        con.commit()

        return jsonify({
            "msg": "Project created successfully",
            "project_id": project_id,
            "initial_status": status,
            "chef_current_charge": new_charge,
            "weekly_capacity": weekly_capacity
        }), 201

    except Exception as e:
        con.rollback()
        print(f"❌ Error creating project: {e}")
        return jsonify({"error": str(e)}), 500

    finally:
        con.close()
# =========================
# GET ALL PROJECTS
# =========================
@app.route("/projects", methods=["GET"])
@verify_token
def get_projects(user):
    """
    Get all projects
    
    For RH: Returns all company projects
    For CHEF: Returns only their assigned projects
    
    Returns:
        200: Projects list with statistics
        403: Permission denied
    """
    con, cur = get_db()
    try:
        if user["role"] == "RH":
            # RH sees all company projects
            cur.execute("""
                SELECT 
                    p.*,
                    u.first_name AS chef_first_name,
                    u.last_name AS chef_last_name,
                    u.profile_img AS chef_profile_img
                FROM projects p
                JOIN users u ON u.id = p.chef_id
                WHERE p.company_id=?
                ORDER BY 
                    CASE p.status
                        WHEN 'active' THEN 1
                        WHEN 'planned' THEN 2
                        WHEN 'finished' THEN 3
                    END,
                    p.start_date DESC
            """, (user["company_id"],))

        elif user["role"] == "CHEF":
            # Chef sees only their projects
            cur.execute("""
                SELECT * FROM projects
                WHERE chef_id=?
                ORDER BY 
                    CASE status
                        WHEN 'active' THEN 1
                        WHEN 'planned' THEN 2
                        WHEN 'finished' THEN 3
                    END,
                    start_date DESC
            """, (user["id"],))

        else:
            return jsonify({"error": "Permission denied"}), 403

        projects = [dict(row) for row in cur.fetchall()]
        
        # Calculate statistics
        stats = {
            "total": len(projects),
            "active": sum(1 for p in projects if p["status"] == "active"),
            "planned": sum(1 for p in projects if p["status"] == "planned"),
            "finished": sum(1 for p in projects if p["status"] == "finished")
        }

        return jsonify({
            "stats": stats,
            "projects": projects
        }), 200

    finally:
        con.close()

# =========================
# GET SINGLE PROJECT
# =========================
@app.route("/project/<int:project_id>", methods=["GET"])
@verify_token
def get_project(user, project_id):
    """
    Get single project details
    
    Returns:
        200: Project details
        403: Permission denied (CHEF accessing other's project)
        404: Project not found
    """
    con, cur = get_db()
    try:
        cur.execute("""
            SELECT 
                p.*,
                u.first_name AS chef_first_name,
                u.last_name AS chef_last_name,
                u.email AS chef_email,
                u.profile_img AS chef_profile_img
            FROM projects p
            JOIN users u ON u.id = p.chef_id
            WHERE p.id=? AND p.company_id=?
        """, (project_id, user["company_id"]))

        project = cur.fetchone()

        if not project:
            return jsonify({"error": "Project not found"}), 404

        # Verify CHEF permission
        if user["role"] == "CHEF" and project["chef_id"] != user["id"]:
            return jsonify({"error": "Permission denied"}), 403

        return jsonify(dict(project)), 200

    finally:
        con.close()

# =========================
# UPDATE PROJECT (WITH AUTOMATIC CHARGE UPDATE)
# =========================
@app.route("/project/update/<int:project_id>", methods=["PUT"])
@verify_token
def update_project(user, project_id):
    """
    Update project details
    
    Required role: RH only
    
    Returns:
        200: Project updated, chef charge recalculated
        400: Validation error or would cause overload
        403: Permission denied
        404: Project not found
    """
    if user["role"] != "RH":
        return jsonify({"error": "Permission denied"}), 403

    con, cur = get_db()
    try:
        # Get existing project
        cur.execute("""
            SELECT * FROM projects 
            WHERE id=? AND company_id=?
        """, (project_id, user["company_id"]))

        project = cur.fetchone()
        if not project:
            return jsonify({"error": "Project not found"}), 404

        # Get updated data (keep existing if not provided)
        name = request.form.get("name", project["name"])
        description = request.form.get("description", project["description"])
        estimated_hours = request.form.get("estimated_hours", project["estimated_hours"])
        start_date = request.form.get("start_date", project["start_date"])
        end_date = request.form.get("end_date", project["end_date"])
        status = request.form.get("status", project["status"])

        try:
            estimated_hours = int(estimated_hours)
        except ValueError:
            return jsonify({"error": "Invalid estimated_hours"}), 400

        # Calculate new duration
        d1 = datetime.strptime(start_date, "%Y-%m-%d")
        d2 = datetime.strptime(end_date, "%Y-%m-%d")
        duration = (d2 - d1).days

        if duration < 0:
            return jsonify({"error": "End date must be after start date"}), 400

        # Verify workload if hours changed
        if estimated_hours != project["estimated_hours"]:
            chef_id = project["chef_id"]

            cur.execute("""
                SELECT disponibilite_hebdo
                FROM ressource_profiles
                WHERE chef_id=?
            """, (chef_id,))
            ressources = cur.fetchall()

            total_capacity = sum(r["disponibilite_hebdo"] * 4 for r in ressources)

            if total_capacity > 0:
                # Calculate hours from other active projects
                cur.execute("""
                    SELECT estimated_hours
                    FROM projects
                    WHERE chef_id=? AND status='active' AND id!=?
                """, (chef_id, project_id))
                
                other_projects = cur.fetchall()
                total_other = sum(p["estimated_hours"] for p in other_projects)

                future_charge = ((total_other + estimated_hours) / total_capacity) * 100

                if future_charge > 100:
                    return jsonify({
                        "error": "Changes will overload chef",
                        "future_charge": round(future_charge)
                    }), 400

        # Update project
        cur.execute("""
            UPDATE projects
            SET name=?, description=?, estimated_hours=?,
                start_date=?, end_date=?, duration_days=?, status=?
            WHERE id=?
        """, (name, description, estimated_hours, start_date, end_date, 
              duration, status, project_id))

        # 🔥 Recalculate chef's charge
        new_charge = calculate_chef_charge(cur, project["chef_id"])
        cur.execute("""
            UPDATE chef_profiles
            SET charge_affectee=?
            WHERE chef_id=?
        """, (new_charge, project["chef_id"]))

        con.commit()

        return jsonify({
            "msg": "Project updated",
            "chef_charge": new_charge
        }), 200

    finally:
        con.close()

# =========================
# DELETE PROJECT (WITH AUTOMATIC CHARGE UPDATE)
# =========================
@app.route("/project/delete/<int:project_id>", methods=["DELETE"])
@verify_token
def delete_project(user, project_id):
    """
    Delete a project
    
    Required role: RH only
    
    Returns:
        200: Project deleted, chef charge recalculated
        403: Permission denied
        404: Project not found
    """
    if user["role"] != "RH":
        return jsonify({"error": "Permission denied"}), 403

    con, cur = get_db()
    try:
        # Get project
        cur.execute("""
            SELECT chef_id FROM projects 
            WHERE id=? AND company_id=?
        """, (project_id, user["company_id"]))

        project = cur.fetchone()
        if not project:
            return jsonify({"error": "Project not found"}), 404

        chef_id = project["chef_id"]

        # Delete project
        cur.execute("DELETE FROM projects WHERE id=?", (project_id,))

        # 🔥 Recalculate chef's charge after deletion
        new_charge = calculate_chef_charge(cur, chef_id)
        cur.execute("""
            UPDATE chef_profiles
            SET charge_affectee=?
            WHERE chef_id=?
        """, (new_charge, chef_id))

        con.commit()

        return jsonify({
            "msg": "Project deleted",
            "chef_charge": new_charge
        }), 200

    finally:
        con.close()

# =========================
# GET USER PROFILE
# =========================
@app.route("/me", methods=["GET"])
@verify_token
def get_my_profile(user):
    """
    Get current user's profile information
    
    Returns:
        200: User profile data (password excluded)
        404: User not found
    """
    con, cur = get_db()
    try:
        cur.execute("""
            SELECT 
                u.*,
                c.name AS company_name
            FROM users u
            JOIN companies c ON c.id = u.company_id
            WHERE u.id=?
        """, (user["id"],))

        user_data = cur.fetchone()

        if not user_data:
            return jsonify({"error": "User not found"}), 404

        result = dict(user_data)
        
        # Add role-specific profile data
        if user_data["role"] == "CHEF":
            cur.execute("""
                SELECT * FROM chef_profiles WHERE chef_id=?
            """, (user["id"],))
            profile = cur.fetchone()
            if profile:
                result["profile"] = dict(profile)

        elif user_data["role"] == "RESSOURCE":
            cur.execute("""
                SELECT * FROM ressource_profiles WHERE ressource_id=?
            """, (user["id"],))
            profile = cur.fetchone()
            if profile:
                result["profile"] = dict(profile)

        # Remove password from response
        result.pop("password", None)

        return jsonify(result), 200

    finally:
        con.close()

# =========================
# SERVE UPLOADED IMAGES
# =========================
@app.route("/images/<filename>")
def get_image(filename):
    """
    Serve uploaded profile images
    
    Args:
        filename: Image filename
    
    Returns:
        Image file
    """
    return send_from_directory(UPLOAD_FOLDER, filename)

# =========================
# HEALTH CHECK
# =========================
@app.route("/health", methods=["GET"])
def health_check():
    """
    API health check endpoint
    
    Returns:
        200: API is healthy with current timestamp
    """
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.now().isoformat()
    }), 200

# =========================
# COMPANY STATISTICS
# =========================
@app.route("/statistics", methods=["GET"])
@verify_token
def get_statistics(user):
    """
    Get company statistics
    
    Required role: RH only
    
    Returns:
        200: Statistics about chefs, resources, projects, and average charge
        403: Permission denied
    """
    con, cur = get_db()
    try:
        if user["role"] != "RH":
            return jsonify({"error": "Permission denied"}), 403
        
        # Count chefs
        cur.execute("""
            SELECT COUNT(*) as count 
            FROM users 
            WHERE role='CHEF' AND company_id=?
        """, (user["company_id"],))
        chefs_count = cur.fetchone()["count"]
        
        # Count resources
        cur.execute("""
            SELECT COUNT(*) as count 
            FROM users 
            WHERE role='RESSOURCE' AND company_id=?
        """, (user["company_id"],))
        resources_count = cur.fetchone()["count"]
        
        # Projects by status
        cur.execute("""
            SELECT status, COUNT(*) as count
            FROM projects
            WHERE company_id=?
            GROUP BY status
        """, (user["company_id"],))
        projects_stats = {row["status"]: row["count"] for row in cur.fetchall()}
        
        # Average chef charge
        cur.execute("""
            SELECT AVG(charge_affectee) as avg_charge
            FROM chef_profiles cp
            JOIN users u ON u.id = cp.chef_id
            WHERE u.company_id=?
        """, (user["company_id"],))
        avg_charge = cur.fetchone()["avg_charge"] or 0
        
        return jsonify({
            "chefs": chefs_count,
            "resources": resources_count,
            "projects": projects_stats,
            "average_charge": round(avg_charge, 2)
        }), 200
        
    finally:
        con.close()

# =========================
# ERROR HANDLERS
# =========================
@app.errorhandler(404)
def not_found(error):
    """Handle 404 errors"""
    return jsonify({"error": "Endpoint not found"}), 404

@app.errorhandler(500)
def internal_error(error):
    """Handle 500 errors"""
    return jsonify({"error": "Internal server error"}), 500

# =========================
# RUN APPLICATION
# =========================
# if __name__ == "__main__":
#     # Start background scheduler for automatic updates
#     scheduler = BackgroundScheduler()
#     scheduler.add_job(update_projects_and_charge, "interval", minutes=6)
#     scheduler.start()
    
#     # Run Flask app
#     app.run(debug=True, host="0.0.0.0", port=5000)

# Initialize scheduler globally (runs once)
scheduler = BackgroundScheduler()
scheduler.add_job(update_projects_and_charge, "interval", minutes=6)
scheduler.start()

if __name__ == "__main__":
    import os
    
    # Check if running in production
    is_production = os.getenv('FLASK_ENV') == 'production'
    
    if is_production:
        # Production: Use Waitress or Gunicorn (not this)
        print("⚠️  Use 'python run_production.py' for production!")
    else:
        # Development only
        app.run(debug=True, host="0.0.0.0", port=5000)