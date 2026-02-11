from flask import Flask, request, jsonify, send_from_directory
import sqlite3, os, uuid, bcrypt, jwt
from functools import wraps
from dotenv import load_dotenv as do
from datetime import datetime, timedelta
import score 
from apscheduler.schedulers.background import BackgroundScheduler
do()

DB_NAME = "database.db"
SECRET = os.getenv("SECRET")
UPLOAD_FOLDER = os.getenv("folder","images")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

app = Flask(__name__)

# =========================
# DB Helper
# =========================
def get_db():
    con = sqlite3.connect(DB_NAME,timeout=10, check_same_thread=False)
    con.row_factory = sqlite3.Row
    return con, con.cursor()
# =========================
# JWT Verification
# =========================
def verify_token(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        auth = request.headers.get("Authorization")
        if not auth:
            return jsonify({"error":"Authorization required"}), 401
        parts = auth.split()
        if len(parts)!=2 or parts[0]!="Bearer":
            return jsonify({"error":"Invalid token format"}),401
        token=parts[1]
        try:
            data = jwt.decode(token, SECRET, algorithms=["HS256"])
        except:
            return jsonify({"error":"Invalid or expired token"}),401
        return f(data, *args, **kwargs)
    return wrapper

# =========================
# Helper: Save profile image
# =========================
def save_profile_img(file):
    if not file:
        return None
    ext = file.filename.rsplit('.',1)[-1].lower()
    if ext not in {"png","jpg","jpeg"}:
        return None
    filename = f"{uuid.uuid4().hex}.{ext}"
    path = os.path.join(UPLOAD_FOLDER, filename)
    file.save(path)
    return filename

# =========================
# calc charge chaque 30 min
# =========================

def difficulty_to_percentage(difficulty):
    return {
        "easy": 15,
        "medium": 40,
        "hard": 65
    }.get(difficulty, 0)


 # =========================
 # 1️⃣ Update project status + days_remaining
 # =========================
def update_projects_and_charge():
    con, cur = get_db()
    try:
        today_date = datetime.now().date()
        cur.execute("SELECT * FROM projects")
        projects = cur.fetchall()
        for proj in projects:
            proj_id = proj["id"]
            chef_id = proj["chef_id"]
            status = proj["status"]

            try:
                start_date = datetime.strptime(proj["start_date"], "%Y-%m-%d").date()
                end_date = datetime.strptime(proj["end_date"], "%Y-%m-%d").date()
            except:
                continue  
            new_status = status

            # planned → active
            if status == "planned" and today_date >= start_date:
                new_status = "active"

            # active → finished
            if status == "active" and today_date > end_date:
                new_status = "finished"

         
            if new_status == "active":
                days_remaining = (end_date - today_date).days
                if days_remaining < 0:
                    days_remaining = 0

            elif new_status == "planned":
                days_remaining = (start_date - today_date).days
                if days_remaining < 0:
                    days_remaining = 0

            else:
                days_remaining = 0

            
            cur.execute("""
                UPDATE projects
                SET status=?, days_remaining=?
                WHERE id=?
            """, (new_status, days_remaining, proj_id))

        # =========================
        # 2️⃣ Recalculate charge for each CHEF
        # =========================
        cur.execute("SELECT id FROM users WHERE role='CHEF'")
        chefs = cur.fetchall()

        for chef in chefs:
            chef_id = chef["id"]

            cur.execute("""
                SELECT difficulty FROM projects
                WHERE chef_id=? AND status='active'
            """, (chef_id,))
            active_projects = cur.fetchall()

            total_charge = 0

            for p in active_projects:
                total_charge += difficulty_to_percentage(p["difficulty"])

            total_charge = min(total_charge, 100)

            cur.execute("""
                UPDATE chef_profiles
                SET charge_affectee=?
                WHERE chef_id=?
            """, (total_charge, chef_id))

        con.commit()
        print("Auto update: status + charge + days_remaining updated")

    except Exception as e:
        print("Scheduler Error:", e)

    finally:
        con.close()


scheduler = BackgroundScheduler()
scheduler.add_job(update_projects_and_charge, "interval", minutes=4)
scheduler.start()

# =========================
# REGISTER COMPANY + RH
# =========================
@app.route("/register", methods=["POST"])
def register_company():
    company_name = request.form.get("company_name")
    first_name = request.form.get("first_name")
    last_name = request.form.get("last_name")
    email = request.form.get("email")
    password = request.form.get("password")
    profile_img = request.files.get("profile_img")

    if not company_name or not first_name or not last_name or not email or not password:
        return jsonify({"error":"Missing data"}),400

    filename = save_profile_img(profile_img)
    hashed_pw = bcrypt.hashpw(password.encode(), bcrypt.gensalt())

    con, cur = get_db()
    try:
        cur.execute("INSERT INTO companies (name) VALUES (?)",(company_name,))
        company_id = cur.lastrowid

        cur.execute("""
            INSERT INTO users (first_name,last_name,email,password,role,company_id,profile_img)
            VALUES (?,?,?,?,?,?,?)
        """,(first_name,last_name,email,hashed_pw,"RH",company_id,filename))
        con.commit()
        return jsonify({"msg":"Company & RH created"}),201
    except sqlite3.IntegrityError as e:
        return jsonify({"error":str(e)}),400
    finally:
        con.close()

# =========================
# LOGIN
# =========================
@app.route("/login",methods=["POST"])
def login():
    email = request.form.get("email")
    password = request.form.get("password")
    if not email or not password:
        return jsonify({"error":"Missing email or password"}),400

    con, cur = get_db()
    cur.execute("SELECT * FROM users WHERE email=?",(email,))
    user = cur.fetchone()
    con.close()

    if not user:
        return jsonify({"error":"User not found"}),404
    if not bcrypt.checkpw(password.encode(),user["password"]):
        return jsonify({"error":"Invalid password"}),401

    token = jwt.encode({
        "id":user["id"],
        "role":user["role"],
        "company_id":user["company_id"],
        "exp":datetime.utcnow()+timedelta(hours=24)
    }, SECRET, algorithm="HS256")

    return jsonify({"token":token}),200

# =========================
# RH → ADD CHEF
# =========================
@app.route("/chef", methods=["POST"])
@verify_token
def add_chef(user):
    if user["role"]!="RH":
        return jsonify({"error":"Permission denied"}),403

    first_name = request.form.get("first_name")
    last_name = request.form.get("last_name")
    email = request.form.get("email")
    password = request.form.get("password")
    dispo = request.form.get("disponibilite_hebdo",100)
    profile_img = request.files.get("profile_img")

    if not first_name or not last_name or not email or not password:
        return jsonify({"error":"Missing data"}),400

    filename = save_profile_img(profile_img)
    hashed_pw = bcrypt.hashpw(password.encode(), bcrypt.gensalt())

    con, cur = get_db()
    try:
        cur.execute("""
            INSERT INTO users (first_name,last_name,email,password,role,company_id,profile_img)
            VALUES (?,?,?,?,?,?,?)
        """,(first_name,last_name,email,hashed_pw,"CHEF",user["company_id"],filename))
        chef_id = cur.lastrowid

        cur.execute("""
            INSERT INTO chef_profiles (chef_id,charge_affectee,score,disponibilite_hebdo)
            VALUES (?,?,?,?)
        """,(chef_id,0,50,int(dispo)))
        con.commit()
        return jsonify({"msg":"Chef created"}),201
    finally:
        con.close()

# =========================
# CHEF → ADD RESSOURCE (avec competence_moyenne)
# =========================


@app.route("/ressource", methods=["POST"])
@verify_token
def add_ressource(user):

    first_name = request.form.get("first_name")
    last_name = request.form.get("last_name")
    email = request.form.get("email")
    password = request.form.get("password")

    experience = int(request.form.get("experience",0))
    cost_hour = float(request.form.get("cost_hour",0))
    dispo = int(request.form.get("disponibilite_hebdo",40))
    charge_affectee = int(request.form.get("charge_affectee",0))
    competence_moyenne = float(request.form.get("competence_moyenne",50))

    profile_img = request.files.get("profile_img")

    if not first_name or not last_name or not email or not password:
        return jsonify({"error":"Missing data"}),400

    # ================================
    # تحديد chef_id حسب الدور
    # ================================
    if user["role"] == "RH":
        chef_id = request.form.get("chef_id")
        if not chef_id:
            return jsonify({"error":"chef_id required"}),400

        # التأكد أن chef ينتمي لنفس الشركة
        con, cur = get_db()
        cur.execute("""
            SELECT * FROM users
            WHERE id=? AND role='CHEF' AND company_id=?
        """,(chef_id,user["company_id"]))
        chef = cur.fetchone()
        con.close()

        if not chef:
            return jsonify({"error":"Chef not found"}),404

    elif user["role"] == "CHEF":
        chef_id = user["id"]

    else:
        return jsonify({"error":"Permission denied"}),403

    # ================================
    # حساب score
    # ================================
    new_score = score.ressource_score(
        experience,
        cost_hour,
        dispo,
        charge_affectee,
        competence_moyenne
    )

    filename = save_profile_img(profile_img)
    hashed_pw = bcrypt.hashpw(password.encode(), bcrypt.gensalt())

    con, cur = get_db()
    try:
        # إنشاء user
        cur.execute("""
            INSERT INTO users
            (first_name,last_name,email,password,role,company_id,profile_img)
            VALUES (?,?,?,?,?,?,?)
        """,(
            first_name,
            last_name,
            email,
            hashed_pw,
            "RESSOURCE",
            user["company_id"],
            filename
        ))

        res_id = cur.lastrowid

        # إنشاء profile
        cur.execute("""
            INSERT INTO ressource_profiles (
                ressource_id,
                chef_id,
                niveau_experience,
                disponibilite_hebdo,
                cout_horaire,
                charge_affectee,
                competence_moyenne,
                score
            )
            VALUES (?,?,?,?,?,?,?,?)
        """,(
            res_id,
            chef_id,
            experience,
            dispo,
            cost_hour,
            charge_affectee,
            competence_moyenne,
           round(new_score)
        ))
   
        con.commit()

        return jsonify({
            "msg":"Ressource created",
            "chef_id": chef_id
        }),201

    finally:
        con.close()

# =========================
# UPDATE CHEF / RESSOURCE (by RH or CHEF)
# =========================
@app.route("/user/update/<int:user_id>", methods=["PUT"])
@verify_token
def update_user(user, user_id):
    con, cur = get_db()
    try:
        # جلب بيانات المستخدم الهدف
        cur.execute("SELECT * FROM users WHERE id=?", (user_id,))
        target_user = cur.fetchone()
        if not target_user:
            return jsonify({"error":"User not found"}),404

        # ===== صلاحيات RH =====
        if user["role"]=="RH":
            # يمكنه تعديل نفسه أو أي مستخدم آخر
            if target_user["role"]=="RH" and user["id"] != user_id:
                pass  # يمكن تعديل أي RH آخر
        if user["role"]=="CHEF":
            if target_user["role"]!="RESSOURCE":
                return jsonify({"error":"Permission denied"}),403
            # فقط يمكنه تعديل الموارد التابعة له
            cur.execute("SELECT * FROM ressource_profiles WHERE ressource_id=? AND chef_id=?",
                        (user_id,user["id"]))
            profile = cur.fetchone()
            if not profile:
                return jsonify({"error":"Permission denied"}),403
        # ===== قراءة البيانات الجديدة =====
        first_name = request.form.get("first_name", target_user["first_name"])
        last_name = request.form.get("last_name", target_user["last_name"])
        email = request.form.get("email", target_user["email"])
        password = request.form.get("password", None)
        profile_img = request.files.get("profile_img", None)
        filename = save_profile_img(profile_img) if profile_img else target_user["profile_img"]

        if password:
            hashed_pw = bcrypt.hashpw(password.encode(), bcrypt.gensalt())
        else:
            hashed_pw = target_user["password"]

        # ===== تحديث جدول users =====
        cur.execute("""
            UPDATE users SET first_name=?, last_name=?, email=?, password=?, profile_img=?
            WHERE id=?""",(first_name,last_name,email,hashed_pw,filename,user_id))
        # ===== تحديث اسم الشركة إذا كان RH يعدّل نفسه =====
        if target_user["role"]=="RH" and user["id"] == user_id:
            company_name = request.form.get("company_name")
            if company_name:
                cur.execute("""
                    UPDATE companies SET name=?
                    WHERE id=?
                """,(company_name,target_user["company_id"]))
        # ===== تحديث ressource_profiles إذا كان RESSOURCE =====
        if target_user["role"]=="RESSOURCE":
            experience = int(request.form.get("experience", 0))
            cost_hour = float(request.form.get("cost_hour", 0))
            dispo = int(request.form.get("disponibilite_hebdo", 40))
            charge_affectee = int(request.form.get("charge_affectee", 0))
            competence_moyenne = float(request.form.get("competence_moyenne", 50))

            new_score = score.ressource_score(experience, cost_hour, dispo, charge_affectee, competence_moyenne)
            cur.execute("""
                UPDATE ressource_profiles
                SET niveau_experience=?, disponibilite_hebdo=?, cout_horaire=?,
                    charge_affectee=?, competence_moyenne=?, score=?
                WHERE ressource_id=?
            """, (
                experience, dispo, cost_hour, charge_affectee, competence_moyenne, new_score, user_id
            ))
        # ===== تحديث chef_profiles إذا كان CHEF =====
        elif target_user["role"]=="CHEF":
            dispo = int(request.form.get("disponibilite_hebdo", 40))
            cur.execute("""
                UPDATE chef_profiles SET disponibilite_hebdo=?
                WHERE chef_id=?
            """, (dispo, user_id))
        con.commit()
        return jsonify({"msg":"User updated"}),200
    finally:
        con.close()

# =========================
# DELETE CHEF / RESSOURCE (by RH or CHEF)
# =========================

@app.route("/user/delete/<int:user_id>", methods=["DELETE"])
@verify_token
def delete_user(user,user_id):
    con, cur = get_db()
    try:
        cur.execute("SELECT * FROM users WHERE id=?", (user_id,))
        target_user = cur.fetchone()
        if not target_user:
            return jsonify({"error":"User not found"}),404

        # RH ne peut pas supprimer lui-même
        if user["role"]=="RH" and target_user["role"]=="RH" and user["id"]==user_id:
            return jsonify({"error":"Vous ne pouvez pas supprimer votre propre compte RH"}),403

        # RH peut supprimer tout autre chef ou ressource
        if user["role"]=="RH":
            pass  # tout est autorisé sauf lui-même

        # CHEF peut supprimer uniquement ses ressources
        elif user["role"]=="CHEF":
            if target_user["role"]!="RESSOURCE":
                return jsonify({"error":"Permission denied"}),403
            cur.execute("SELECT * FROM ressource_profiles WHERE ressource_id=? AND chef_id=?",(user_id,user["id"]))
            profile = cur.fetchone()
            if not profile:
                return jsonify({"error":"Permission denied"}),403
        else:
            return jsonify({"error":"Permission denied"}),403

        # Suppression des profils liés
        if target_user["role"]=="CHEF":
            cur.execute("DELETE FROM chef_profiles WHERE chef_id=?",(user_id,))
        elif target_user["role"]=="RESSOURCE":
            cur.execute("DELETE FROM ressource_profiles WHERE ressource_id=?",(user_id,))

        # Suppression du user
        cur.execute("DELETE FROM users WHERE id=?",(user_id,))
        con.commit()
        return jsonify({"msg":"User deleted"}),200
    finally:
        con.close()







@app.route("/dashboard/resources", methods=["GET"])
@verify_token
def dashboard_resources(user):
    con, cur = get_db()
    try:
        # ======================================================
        # RH → chefs + ressources 
        # ======================================================
        if user["role"] == "RH":
            cur.execute("""
                SELECT
                    -- CHEF
                    c.id                AS chef_id,
                    c.first_name        AS chef_first_name,
                    c.last_name         AS chef_last_name,
                    c.email             AS chef_email,
                    c.profile_img       AS chef_profile_img,
                    cp.charge_affectee  AS chef_charge,
                    cp.disponibilite_hebdo AS chef_disponibilite,
                    cp.score            AS chef_score,

                    -- RESSOURCE
                    u.id                AS ressource_id,
                    u.first_name        AS ressource_first_name,
                    u.last_name         AS ressource_last_name,
                    u.email             AS ressource_email,
                    u.profile_img       AS ressource_profile_img,

                    rp.niveau_experience,
                    rp.disponibilite_hebdo,
                    rp.cout_horaire,
                    rp.charge_affectee,
                    rp.competence_moyenne,
                    rp.score            AS ressource_score

                FROM users c
                LEFT JOIN chef_profiles cp ON cp.chef_id = c.id
                LEFT JOIN ressource_profiles rp ON rp.chef_id = c.id
                LEFT JOIN users u ON u.id = rp.ressource_id
                WHERE c.role = 'CHEF'
                  AND c.company_id = ?
                ORDER BY c.id
            """, (user["company_id"],))

            rows = cur.fetchall()
            chefs = {}

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

        # ======================================================
        # CHEF → ses ressources فقط (كل التفاصيل)
        # ======================================================
        elif user["role"] == "CHEF":
            cur.execute("""
                SELECT
                    u.id, u.first_name, u.last_name, u.email, u.profile_img,
                    rp.niveau_experience,
                    rp.disponibilite_hebdo,
                    rp.cout_horaire,
                    rp.charge_affectee,
                    rp.competence_moyenne,
                    rp.score
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
# CREATE PROJECT (by RH)
# =========================

@app.route("/project/create", methods=["POST"])
@verify_token
def create_project(user):
    if user["role"] != "RH":
        return jsonify({"error": "Permission denied"}), 403

    name = request.form.get("name")
    description = request.form.get("description")
    difficulty = request.form.get("difficulty")  # easy | medium | hard
    chef_id = int(request.form.get("chef_id"))
    start_date = request.form.get("start_date")
    end_date = request.form.get("end_date")

    if not all([name, difficulty, chef_id, start_date, end_date]):
        return jsonify({"error": "Missing data"}), 400

    difficulty_map = {
        "easy": 15,
        "medium": 40,
        "hard": 60
    }

    if difficulty not in difficulty_map:
        return jsonify({"error": "Invalid difficulty"}), 400

    charge_to_add = difficulty_map[difficulty]

    con, cur = get_db()
    try:
        # التأكد أن chef ينتمي لنفس الشركة
        cur.execute("SELECT * FROM users WHERE id=? AND role='CHEF' AND company_id=?",
                    (chef_id, user["company_id"]))
        chef = cur.fetchone()
        if not chef:
            return jsonify({"error": "Chef not found"}), 404

        # جلب charge الحالي
        cur.execute("SELECT charge_affectee FROM chef_profiles WHERE chef_id=?",
                    (chef_id,))
        chef_profile = cur.fetchone()

        current_charge = chef_profile["charge_affectee"]

        if current_charge + charge_to_add > 100:
            return jsonify({"error": "Chef is overloaded"}), 400

        # حساب المدة
        from datetime import datetime
        d1 = datetime.strptime(start_date, "%Y-%m-%d")
        d2 = datetime.strptime(end_date, "%Y-%m-%d")
        duration = (d2 - d1).days

        # إدخال المشروع
        cur.execute("""
            INSERT INTO projects
            (name, description, difficulty, chef_id, company_id,
             start_date, end_date, duration_days, status,days_remaining)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?,?)
        """, (
            name,
            description,
            difficulty,
            chef_id,
            user["company_id"],
            start_date,
            end_date,
            duration,
            "planned",
            duration,
        ))

        # تحديث charge chef
        new_charge = current_charge + charge_to_add

        cur.execute("""
            UPDATE chef_profiles
            SET charge_affectee=?
            WHERE chef_id=?
        """, (new_charge, chef_id))

        con.commit()

        return jsonify({
            "msg": "Project created",
            "new_chef_charge": new_charge
        }), 201

    finally:
        con.close()



# =========================
# SERVE IMAGES
# =========================
@app.route("/images/<filename>")
def get_image(filename):
    return send_from_directory(UPLOAD_FOLDER,filename)
# =========================
# RUN APP
# =========================
if __name__=="__main__":
    app.run(debug=True)
