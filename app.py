from flask import Flask, render_template, request, redirect, url_for
import requests
import sqlite3
from datetime import datetime

app = Flask(__name__)

def init_db():
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS songs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            deezer_id TEXT UNIQUE,
            title TEXT,
            artist TEXT,
            album TEXT,
            cover TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            song_id INTEGER,
            rating INTEGER,
            comment TEXT,
            created_at TEXT,
            is_flagged INTEGER DEFAULT 0,
            FOREIGN KEY(song_id) REFERENCES songs(id)
        )
    """)
    conn.commit()
    conn.close()

@app.route('/')
def index():
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    cursor.execute("""
        SELECT songs.*, AVG(reviews.rating) as avg_rating, COUNT(reviews.id) as count_reviews
        FROM songs
        LEFT JOIN reviews ON songs.id = reviews.song_id
        GROUP BY songs.id
        ORDER BY avg_rating DESC
        LIMIT 10
    """)
    songs = cursor.fetchall()
    conn.close()
    return render_template('index.html', songs=songs)

@app.route('/search', methods=['GET', 'POST'])
def search():
    if request.method == 'POST':
        q = request.form['query']
        res = requests.get(f'https://api.deezer.com/search?q={q}')
        results = res.json().get('data', [])
        return render_template('search.html', results=results)
    return render_template('search.html')

@app.route('/song/<deezer_id>', methods=['GET', 'POST'])
def song(deezer_id):
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM songs WHERE deezer_id=?', (deezer_id,))
    song = cursor.fetchone()

    if not song:
        res = requests.get(f'https://api.deezer.com/track/{deezer_id}')
        if res.status_code == 200:
            track = res.json()
            title = track['title']
            artist = track['artist']['name']
            album = track['album']['title']
            cover = track['album']['cover_medium']
            cursor.execute("""
                INSERT INTO songs (deezer_id, title, artist, album, cover)
                VALUES (?, ?, ?, ?, ?)
            """, (deezer_id, title, artist, album, cover))
            conn.commit()
            cursor.execute('SELECT * FROM songs WHERE deezer_id=?', (deezer_id,))
            song = cursor.fetchone()

    if request.method == 'POST':
        rating = int(request.form['rating'])
        comment = request.form['comment']
        cursor.execute("""
            INSERT INTO reviews (song_id, rating, comment, created_at)
            VALUES (?, ?, ?, ?)
        """, (song[0], rating, comment, datetime.now()))
        conn.commit()
        return redirect(url_for('song', deezer_id=deezer_id))

    cursor.execute('SELECT rating, comment, created_at, id FROM reviews WHERE song_id=? ORDER BY created_at DESC', (song[0],))
    reviews = cursor.fetchall()
    conn.close()
    return render_template('song.html', song=song, reviews=reviews)

@app.route('/profile')
def profile():
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    cursor.execute("""
        SELECT songs.title, songs.artist, reviews.rating, reviews.comment, reviews.created_at
        FROM reviews
        JOIN songs ON reviews.song_id = songs.id
        ORDER BY reviews.created_at DESC
    """)
    history = cursor.fetchall()
    conn.close()
    return render_template('profile.html', history=history)

@app.route('/report', methods=['POST'])
def report_review():
    review_id = request.form['review_id']
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    cursor.execute('UPDATE reviews SET is_flagged = 1 WHERE id = ?', (review_id,))
    conn.commit()
    conn.close()
    return redirect(request.referrer or url_for('index'))

if __name__ == '__main__':
    init_db()
    app.run(debug=True)
