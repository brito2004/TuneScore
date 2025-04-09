from flask import Flask, render_template, request, redirect, url_for, flash, session
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3
import requests
import logging
from datetime import datetime
import os

app = Flask(__name__)
app.secret_key = 'your-secret-key'  # Substitua por uma chave secreta segura
app.config['UPLOAD_FOLDER'] = 'static/uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # Limite de 16MB para upload

# Configuração de logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuração do Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# Classe de usuário para Flask-Login
class User(UserMixin):
    def __init__(self, id, username, email, profile_picture):
        self.id = id
        self.username = username
        self.email = email
        self.profile_picture = profile_picture

# Função para carregar usuário
@login_manager.user_loader
def load_user(user_id):
    conn = sqlite3.connect('tunescore.db')
    cursor = conn.cursor()
    cursor.execute('SELECT id, username, email, profile_picture FROM users WHERE id = ?', (user_id,))
    user = cursor.fetchone()
    conn.close()
    if user:
        return User(user[0], user[1], user[2], user[3])
    return None

# Função para conectar ao banco de dados
def get_db_connection():
    conn = sqlite3.connect('tunescore.db')
    conn.row_factory = sqlite3.Row
    return conn

# Função para inicializar o banco de dados
def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()

    # Criar tabela users
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            password TEXT NOT NULL,
            profile_picture TEXT DEFAULT 'default.jpg'
        )
    ''')

    # Criar tabela tracks
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS tracks (
            deezer_id INTEGER PRIMARY KEY,
            title TEXT NOT NULL,
            artist_name TEXT NOT NULL,
            album_name TEXT NOT NULL,
            cover_url TEXT,
            genre_id INTEGER
        )
    ''')

    # Criar tabela ratings
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS ratings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            deezer_id INTEGER NOT NULL,
            rating INTEGER NOT NULL,
            comment TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users (id),
            FOREIGN KEY (deezer_id) REFERENCES tracks (deezer_id)
        )
    ''')

    conn.commit()
    conn.close()
    logger.info("Database initialized successfully.")

# Rota para a página inicial
@app.route('/')
def index():
    try:
        # Buscar músicas populares usando o endpoint /chart do Deezer
        res = requests.get('https://api.deezer.com/chart')
        if res.status_code == 200:
            data = res.json()
            tracks = data.get('tracks', {}).get('data', [])
            # Extrair informações relevantes para o slideshow
            slideshow_items = [
                {
                    'title': track['title'],
                    'artist': track['artist']['name'],
                    'cover': track['album']['cover_medium']
                }
                for track in tracks[:10]
            ]
            return render_template('index.html', slideshow_items=slideshow_items)
        else:
            logger.error(f"Failed to fetch Deezer chart: {res.status_code}")
            return render_template('index.html', slideshow_items=[])
    except Exception as e:
        logger.error(f"Error in index: {str(e)}")
        return render_template('index.html', slideshow_items=[])

# Rota para o ranking pessoal
@app.route('/ranking', methods=['GET'])
@login_required
def ranking():
    try:
        # Buscar gêneros disponíveis da API do Deezer
        genres_response = requests.get('https://api.deezer.com/genre')
        genres = []
        if genres_response.status_code == 200:
            genres_data = genres_response.json().get('data', [])
            genres = [(genre['id'], genre['name']) for genre in genres_data]

        # Obter o gênero selecionado (se houver)
        selected_genre = request.args.get('genre', type=int)

        # Conectar ao banco de dados
        conn = get_db_connection()
        cursor = conn.cursor()

        # Buscar as avaliações do usuário logado
        if selected_genre:
            # Filtrar por gênero
            cursor.execute('''
                SELECT r.id, r.user_id, r.deezer_id, r.rating, r.comment, r.created_at,
                       t.title, t.artist_name, t.album_name, t.cover_url, t.genre_id
                FROM ratings r
                JOIN tracks t ON r.deezer_id = t.deezer_id
                WHERE r.user_id = ? AND t.genre_id = ?
                ORDER BY r.rating DESC, r.created_at DESC
            ''', (current_user.id, selected_genre))
        else:
            # Sem filtro de gênero
            cursor.execute('''
                SELECT r.id, r.user_id, r.deezer_id, r.rating, r.comment, r.created_at,
                       t.title, t.artist_name, t.album_name, t.cover_url, t.genre_id
                FROM ratings r
                JOIN tracks t ON r.deezer_id = t.deezer_id
                WHERE r.user_id = ?
                ORDER BY r.rating DESC, r.created_at DESC
            ''', (current_user.id,))

        ratings = cursor.fetchall()
        conn.close()

        return render_template('ranking.html', ratings=ratings, genres=genres, selected_genre=selected_genre)
    except Exception as e:
        logger.error(f"Error in ranking: {str(e)}")
        flash('Ocorreu um erro ao carregar o ranking.', 'error')
        return render_template('ranking.html', ratings=[], genres=[], selected_genre=None)

# Rota para buscar músicas
@app.route('/search', methods=['GET', 'POST'])
@login_required
def search():
    if request.method == 'POST':
        query = request.form.get('query')
        if not query:
            flash('Por favor, insira um termo de busca.', 'error')
            return redirect(url_for('search'))

        try:
            # Buscar músicas na API do Deezer
            res = requests.get(f'https://api.deezer.com/search?q={query}')
            if res.status_code == 200:
                data = res.json()
                tracks = data.get('data', [])
                # Conectar ao banco de dados para verificar avaliações
                conn = get_db_connection()
                cursor = conn.cursor()
                for track in tracks:
                    cursor.execute('SELECT rating, comment FROM ratings WHERE user_id = ? AND deezer_id = ?',
                                   (current_user.id, track['id']))
                    rating = cursor.fetchone()
                    track['user_rating'] = rating['rating'] if rating else None
                    track['user_comment'] = rating['comment'] if rating else None
                conn.close()
                return render_template('search.html', tracks=tracks, query=query)
            else:
                flash('Erro ao buscar músicas. Tente novamente.', 'error')
                return redirect(url_for('search'))
        except Exception as e:
            logger.error(f"Error in search: {str(e)}")
            flash('Ocorreu um erro ao buscar músicas.', 'error')
            return redirect(url_for('search'))
    return render_template('search.html', tracks=None, query=None)

# Rota para avaliar uma música
@app.route('/rate/<int:deezer_id>', methods=['POST'])
@login_required
def rate(deezer_id):
    rating = request.form.get('rating', type=int)
    comment = request.form.get('comment')
    if not rating or rating < 1 or rating > 10:
        flash('A nota deve estar entre 1 e 10.', 'error')
        return redirect(url_for('search'))

    try:
        # Buscar informações da música na API do Deezer
        res = requests.get(f'https://api.deezer.com/track/{deezer_id}')
        if res.status_code != 200:
            flash('Música não encontrada.', 'error')
            return redirect(url_for('search'))

        track = res.json()
        title = track.get('title')
        artist_name = track.get('artist', {}).get('name')
        album_name = track.get('album', {}).get('title')
        cover_url = track.get('album', {}).get('cover_medium')
        # Obter o gênero do álbum ou artista
        genre_id = track.get('album', {}).get('genre_id') or track.get('artist', {}).get('genre_id')

        # Conectar ao banco de dados
        conn = get_db_connection()
        cursor = conn.cursor()

        # Verificar se a música já está no banco de dados
        cursor.execute('SELECT * FROM tracks WHERE deezer_id = ?', (deezer_id,))
        if not cursor.fetchone():
            cursor.execute('''
                INSERT INTO tracks (deezer_id, title, artist_name, album_name, cover_url, genre_id)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (deezer_id, title, artist_name, album_name, cover_url, genre_id))

        # Verificar se o usuário já avaliou a música
        cursor.execute('SELECT * FROM ratings WHERE user_id = ? AND deezer_id = ?', (current_user.id, deezer_id))
        if cursor.fetchone():
            # Atualizar avaliação existente
            cursor.execute('''
                UPDATE ratings
                SET rating = ?, comment = ?, created_at = ?
                WHERE user_id = ? AND deezer_id = ?
            ''', (rating, comment, datetime.utcnow(), current_user.id, deezer_id))
        else:
            # Inserir nova avaliação
            cursor.execute('''
                INSERT INTO ratings (user_id, deezer_id, rating, comment, created_at)
                VALUES (?, ?, ?, ?, ?)
            ''', (current_user.id, deezer_id, rating, comment, datetime.utcnow()))

        conn.commit()
        conn.close()
        flash('Avaliação salva com sucesso!', 'success')
        return redirect(url_for('search'))
    except Exception as e:
        logger.error(f"Error in rate: {str(e)}")
        flash('Ocorreu um erro ao salvar a avaliação.', 'error')
        return redirect(url_for('search'))

