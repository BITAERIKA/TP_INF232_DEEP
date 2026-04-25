from flask import Flask, render_template, request, redirect, url_for, flash, session, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import seaborn as sns
from io import BytesIO
import base64
import folium
from datetime import datetime
import os
from functools import wraps

app = Flask(__name__)
app.secret_key = os.urandom(24)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///signalements.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = 'static/uploads'
app.config['MAX_CONTENT_LENGTH'] = 2 * 1024 * 1024  # 2 Mo
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
db = SQLAlchemy(app)

# Créer le dossier d'upload si inexistant
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# --------- Modèles ---------
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nom_complet = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)

class Signalement(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    quartier = db.Column(db.String(100), nullable=False)
    type_insalubrite = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=True)
    image_filename = db.Column(db.String(200), nullable=True)
    date_signalement = db.Column(db.Date, nullable=False, default=datetime.utcnow)
    user = db.relationship('User', backref=db.backref('signalements', lazy=True))

# --------- Coordonnées ---------
QUARTIERS = {
    "Bastos":       (3.8796, 11.5125),
    "Mendong":      (3.8373, 11.4803),
    "Mvog Mbi":     (3.8410, 11.5190),
    "Nlongkak":     (3.8780, 11.5170),
    "Etoudi":       (3.8890, 11.5080),
    "Mvolyé":       (3.8250, 11.5000),
    "Melen":        (3.8510, 11.4980),
    "Tsinga":       (3.8670, 11.5100),
    "Ekounou":      (3.8310, 11.5380),
    "Ngousso":      (3.8950, 11.5400),
    "Olembe":       (3.9200, 11.5100),
    "Mimboman":     (3.8450, 11.5500),
    "Nkolbisson":   (3.8700, 11.4500),
    "Simbock":      (3.8200, 11.5300),
    "Cité Verte":   (3.8750, 11.5350),
    "Biyem-Assi":   (3.8430, 11.4860),
    "Nsam":         (3.8280, 11.5290),
    "Essos":        (3.8800, 11.5330),
    "Mvog Ada":     (3.8630, 11.5200)
}
TYPES = ["Dépôt d'ordures sauvage", "Canalisation bouchée", "Eaux stagnantes", "Déchets toxiques", "Autre"]

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# Décorateur pour routes protégées
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash("Veuillez vous connecter pour accéder à cette page.", "warning")
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# Création des tables
with app.app_context():
    db.create_all()

# --------- Routes authentification ---------
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        nom = request.form['nom_complet'].strip()
        email = request.form['email'].strip().lower()
        password = request.form['password']
        confirm = request.form['confirm_password']

        if not nom or not email or not password:
            flash("Tous les champs sont obligatoires.", "danger")
            return redirect(url_for('register'))
        if password != confirm:
            flash("Les mots de passe ne correspondent pas.", "danger")
            return redirect(url_for('register'))
        if User.query.filter_by(email=email).first():
            flash("Cet email est déjà utilisé.", "warning")
            return redirect(url_for('register'))

        hashed_pw = generate_password_hash(password)
        user = User(nom_complet=nom, email=email, password=hashed_pw)
        db.session.add(user)
        db.session.commit()
        flash("Compte créé avec succès. Vous pouvez vous connecter.", "success")
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email'].strip().lower()
        password = request.form['password']
        user = User.query.filter_by(email=email).first()
        if user and check_password_hash(user.password, password):
            session['user_id'] = user.id
            session['user_name'] = user.nom_complet
            flash(f"Bienvenue, {user.nom_complet} !", "success")
            return redirect(url_for('index'))
        else:
            flash("Email ou mot de passe incorrect.", "danger")
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash("Déconnexion réussie.", "info")
    return redirect(url_for('login'))

# --------- Route principale (protégée) ---------
@app.route('/')
@login_required
def index():
    signalements = Signalement.query.order_by(Signalement.id.desc()).limit(20).all()
    return render_template('index.html',
                           quartiers=sorted(QUARTIERS.keys()),
                           types=TYPES,
                           signalements=signalements,
                           today=datetime.today().strftime('%Y-%m-%d'))

