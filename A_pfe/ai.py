
# import streamlit as st
# import sqlite3
# import numpy as np
# import pandas as pd
# import plotly.express as px
# import plotly.graph_objects as go
# from scipy.spatial import ConvexHull 

# from sklearn.cluster import KMeans
# from sklearn.metrics import silhouette_score
# from sklearn.preprocessing import StandardScaler
# from sklearn.decomposition import PCA
# from sklearn.model_selection import train_test_split
# from sklearn.pipeline import Pipeline
# from sklearn.ensemble import RandomForestRegressor
# from sklearn.metrics import r2_score, mean_absolute_error


# # Configuration de la page Streamlit
# st.set_page_config(layout="wide", page_title="Analyse des Clusters de Ressources")
# st.title("Analyse et Prédiction de l'Affectation des Ressources")
# # =========================================
# #  LOAD DATA & PROCESSING
# # =========================================

# @st.cache_data
# def load_and_process_data():
#     # Assurez-vous que DB_PFE_complete.db est accessible
#     try:
#         conn = sqlite3.connect("DB_PFE_complete.db")
#         df = pd.read_sql_query("""
#         SELECT 
#             r.id_resource,
#             r.niveau_experience,
#             r.disponibilite_hebdo,
#             r.cout_horaire,
#             a.charge_affectee,
#             AVG(m.niveau_maitrise) AS competence_moyenne,
#             a.score_affectation
#         FROM AFFECTATION a
#         JOIN RESOURCE r ON a.id_resource = r.id_resource
#         JOIN MAITRISE m ON m.id_resource = r.id_resource
#         GROUP BY a.id_affectation
#         """, conn)
#         conn.close()
#     except sqlite3.OperationalError:
#         st.error("Erreur de connexion à la base de données. Assurez-vous que 'DB_PFE_complete.db' existe.")
#         return None, None, None, None, None, None

#     if df.empty or len(df) < 10: # Vérification minimale pour le clustering
#         st.error("Données insuffisantes pour le clustering K-Means (moins de 10 enregistrements).")
#         return None, None, None, None, None, None

#     features_cluster = [
#         'niveau_experience', 'disponibilite_hebdo', 'cout_horaire', 
#         'charge_affectee', 'competence_moyenne'
#     ]
    
#     # Prétraitement et Clustering
#     scaler_cluster = StandardScaler()
#     X_cluster = scaler_cluster.fit_transform(df[features_cluster])

#     best_k = 0
#     best_score = -1
#     silhouette_scores = {}



#     for k in range(2, 9):
#         km = KMeans(n_clusters=k, random_state=42, n_init=10)
#         labels = km.fit_predict(X_cluster)
#         score = silhouette_score(X_cluster, labels)
#         silhouette_scores[k] = score
#         if score > best_score:
#             best_score = score
#             best_k = k

#     kmeans = KMeans(n_clusters=best_k, random_state=42, n_init=10)
#     df['cluster'] = kmeans.fit_predict(X_cluster)
    
#     return df, X_cluster, scaler_cluster, best_k, silhouette_scores, kmeans

# df, X_cluster, scaler_cluster, best_k, silhouette_scores, kmeans = load_and_process_data()





# if df is not None:
#     # =========================================
#     # ACP (PCA)
#     # =========================================
#     pca_3d = PCA(n_components=3)
#     components_3d = pca_3d.fit_transform(X_cluster)
#     df_pca = pd.DataFrame(components_3d, columns=['PC1', 'PC2', 'PC3'])
#     df_pca['Cluster'] = df['cluster'].astype(str)
#     col1, col2 = st.columns(2)