# Rota para o perfil do usuário
@app.route('/profile')
@login_required
def profile():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT r.id, r.deezer_id, r.rating, r.comment, r.created_at,
               t.title, t.artist_name, t.album_name, t.cover_url
        FROM ratings r
        JOIN tracks t ON r.deezer_id = t.deezer_id
        WHERE r.user_id = ?
        ORDER BY r.created_at DESC
    ''', (current_user.id,))
    ratings = cursor.fetchall()
    conn.close()
    return render_template('profile.html', user=current_user, ratings=ratings)

# Rota para login
@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM users WHERE email = ?', (email,))
        user = cursor.fetchone()
        conn.close()
        if user and check_password_hash(user['password'], password):
            user_obj = User(user['id'], user['username'], user['email'], user['profile_picture'])
            login_user(user_obj)
            flash('Login realizado com sucesso!', 'success')
            return redirect(url_for('index'))
        else:
            flash('Email ou senha inválidos.', 'error')
    return render_template('login.html')

# Rota para registro
@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        if not username or not email or not password:
            flash('Todos os campos são obrigatórios.', 'error')
            return redirect(url_for('register'))
        hashed_password = generate_password_hash(password)
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM users WHERE email = ?', (email,))
            if cursor.fetchone():
                flash('Email já registrado.', 'error')
                conn.close()
                return redirect(url_for('register'))
            cursor.execute('''
                INSERT INTO users (username, email, password, profile_picture)
                VALUES (?, ?, ?, ?)
            ''', (username, email, hashed_password, 'default.jpg'))
            conn.commit()
            cursor.execute('SELECT * FROM users WHERE email = ?', (email,))
            user = cursor.fetchone()
            user_obj = User(user['id'], user['username'], user['email'], user['profile_picture'])
            login_user(user_obj)
            conn.close()
            flash('Registro realizado com sucesso!', 'success')
            return redirect(url_for('index'))
        except Exception as e:
            logger.error(f"Error in register: {str(e)}")
            flash('Ocorreu um erro ao registrar.', 'error')
            return redirect(url_for('register'))
    return render_template('register.html')

# Rota para logout
@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Você saiu da sua conta.', 'success')
    return redirect(url_for('index'))

# Rota para atualizar a foto de perfil
@app.route('/update_profile_picture', methods=['POST'])
@login_required
def update_profile_picture():
    if 'profile_picture' not in request.files:
        flash('Nenhuma imagem enviada.', 'error')
        return redirect(url_for('profile'))
    file = request.files['profile_picture']
    if file.filename == '':
        flash('Nenhuma imagem selecionada.', 'error')
        return redirect(url_for('profile'))
    if file:
        filename = f"{current_user.id}_{file.filename}"
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('UPDATE users SET profile_picture = ? WHERE id = ?', (filename, current_user.id))
        conn.commit()
        conn.close()
        flash('Foto de perfil atualizada com sucesso!', 'success')
        return redirect(url_for('profile'))
    flash('Ocorreu um erro ao atualizar a foto de perfil.', 'error')
    return redirect(url_for('profile'))

if __name__ == '__main__':
    # Inicializar o banco de dados antes de iniciar o servidor
    init_db()
    # Criar o diretório de uploads se não existir
    if not os.path.exists(app.config['UPLOAD_FOLDER']):
        os.makedirs(app.config['UPLOAD_FOLDER'])
    app.run(debug=True)