# --------- Ajouter un signalement (protégé) ---------
@app.route('/ajouter', methods=['POST'])
@login_required
def ajouter():
    try:
        quartier = request.form['quartier'].strip()
        type_insal = request.form['type_insalubrite']
        description = request.form.get('description', '').strip()
        date_str = request.form['date_signalement']

        if quartier not in QUARTIERS:
            flash("Quartier non reconnu.", "danger")
            return redirect(url_for('index'))
        if type_insal not in TYPES:
            flash("Type d'insalubrité invalide.", "danger")
            return redirect(url_for('index'))
        date_obj = datetime.strptime(date_str, '%Y-%m-%d').date()
        if date_obj > datetime.today().date():
            flash("La date ne peut pas être dans le futur.", "danger")
            return redirect(url_for('index'))

        # Gestion de l'image
        file = request.files.get('image')
        filename = None
        if file and file.filename != '' and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            # Renommer pour éviter les conflits
            name, ext = os.path.splitext(filename)
            filename = f"{name}_{datetime.now().strftime('%Y%m%d%H%M%S')}{ext}"
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))

        signalement = Signalement(
            user_id=session['user_id'],
            quartier=quartier,
            type_insalubrite=type_insal,
            description=description,
            image_filename=filename,
            date_signalement=date_obj
        )
        db.session.add(signalement)
        db.session.commit()
        flash("Signalement enregistré avec succès !", "success")
    except Exception as e:
        flash(f"Erreur : {str(e)}", "danger")
    return redirect(url_for('index'))

# --------- Analyse (protégée) ---------
@app.route('/analyse')
@login_required
def analyse():
    signalements = Signalement.query.all()
    if not signalements:
        flash("Aucun signalement pour le moment.", "warning")
        return redirect(url_for('index'))

    data = [{
        'Quartier': s.quartier,
        'Type': s.type_insalubrite,
        'Date': s.date_signalement
    } for s in signalements]
    df = pd.DataFrame(data)

    nb_total = len(df)
    top_quartiers = df['Quartier'].value_counts().head(10).reset_index()
    top_quartiers.columns = ['Quartier', 'Nombre de signalements']

    # Graphique barres
    fig1, ax1 = plt.subplots(figsize=(10, 6))
    quartier_counts = df['Quartier'].value_counts()
    sns.barplot(x=quartier_counts.values, y=quartier_counts.index, ax=ax1, palette='Reds_r')
    ax1.set_title('Nombre de signalements par quartier')
    ax1.set_xlabel('Nombre')
    buf1 = BytesIO()
    plt.tight_layout()
    plt.savefig(buf1, format='png')
    plt.close()
    bar_img = base64.b64encode(buf1.getvalue()).decode('utf-8')

    # Camembert
    fig2, ax2 = plt.subplots()
    type_counts = df['Type'].value_counts()
    ax2.pie(type_counts, labels=type_counts.index, autopct='%1.1f%%', startangle=90)
    ax2.set_title('Répartition des types d\'insalubrité')
    buf2 = BytesIO()
    plt.tight_layout()
    plt.savefig(buf2, format='png')
    plt.close()
    pie_img = base64.b64encode(buf2.getvalue()).decode('utf-8')

    return render_template('analyse.html',
                           nb_total=nb_total,
                           top_quartiers=top_quartiers,
                           bar_img=bar_img,
                           pie_img=pie_img)

# --------- Carte ---------
@app.route('/carte')
@login_required
def carte():
    signalements = Signalement.query.all()
    if not signalements:
        return "<p>Aucune donnée.</p>"

    df = pd.DataFrame([(s.quartier,) for s in signalements], columns=['quartier'])
    counts = df['quartier'].value_counts().reset_index()
    counts.columns = ['quartier', 'nb_signalements']

    m = folium.Map(location=[3.848, 11.502], zoom_start=12)
    for _, row in counts.iterrows():
        nom = row['quartier']
        nb = row['nb_signalements']
        coord = QUARTIERS.get(nom)
        if coord:
            folium.Circle(
                location=coord,
                radius=nb * 200,
                color='red',
                fill=True,
                fill_opacity=0.6,
                popup=f"<b>{nom}</b><br>Signalements : {nb}"
            ).add_to(m)

    return m._repr_html_()

# --------- Fichiers uploadés (accès protégé) ---------
@app.route('/uploads/<filename>')
@login_required
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

if __name__ == '__main__':
    app.run(debug=True)