#     # --- Courbe 1 : Méthode du Silhouette ---
#     with col1:
#         st.subheader("1. Courbe de la Méthode du Silhouette")
#         scores_df = pd.DataFrame({
#             'Nombre de Clusters (k)': list(silhouette_scores.keys()),
#             'Score de Silhouette': list(silhouette_scores.values())
#         })
#         fig_silhouette = px.line(
#             scores_df, x='Nombre de Clusters (k)', y='Score de Silhouette',height=420, 
#           color_discrete_sequence=["#7810FF"], markers=True, title=f"Score de Silhouette pour différents k (Meilleur k={best_k})"
#         )

#         st.plotly_chart(fig_silhouette, use_container_width=True)





#     # --- Courbe 2 : PCA 2D avec Enveloppes Convexes (comme dans votre image) ---
#     with col2:
#         st.subheader("2. Visualisation 2D des Clusters (ACP) avec Enveloppes")
        
#         fig_2d = go.Figure()

#         # Couleurs pour les clusters
#         colors = px.colors.qualitative.Plotly[:best_k]

#         for i, c in enumerate(sorted(df_pca['Cluster'].unique())):
#             cluster_data = df_pca[df_pca['Cluster'] == c]
            
#             # Scatter plot pour les points (similaire à l'image)
#             fig_2d.add_trace(go.Scatter(
#                 x=cluster_data['PC1'], 
#                 y=cluster_data['PC2'], 
#                 mode='markers', 
#                 name=f'Cluster {c}',
#                 marker=dict(color=colors[i], size=8)
#             ))

#             # Création de l'enveloppe convexe (Convex Hull)
#             try:
#                 points = cluster_data[['PC1', 'PC2']].values
#                 hull = ConvexHull(points)
                
#                 # Ajouter la forme délimitant le cluster
#                 fig_2d.add_trace(go.Scatter(
#                     x=points[hull.vertices, 0], 
#                     y=points[hull.vertices, 1],
#                     fill='toself', # Remplir l'enveloppe
#                     fillcolor=colors[i].replace(')', ', 0.2)').replace('rgb', 'rgba'), # Couleur semi-transparente
#                     line=dict(color=colors[i], width=1), 
#                     mode='lines',
#                     showlegend=False,
#                     hoverinfo='skip'
#                 ))
#             except Exception as e:
#                 # Gérer le cas où le cluster est trop petit (moins de 3 points)
#                 st.warning(f"Impossible de calculer l'enveloppe convexe pour le Cluster {c}. Raison : {e}")
#                 pass

#         fig_2d.update_layout(
#             title='Clusters visualisés (PC1 vs PC2) avec Enveloppes Convexes',
#             xaxis_title=f"Dim1 ({pca_3d.explained_variance_ratio_[0]*100:.1f}%)",
#             yaxis_title=f"Dim2 ({pca_3d.explained_variance_ratio_[1]*100:.1f}%)",
#             legend_title="Cluster"
#         )
#         st.plotly_chart(fig_2d, use_container_width=True)


#     # --- Courbe 3 : PCA 3D (Séparation pour meilleure mise en page) ---
#     st.subheader("3. Courbe 3D des Clusters (ACP)")
#     fig_3d = px.scatter_3d(
#         df_pca, 
#         x='PC1', 
#         y='PC2', 
#         z='PC3',
#         color='Cluster',
#         title='Clusters visualisés dans l\'espace 3D des Composantes Principales',
#         color_discrete_sequence=px.colors.qualitative.Plotly 
#     )
#     fig_3d.update_layout(height=600)
#     st.plotly_chart(fig_3d, use_container_width=True)
    
    
#     # =========================================
#     #  MACHINE LEARNING
#     # =========================================
    
#     st.header("🤖 Prédiction du Score d'Affectation")
    
#     features_cluster = [
#         'niveau_experience', 'disponibilite_hebdo', 'cout_horaire', 
#         'charge_affectee', 'competence_moyenne'
#     ]
#     X = df[features_cluster + ['cluster']]
#     y = df['score_affectation']

#     X_train, X_test, y_train, y_test = train_test_split(
#         X, y, test_size=0.25, random_state=42
#     )

