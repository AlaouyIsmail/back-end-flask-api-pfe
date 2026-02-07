# ======================================================
# IMPORTS
# ======================================================
import sqlite3
import numpy as np
import pandas as pd

import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d import Axes3D

from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler
from sklearn.decomposition import PCA
from sklearn.metrics import silhouette_score

from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import r2_score, mean_absolute_error
import joblib


# ======================================================
# 1️⃣ LOAD DATA FROM DATABASE
# ======================================================
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

print("\n✅ DATA LOADED")
print(df.head())


# ======================================================
# 2️⃣ FEATURES FOR CLUSTERING
# ======================================================
features_cluster = [
    'niveau_experience',
    'disponibilite_hebdo',
    'cout_horaire',
    'charge_affectee',
    'competence_moyenne'
]

scaler_cluster = StandardScaler()
X_cluster = scaler_cluster.fit_transform(df[features_cluster])


# ======================================================
# 3️⃣ FIND BEST NUMBER OF CLUSTERS (SILHOUETTE)
# ======================================================
print("\n🔍 SILHOUETTE SCORES")

best_k = 0
best_score = -1

for k in range(2, 9):
    km = KMeans(n_clusters=k, random_state=42, n_init=10)
    labels = km.fit_predict(X_cluster)
    score = silhouette_score(X_cluster, labels)
    print(f"k = {k} ➜ Silhouette = {score:.3f}")

    if score > best_score:
        best_score = score
        best_k = k

print("\n✅ BEST NUMBER OF CLUSTERS =", best_k)


# ======================================================
# 4️⃣ K-MEANS WITH BEST k
# ======================================================
kmeans = KMeans(n_clusters=best_k, random_state=42, n_init=10)
df['cluster'] = kmeans.fit_predict(X_cluster)

print("\n📌 CLUSTER PROFILES")
print(df.groupby('cluster').mean(numeric_only=True))


# ======================================================
# 5️⃣ PCA / ACP 3D
# ======================================================
pca = PCA(n_components=3)
X_pca = pca.fit_transform(X_cluster)

df['PC1'] = X_pca[:, 0]
df['PC2'] = X_pca[:, 1]
df['PC3'] = X_pca[:, 2]

print("\n📊 VARIANCE EXPLIQUÉE PAR PCA")
print("PC1 :", round(pca.explained_variance_ratio_[0]*100,2), "%")
print("PC2 :", round(pca.explained_variance_ratio_[1]*100,2), "%")
print("PC3 :", round(pca.explained_variance_ratio_[2]*100,2), "%")
print("TOTAL :", round(sum(pca.explained_variance_ratio_)*100,2), "%")


# ======================================================
# 6️⃣ PCA 3D VISUALISATION
# ======================================================
fig = plt.figure(figsize=(10,8))
ax = fig.add_subplot(111, projection='3d')

scatter = ax.scatter(
    df['PC1'],
    df['PC2'],
    df['PC3'],
    c=df['cluster'],
    cmap='tab10',
    alpha=0.6
)

ax.set_title("ACP 3D - Visualisation des Clusters", fontsize=14)
ax.set_xlabel("PC1")
ax.set_ylabel("PC2")
ax.set_zlabel("PC3")

legend = ax.legend(*scatter.legend_elements(), title="Clusters")
ax.add_artist(legend)

plt.show()


# ======================================================
# 7️⃣ MACHINE LEARNING (PREDICTION SCORE)
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
y_pred = model.predict(X_test)

print("\n✅ MODEL TRAINED")
print("\n📊 ML EVALUATION")
print("R2 Score :", round(r2_score(y_test, y_pred),3))
print("MAE      :", round(mean_absolute_error(y_test, y_pred),2))


# ======================================================
# 8️⃣ NEW RESOURCE TEST
# ======================================================
new_resource = pd.DataFrame([{
    'niveau_experience': 3,
    'disponibilite_hebdo': 30,
    'cout_horaire': 80,
    'charge_affectee': 10,
    'competence_moyenne': 65
}])

new_scaled = scaler_cluster.transform(new_resource)
new_cluster = kmeans.predict(new_scaled)[0]
new_resource['cluster'] = new_cluster

pred_score = model.predict(new_resource)[0]
pred_score = np.clip(pred_score, 0, 100)

print("\n📌 NEW RESOURCE CLUSTER :", new_cluster)
print("🤖 PREDICTED SCORE     :", round(pred_score,2), "%")


# ======================================================
# 9️⃣ DISPLAY ALL RESOURCES PER CLUSTER
# ======================================================
print("\n📋 ALL RESOURCES PER CLUSTER")

for c in sorted(df['cluster'].unique()):
    cluster_df = df[df['cluster'] == c]
    print(f"\n================ CLUSTER {c} =================")
    print("Nombre de ressources :", len(cluster_df))
    print(cluster_df[['id_resource','score_affectation']].head(10))



# بعد تدريب الموديل كما في الكود ML ديالك
joblib.dump(model, "model_score.pkl")
joblib.dump(kmeans, "kmeans_cluster.pkl")
joblib.dump(scaler_cluster, "scaler_cluster.pkl")