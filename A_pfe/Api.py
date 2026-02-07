from flask import Flask, jsonify, request
import sqlite3
import numpy as np
import pandas as pd

from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.ensemble import RandomForestRegressor

# ======================================================
# INIT FLASK
# ======================================================
app = Flask(__name__)

# ======================================================
# LOAD DATA FROM DATABASE
# ======================================================
def load_data():
    conn = sqlite3.connect("DB_PFE_complete.db")
    df = pd.read_sql_query("""
    SELECT 
        r.id_resource,
        r.niveau_experience,
        r.disponibilite_hebdo,
        r.cout_horaire,
        a.charge_affectee,
        AVG(m.niveau_maitrise) AS competence_moyenne,
        a.score_affectation
    FROM AFFECTATION a
    JOIN RESOURCE r ON a.id_resource = r.id_resource
    JOIN MAITRISE m ON m.id_resource = r.id_resource
    GROUP BY a.id_affectation
    """, conn)
    conn.close()
    return df

df = load_data()

# ======================================================
# FEATURES
# ======================================================
features_cluster = [
    'niveau_experience',
    'disponibilite_hebdo',
    'cout_horaire',
    'charge_affectee',
    'competence_moyenne'
]

# ======================================================
# SCALING + CLUSTERING
# ======================================================
scaler_cluster = StandardScaler()
X_cluster = scaler_cluster.fit_transform(df[features_cluster])

kmeans = KMeans(n_clusters=4, random_state=42, n_init=10)
df['cluster'] = kmeans.fit_predict(X_cluster)

# ======================================================
# MACHINE LEARNING MODEL (PREDICTION)
# ======================================================
X = df[features_cluster + ['cluster']]
y = df['score_affectation']

X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.25, random_state=42
)

model = Pipeline([
    ('scaler', StandardScaler()),
    ('rf', RandomForestRegressor(n_estimators=300, random_state=42))
])

model.fit(X_train, y_train)

# ======================================================
# ROUTES
# ======================================================
@app.route("/")
def home():
    return jsonify({"message": "PFE Resource Allocation API running (No PCA)"})

# ------------------------------------------------------
# CLUSTERS PROFILES
# ------------------------------------------------------
@app.route("/clusters", methods=["GET"])
def clusters():
    profiles = df.groupby("cluster").mean(numeric_only=True)
    return jsonify(profiles.to_dict())

# ------------------------------------------------------
# RESOURCES PER CLUSTER
# ------------------------------------------------------
@app.route("/resources/<int:cluster_id>", methods=["GET"])
def resources_by_cluster(cluster_id):
    data = df[df["cluster"] == cluster_id]
    return jsonify(data.to_dict(orient="records"))

# ------------------------------------------------------
# PREDICT NEW RESOURCE SCORE
# ------------------------------------------------------
@app.route("/predict", methods=["POST"])
def predict():
    data = request.json

    new_resource = pd.DataFrame([{
        'niveau_experience': data['niveau_experience'],
        'disponibilite_hebdo': data['disponibilite_hebdo'],
        'cout_horaire': data['cout_horaire'],
        'charge_affectee': data['charge_affectee'],
        'competence_moyenne': data['competence_moyenne']
    }])

    new_scaled = scaler_cluster.transform(new_resource)
    new_cluster = kmeans.predict(new_scaled)[0]
    new_resource['cluster'] = new_cluster

    score = model.predict(new_resource)[0]
    score = float(np.clip(score, 0, 100))

    return jsonify({
        "cluster": int(new_cluster),
        "predicted_score": round(score, 2)
    })

# ======================================================
# RUN SERVER
# ======================================================
if __name__ == "__main__":
    app.run(debug=True)
 