#     model = Pipeline([
#         ('scaler', StandardScaler()),
#         ('rf', RandomForestRegressor(random_state=42))
#     ])

#     model.fit(X_train, y_train)
#     y_pred = model.predict(X_test)
    
#     st.subheader("📊 Évaluation du Modèle de Régression")
#     col_ml_1, col_ml_2, col_ml_3 = st.columns(3)
    
#     col_ml_1.metric("R2 Score", f"{r2_score(y_test, y_pred):.3f}")
#     col_ml_2.metric("MAE (Erreur Absolue Moyenne)", f"{mean_absolute_error(y_test, y_pred):.2f}")
    
    
#     # =========================================
#     # 6 NEW RESOURCE TEST
#     # =========================================
    
#     st.subheader("💡 Tester une Nouvelle Ressource")
    
#     # Création d'un formulaire pour les entrées utilisateur
#     with st.form("new_resource_form"):
#         col_f1, col_f2, col_f3 = st.columns(3)
        
#         nv_exp = col_f1.slider("Niveau d'Expérience (1 à 10)", 1, 10, 5)
#         dispo = col_f2.slider("Disponibilité Hebdomadaire (h)", 10, 100, 40)
#         cout = col_f3.slider("Coût Horaire (dh)", 5, 100, 30)
        
#         col_f4, col_f5 = st.columns(2)
#         charge = col_f4.slider("Charge Affectée (unité)", 1, 50, 15)
#         comp_moy = col_f5.slider("Compétence Moyenne (sur 100)", 10, 100, 50)
        
#         submitted = st.form_submit_button("Calculer le Score d'Affectation")

#     if submitted:
#         new_resource = pd.DataFrame([{
#             'niveau_experience': nv_exp,
#             'disponibilite_hebdo': dispo,
#             'cout_horaire': cout,
#             'charge_affectee': charge,
#             'competence_moyenne': comp_moy
#         }])

#         # 1. Mise à l'échelle (Scaler du clustering)
#         new_scaled = scaler_cluster.transform(new_resource)
        
#         # 2. Prédiction du Cluster (KMeans)
#         new_cluster = kmeans.predict(new_scaled)[0]
#         new_resource['cluster'] = new_cluster

#         # 3. Prédiction du Score (Random Forest)
#         pred = model.predict(new_resource)[0]
#         pred = np.clip(pred, 0, 100) # Assurer que le score est entre 0 et 100

#         st.success(f"La ressource est classée dans le **Cluster {new_cluster}**.")
#         st.metric(
#             label="Score d'Affectation Prédit", 
#             value=f"{round(pred, 2)} %", 
#             delta="Score élevé = Affectation optimale" if pred > 70 else "Score faible = Amélioration requise"
#         )



import sqlite3
import numpy as np
import pandas as pd
from scipy.spatial import ConvexHull

from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score, r2_score, mean_absolute_error
from sklearn.preprocessing import StandardScaler
from sklearn.decomposition import PCA
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.ensemble import RandomForestRegressor

# =========================================
#  LOAD DATA & PROCESSING
# =========================================
def load_and_process_data(db_path="DB_PFE_complete.db"):
    try:
        conn = sqlite3.connect(db_path)
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
    except sqlite3.OperationalError:
        print("Erreur de connexion à la base de données. Vérifiez que DB_PFE_complete.db existe.")
        return None, None, None, None, None, None

    if df.empty or len(df) < 10:
        print("Données insuffisantes pour le clustering K-Means (moins de 10 enregistrements).")
        return None, None, None, None, None, None

    features_cluster = [
        'niveau_experience', 'disponibilite_hebdo', 'cout_horaire', 
        'charge_affectee', 'competence_moyenne'
    ]
    
    scaler_cluster = StandardScaler()
    X_cluster = scaler_cluster.fit_transform(df[features_cluster])

    best_k = 0
    best_score = -1
    silhouette_scores = {}

    for k in range(2, 9):
        km = KMeans(n_clusters=k, random_state=42, n_init=10)
        labels = km.fit_predict(X_cluster)
        score = silhouette_score(X_cluster, labels)
        silhouette_scores[k] = score
        if score > best_score:
            best_score = score
            best_k = k

    kmeans = KMeans(n_clusters=best_k, random_state=42, n_init=10)
    df['cluster'] = kmeans.fit_predict(X_cluster)

    return df, X_cluster, scaler_cluster, best_k, silhouette_scores, kmeans

