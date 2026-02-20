from flask import Flask, request, jsonify
import pandas as pd
import numpy as np
import joblib

app = Flask(__name__)

model = joblib.load("model_score.pkl")
kmeans = joblib.load("kmeans_cluster.pkl")
scaler = joblib.load("scaler_cluster.pkl")

features = [
    'niveau_experience',
    'disponibilite_hebdo',
    'cout_horaire',
    'charge_affectee',
    'competence_moyenne'
]

def ressource_score(niveau_experience, cout_horaire, disponibilite_hebdo,
                    charge_affectee, competence_moyenne):

    new_resource = pd.DataFrame([[
        niveau_experience,
        disponibilite_hebdo,
        cout_horaire,
        charge_affectee,
        competence_moyenne
    ]], columns=features)

    new_scaled = scaler.transform(new_resource)
    new_cluster = kmeans.predict(new_scaled)[0]

    new_resource["cluster"] = new_cluster
    pred_score = model.predict(new_resource)[0]

    return float(np.clip(pred_score, 0, 100))

if __name__ == "__main__":
    app.run(debug=True)