df, X_cluster, scaler_cluster, best_k, silhouette_scores, kmeans = load_and_process_data()

if df is not None:
    print(f"\nMeilleur nombre de clusters k = {best_k}\n")

    print("=== Clusters des 20 premières ressources ===")
    # Sélection des 20 premières lignes
    df_top20 = df.head(20)

    # Affichage cluster et informations principales
    for idx, row in df_top20.iterrows():
        print(f"Ressource {row['id_resource']}: Cluster {row['cluster']}, "
              f"Niveau Exp={row['niveau_experience']}, "
              f"Disponibilité={row['disponibilite_hebdo']}h, "
              f"Coût={row['cout_horaire']} dh, "
              f"Charge={row['charge_affectee']}, "
              f"Compétence Moyenne={row['competence_moyenne']:.1f}")

    # =========================================
    # PCA pour visualisation (console)
    # =========================================
    pca_3d = PCA(n_components=3)
    components_3d = pca_3d.fit_transform(X_cluster)
    df_pca = pd.DataFrame(components_3d, columns=['PC1', 'PC2', 'PC3'])
    df_pca['Cluster'] = df['cluster']

    print("\nExtrait PCA 3D (premières lignes) :")
    print(df_pca.head())

    # =========================================
    # MACHINE LEARNING
    # =========================================
    print("\n--- Entraînement du modèle RandomForest ---")
    features_cluster = [
        'niveau_experience', 'disponibilite_hebdo', 'cout_horaire', 
        'charge_affectee', 'competence_moyenne'
    ]
    X = df[features_cluster + ['cluster']]
    y = df['score_affectation']

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.25, random_state=42
    )

    model = Pipeline([
        ('scaler', StandardScaler()),
        ('rf', RandomForestRegressor(random_state=42))
    ])

    model.fit(X_train, y_train)
    y_pred = model.predict(X_test)

    print(f"R2 Score : {r2_score(y_test, y_pred):.3f}")
    print(f"MAE (Erreur Absolue Moyenne) : {mean_absolute_error(y_test, y_pred):.2f}")

    # =========================================
    # TEST NOUVELLE RESSOURCE
    # =========================================
    print("\n--- Tester une nouvelle ressource ---")
    nv_exp = int(input("Niveau d'expérience (1-10) : "))
    dispo = int(input("Disponibilité hebdomadaire (h) : "))
    cout = float(input("Coût horaire (dh) : "))
    charge = float(input("Charge affectée (unité) : "))
    comp_moy = float(input("Compétence moyenne (0-100) : "))

    new_resource = pd.DataFrame([{
        'niveau_experience': nv_exp,
        'disponibilite_hebdo': dispo,
        'cout_horaire': cout,
        'charge_affectee': charge,
        'competence_moyenne': comp_moy
    }])

    # Mise à l'échelle
    new_scaled = scaler_cluster.transform(new_resource)

    # Prédiction du Cluster
    new_cluster = kmeans.predict(new_scaled)[0]
    new_resource['cluster'] = new_cluster

    # Prédiction du Score
    pred = model.predict(new_resource)[0]
    pred = np.clip(pred, 0, 100)

    print(f"\nLa ressource est classée dans le Cluster {new_cluster}.")
    print(f"Score d'Affectation Prévu : {round(pred, 2)} %")
    print("Score élevé = Affectation optimale" if pred > 70 else "Score faible = Amélioration requise")
