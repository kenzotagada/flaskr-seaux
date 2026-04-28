from flask import Flask, render_template, request, redirect, url_for, session, send_from_directory, send_file
import sqlite3
import os
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from datetime import datetime, timedelta
from flask import jsonify
import pytz

def get_online_status(last_seen):
    if not last_seen:
        return "Hors ligne"
    last_seen_dt = datetime.strptime(last_seen, '%Y-%m-%d %H:%M:%S')
    if datetime.utcnow() - last_seen_dt <= timedelta(minutes=5):
        return "En ligne"
    return "Hors ligne"

app = Flask(__name__)
app.secret_key = 'une_clef_secrete_complexe_et_unique'
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SECURE=False,
    SESSION_COOKIE_SAMESITE='Lax'
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, 'database.db')
AUDIO_DIR = "static/messages_audio"
os.makedirs(AUDIO_DIR, exist_ok=True)
AVATAR_DIR = os.path.join(BASE_DIR, 'static', 'avatars')
os.makedirs(AVATAR_DIR, exist_ok=True)
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
IMAGE_DIR = os.path.join(BASE_DIR, 'static', 'images')
os.makedirs(IMAGE_DIR, exist_ok=True)
UPLOAD_FOLDER = 'static/post_images'

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

def to_paris_time(utc_string):
    if not utc_string:
        return ""

    utc = pytz.utc
    paris = pytz.timezone('Europe/Paris')

    dt = datetime.strptime(utc_string, '%Y-%m-%d %H:%M:%S')
    dt = utc.localize(dt)

    paris_dt = dt.astimezone(paris)

    return paris_dt.strftime('%Y-%m-%d %H:%M:%S')

app.jinja_env.filters['paris_time'] = to_paris_time

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            avatar_url TEXT,
            bio TEXT,
            last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS followers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            follower_id INTEGER,
            followed_id INTEGER,
            FOREIGN KEY(follower_id) REFERENCES users(id),
            FOREIGN KEY(followed_id) REFERENCES users(id),
            UNIQUE(follower_id, followed_id)
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            content TEXT,
            created_at TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS post_likes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            post_id INTEGER,
            user_id INTEGER,
            FOREIGN KEY(post_id) REFERENCES posts(id),
            FOREIGN KEY(user_id) REFERENCES users(id),
            UNIQUE(post_id, user_id)
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS comments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            post_id INTEGER,
            user_id INTEGER,
            content TEXT,
            created_at TIMESTAMP,
            FOREIGN KEY(post_id) REFERENCES posts(id),
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS comment_likes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            comment_id INTEGER,
            user_id INTEGER,
            FOREIGN KEY(comment_id) REFERENCES comments(id),
            FOREIGN KEY(user_id) REFERENCES users(id),
            UNIQUE(comment_id, user_id)
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender_id INTEGER,
            receiver_id INTEGER,
            content TEXT,
            created_at TIMESTAMP,
            FOREIGN KEY(sender_id) REFERENCES users(id),
            FOREIGN KEY(receiver_id) REFERENCES users(id)
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS groupes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS groupe_users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            group_id INTEGER,
            user_id INTEGER,
            FOREIGN KEY(group_id) REFERENCES groupes(id),
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS group_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            group_id INTEGER,
            sender_id INTEGER,
            content TEXT,
            created_at TIMESTAMP,
            FOREIGN KEY(group_id) REFERENCES groupes(id),
            FOREIGN KEY(sender_id) REFERENCES users(id)
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,            -- Utilisateur qui reçoit la notification
            type TEXT,                  -- 'like_post', 'like_comment', 'comment', 'follow'
            ref_id INTEGER,             -- ID du post/comment ou follower
            seen INTEGER DEFAULT 0,     -- 0 = non lu, 1 = lu
            created_at TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
    ''')

    conn.commit()
    cursor.close()
    conn.close()

def add_border_color_column():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(users)")
    columns = [col['name'] for col in cursor.fetchall()]
    if 'border_color' not in columns:
        cursor.execute("ALTER TABLE users ADD COLUMN border_color TEXT DEFAULT '#4CAF50'")
        conn.commit()
    cursor.close()
    conn.close()

add_border_color_column()

def add_banner_column():
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("PRAGMA table_info(users)")
    columns = [col['name'] for col in cursor.fetchall()]

    if 'banner_url' not in columns:
        cursor.execute("ALTER TABLE users ADD COLUMN banner_url TEXT")

    conn.commit()
    cursor.close()
    conn.close()

add_banner_column()

def add_image_to_posts():
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("PRAGMA table_info(posts)")
    columns = [col['name'] for col in cursor.fetchall()]
    if 'image_url' not in columns:
        cursor.execute("ALTER TABLE posts ADD COLUMN image_url TEXT")
        conn.commit()

    cursor.close()
    conn.close()

add_image_to_posts()

ALLOWED_MEDIA_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'mp4', 'mov'}

def allowed_media(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_MEDIA_EXTENSIONS

def add_media_columns():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(messages)")
    columns = [col['name'] for col in cursor.fetchall()]
    if 'media_url' not in columns:
        cursor.execute("ALTER TABLE messages ADD COLUMN media_url TEXT")
    if 'media_mime' not in columns:
        cursor.execute("ALTER TABLE messages ADD COLUMN media_mime TEXT")
    cursor.execute("PRAGMA table_info(group_messages)")
    columns = [col['name'] for col in cursor.fetchall()]
    if 'media_url' not in columns:
        cursor.execute("ALTER TABLE group_messages ADD COLUMN media_url TEXT")
    if 'media_mime' not in columns:
        cursor.execute("ALTER TABLE group_messages ADD COLUMN media_mime TEXT")
    conn.commit()
    cursor.close()
    conn.close()

add_media_columns()

def add_image_column():
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("PRAGMA table_info(messages)")
    columns = [col['name'] for col in cursor.fetchall()]

    if 'image_url' not in columns:
        cursor.execute("ALTER TABLE messages ADD COLUMN image_url TEXT")

    conn.commit()
    cursor.close()
    conn.close()

add_image_column()

def add_from_user_column():
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("PRAGMA table_info(notifications)")
    columns = [col['name'] for col in cursor.fetchall()]

    if 'from_user_id' not in columns:
        cursor.execute("ALTER TABLE notifications ADD COLUMN from_user_id INTEGER")

    conn.commit()
    cursor.close()
    conn.close()

add_from_user_column()

def supprimer_dependances_utilisateur(user_id):
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute('SELECT audio_url, image_url FROM messages WHERE sender_id = ? OR receiver_id = ?', (user_id, user_id))
    for row in cursor.fetchall():
        if row['audio_url']:
            audio_path = os.path.join(AUDIO_DIR, row['audio_url'])
            if os.path.exists(audio_path):
                os.remove(audio_path)
        if row['image_url']:
            image_path = os.path.join(IMAGE_DIR, row['image_url'])
            if os.path.exists(image_path):
                os.remove(image_path)

    cursor.execute('SELECT audio_url, image_url FROM group_messages WHERE sender_id = ?', (user_id,))
    for row in cursor.fetchall():
        if row['audio_url']:
            audio_path = os.path.join(AUDIO_DIR, row['audio_url'])
            if os.path.exists(audio_path):
                os.remove(audio_path)
        if row['image_url']:
            image_path = os.path.join(IMAGE_DIR, row['image_url'])
            if os.path.exists(image_path):
                os.remove(image_path)

    cursor.execute('SELECT avatar_url FROM users WHERE id = ?', (user_id,))
    avatar_row = cursor.fetchone()
    if avatar_row and avatar_row['avatar_url']:
        avatar_path = os.path.join(AVATAR_DIR, avatar_row['avatar_url'])
        if os.path.exists(avatar_path):
            os.remove(avatar_path)

    cursor.execute('DELETE FROM group_messages WHERE sender_id = ?', (user_id,))
    cursor.execute('DELETE FROM groupe_users WHERE user_id = ?', (user_id,))
    cursor.execute('DELETE FROM post_likes WHERE user_id = ?', (user_id,))
    cursor.execute('DELETE FROM comment_likes WHERE user_id = ?', (user_id,))
    cursor.execute('DELETE FROM comments WHERE user_id = ?', (user_id,))
    cursor.execute('DELETE FROM posts WHERE user_id = ?', (user_id,))
    cursor.execute('DELETE FROM messages WHERE sender_id = ? OR receiver_id = ?', (user_id, user_id))
    cursor.execute('DELETE FROM followers WHERE follower_id = ? OR followed_id = ?', (user_id, user_id))
    cursor.execute('DELETE FROM notifications WHERE user_id = ?', (user_id,))

    conn.commit()
    cursor.close()
    conn.close()
def add_location_columns():
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("PRAGMA table_info(users)")
    columns = [col['name'] for col in cursor.fetchall()]

    if 'latitude' not in columns:
        cursor.execute("ALTER TABLE users ADD COLUMN latitude REAL")
    if 'longitude' not in columns:
        cursor.execute("ALTER TABLE users ADD COLUMN longitude REAL")

    conn.commit()
    cursor.close()
    conn.close()

def add_last_seen_column():
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("PRAGMA table_info(users)")
    columns = [col['name'] for col in cursor.fetchall()]

    if 'last_seen' not in columns:
        cursor.execute("ALTER TABLE users ADD COLUMN last_seen TIMESTAMP")
        cursor.execute("UPDATE users SET last_seen = ?", (datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'),))
        conn.commit()

    cursor.close()
    conn.close()

def add_audio_columns():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(messages)")
    columns = [col['name'] for col in cursor.fetchall()]

    if 'audio_url' not in columns:
        cursor.execute("ALTER TABLE messages ADD COLUMN audio_url TEXT")
    if 'audio_mime' not in columns:
        cursor.execute("ALTER TABLE messages ADD COLUMN audio_mime TEXT")
    conn.commit()
    cursor.close()
    conn.close()

add_audio_columns()

def add_audio_columns_group_messages():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(group_messages)")
    columns = [col['name'] for col in cursor.fetchall()]

    if 'audio_url' not in columns:
        cursor.execute("ALTER TABLE group_messages ADD COLUMN audio_url TEXT")
    if 'audio_mime' not in columns:
        cursor.execute("ALTER TABLE group_messages ADD COLUMN audio_mime TEXT")
    conn.commit()
    cursor.close()
    conn.close()

add_audio_columns_group_messages()

user_status_cache = {}

def add_last_login_date_column():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(users)")
    columns = [col['name'] for col in cursor.fetchall()]

    if 'last_login_date' not in columns:
        cursor.execute("ALTER TABLE users ADD COLUMN last_login_date DATE")
        cursor.execute("UPDATE users SET last_login_date = ?", (datetime.utcnow().strftime('%Y-%m-%d'),))
        conn.commit()

    cursor.close()
    conn.close()

add_last_login_date_column()

@app.before_request
def update_last_seen_and_streak():
    if 'user_id' in session:
        now = datetime.utcnow()
        last_seen_update = session.get('last_seen_update')

        if not last_seen_update or (now - datetime.strptime(last_seen_update, '%Y-%m-%d %H:%M:%S')).seconds > 30:
            try:
                conn = get_db_connection()
                conn.execute(
                    'UPDATE users SET last_seen = ? WHERE id = ?',
                    (now.strftime('%Y-%m-%d %H:%M:%S'), session['user_id'])
                )
                conn.commit()
                session['last_seen_update'] = now.strftime('%Y-%m-%d %H:%M:%S')
            except:
                pass
            finally:
                conn.close()

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT last_login_date, streak_days FROM users WHERE id = ?', (session['user_id'],))
        row = cursor.fetchone()
        today = now.date()

        streak_days = 0
        last_login = None
        if row:
            last_login = row['last_login_date']
            streak_days = row['streak_days'] if 'streak_days' in row.keys() else 0

        if last_login:
            last_login_dt = datetime.strptime(last_login, '%Y-%m-%d').date()
            if last_login_dt == today:
                pass
            elif last_login_dt == today - timedelta(days=1):
                streak_days += 1
            else:
                streak_days = 1
        else:
            streak_days = 1

        cursor.execute('''
            UPDATE users SET last_login_date = ?, streak_days = ? WHERE id = ?
        ''', (today.strftime('%Y-%m-%d'), streak_days, session['user_id']))
        conn.commit()
        cursor.close()
        conn.close()

@app.route('/')
def home():
    return render_template('hello.html')

@app.route('/authentification', methods=['GET', 'POST'])
def authentification():
    if request.method == 'POST':
        username = request.form['username'].strip()
        email = request.form['email'].strip()
        password = request.form['password'].strip()
        hashed_password = generate_password_hash(password)
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('INSERT INTO users (username, email, password) VALUES (?, ?, ?)',
                           (username, email, hashed_password))
            conn.commit()
            return redirect(url_for('connexion'))
        except sqlite3.IntegrityError:
            error = "Email déjà utilisé"
            return render_template('authentification.html', error=error)
        finally:
            cursor.close()
            conn.close()
    return render_template('authentification.html')

@app.route('/connexion', methods=['GET', 'POST'])
def connexion():
    if request.method == 'POST':
        email = request.form['email'].strip()
        password = request.form['password'].strip()
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM users WHERE lower(email) = lower(?)', (email,))
        user = cursor.fetchone()
        cursor.close()
        conn.close()
        if user and check_password_hash(user['password'], password):
            session['user_id'] = user['id']
            session['username'] = user['username']
            return redirect(url_for('profil'))
        else:
            error = "Email ou mot de passe incorrect"
            return render_template('connexion.html', error=error)
    return render_template('connexion.html')

@app.route('/deconnexion')
def deconnexion():
    session.clear()
    return redirect(url_for('connexion'))

@app.route('/upload_avatar', methods=['POST'])
def upload_avatar():
    if 'user_id' not in session:
        return redirect(url_for('connexion'))

    if 'avatar' not in request.files:
        return redirect(url_for('profil'))

    file = request.files['avatar']

    if file.filename == '' or not allowed_file(file.filename):
        return redirect(url_for('profil'))

    filename = secure_filename(f"user_{session['user_id']}_{file.filename}")
    filepath = os.path.join(AVATAR_DIR, filename)
    file.save(filepath)

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET avatar_url = ? WHERE id = ?', (filename, session['user_id']))
    conn.commit()
    cursor.close()
    conn.close()

    return redirect(url_for('profil'))

@app.route('/profil')
def profil():
    if 'user_id' not in session:
        return redirect(url_for('connexion'))

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        'SELECT COUNT(*) as count FROM notifications WHERE user_id = ? AND seen = 0',
        (session['user_id'],)
    )
    notif_count = cursor.fetchone()['count']

    cursor.execute('''
        SELECT p.id, p.user_id, u.username, u.avatar_url, p.content, p.image_url, p.created_at, COUNT(pl.id) as likes_count
        FROM posts p
        JOIN users u ON u.id = p.user_id
        LEFT JOIN post_likes pl ON p.id = pl.post_id
        WHERE p.user_id = ?
        GROUP BY p.id
        ORDER BY p.created_at DESC
    ''', (session['user_id'],))

    posts_rows = cursor.fetchall()
    posts_list = []

    for post in posts_rows:
        post_dict = dict(post)
        post_dict['avatar_url'] = post_dict.get('avatar_url') or 'default.png'
        post_dict['image_url'] = post_dict.get('image_url')

        cursor.execute('''
            SELECT c.id, c.user_id, c.content, c.created_at,
                   u.username, u.avatar_url,
                   COUNT(cl.id) AS likes_count
            FROM comments c
            JOIN users u ON c.user_id = u.id
            LEFT JOIN comment_likes cl ON c.id = cl.comment_id
            WHERE c.post_id = ?
            GROUP BY c.id
            ORDER BY c.created_at ASC
        ''', (post['id'],))

        comments = []
        for c in cursor.fetchall():
            c_dict = dict(c)
            c_dict['avatar_url'] = c_dict.get('avatar_url') or 'default.png'
            comments.append(c_dict)

        post_dict['comments'] = comments
        posts_list.append(post_dict)

    cursor.execute('''
        SELECT u.id, u.username, u.avatar_url, u.last_seen
        FROM followers f
        JOIN users u ON u.id = f.follower_id
        WHERE f.followed_id = ?
    ''', (session['user_id'],))

    abonnes = []
    for abonne in cursor.fetchall():
        ab_dict = dict(abonne)
        ab_dict['status'] = get_online_status(abonne['last_seen'])
        ab_dict['avatar_url'] = ab_dict.get('avatar_url') or 'default.png'
        abonnes.append(ab_dict)

    cursor.execute('''
        SELECT u.id, u.username, u.avatar_url, u.last_seen
        FROM followers f
        JOIN users u ON u.id = f.followed_id
        WHERE f.follower_id = ?
    ''', (session['user_id'],))

    abonnements = []
    for abo in cursor.fetchall():
        abo_dict = dict(abo)
        abo_dict['status'] = get_online_status(abo['last_seen'])
        abo_dict['avatar_url'] = abo_dict.get('avatar_url') or 'default.png'
        abonnements.append(abo_dict)

    cursor.execute('SELECT COUNT(*) as count FROM followers WHERE followed_id = ?', (session['user_id'],))
    abonnes_count = cursor.fetchone()['count']

    cursor.execute('SELECT COUNT(*) as count FROM followers WHERE follower_id = ?', (session['user_id'],))
    abonnements_count = cursor.fetchone()['count']

    cursor.execute('SELECT * FROM users WHERE id = ?', (session['user_id'],))
    user_row = cursor.fetchone()

    if user_row:
        user_dict = dict(user_row)
        user_dict['status'] = get_online_status(user_row['last_seen'])
        user_dict['avatar_url'] = user_dict.get('avatar_url') or 'default.png'
        user_dict['bio'] = user_dict.get('bio') or ""
        user_dict['streak_days'] = user_dict.get('streak_days', 0)
    else:
        user_dict = {
            "id": session['user_id'],
            "username": session['username'],
            "avatar_url": "default.png",
            "bio": "",
            "status": "Hors ligne",
            "streak_days": 0
        }

    cursor.close()
    conn.close()

    return render_template(
        'profil.html',
        user=user_dict,
        posts=posts_list,
        abonnes=abonnes,
        abonnements=abonnements,
        notif_count=notif_count,
        abonnes_count=abonnes_count,
        abonnements_count=abonnements_count
    )

@app.route('/abonnées')
@app.route('/abonnées/<int:user_id>')
def abonnées(user_id=None):
    if 'user_id' not in session:
        return redirect(url_for('connexion'))

    target_id = user_id or session['user_id']

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        'SELECT COUNT(*) as count FROM notifications WHERE user_id = ? AND seen = 0',
        (session['user_id'],)
    )
    notif_count = cursor.fetchone()['count']

    cursor.execute('SELECT username FROM users WHERE id = ?', (target_id,))
    profile_user = cursor.fetchone()
    if not profile_user:
        cursor.close()
        conn.close()
        return 'Utilisateur introuvable'
    profile_username = profile_user['username']

    cursor.execute('''
        SELECT u.id, u.username, u.avatar_url, u.last_seen
        FROM followers f
        JOIN users u ON u.id = f.follower_id
        WHERE f.followed_id = ?
    ''', (target_id,))

    abonnes = []
    for abonne in cursor.fetchall():
        ab_dict = dict(abonne)
        ab_dict['status'] = get_online_status(abonne['last_seen'])
        ab_dict['avatar_url'] = ab_dict.get('avatar_url') or 'default.png'
        abonnes.append(ab_dict)

    cursor.close()
    conn.close()

    return render_template(
        'abonnées.html',
        abonnes=abonnes,
        notif_count=notif_count,
        username=session.get('username'),
        profile_username=profile_username,
        target_id=target_id,
        own_profile=(target_id == session['user_id'])
    )

@app.route('/abonnement')
@app.route('/abonnement/<int:user_id>')
def abonnement(user_id=None):
    if 'user_id' not in session:
        return redirect(url_for('connexion'))

    target_id = user_id or session['user_id']

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        'SELECT COUNT(*) as count FROM notifications WHERE user_id = ? AND seen = 0',
        (session['user_id'],)
    )
    notif_count = cursor.fetchone()['count']

    cursor.execute('SELECT username FROM users WHERE id = ?', (target_id,))
    profile_user = cursor.fetchone()
    if not profile_user:
        cursor.close()
        conn.close()
        return 'Utilisateur introuvable'
    profile_username = profile_user['username']

    cursor.execute('''
        SELECT u.id, u.username, u.avatar_url, u.last_seen
        FROM followers f
        JOIN users u ON u.id = f.followed_id
        WHERE f.follower_id = ?
    ''', (target_id,))

    abonnements = []
    for abo in cursor.fetchall():
        abo_dict = dict(abo)
        abo_dict['status'] = get_online_status(abo['last_seen'])
        abo_dict['avatar_url'] = abo_dict.get('avatar_url') or 'default.png'
        abonnements.append(abo_dict)

    cursor.close()
    conn.close()

    return render_template(
        'abonnement.html',
        abonnements=abonnements,
        notif_count=notif_count,
        username=session.get('username'),
        profile_username=profile_username,
        target_id=target_id,
        own_profile=(target_id == session['user_id'])
    )

@app.route('/messagerie')
def messagerie():
    if 'user_id' not in session:
        return redirect(url_for('connexion'))

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute('''
        SELECT g.id, g.name
        FROM groupes g
        JOIN groupe_users gu ON g.id = gu.group_id
        WHERE gu.user_id = ?
    ''', (session['user_id'],))
    groups = cursor.fetchall()

    cursor.execute('''
        SELECT DISTINCT u.id, u.username, u.avatar_url, u.last_seen
        FROM users u
        WHERE u.id IN (
            SELECT receiver_id FROM messages WHERE sender_id = ?
            UNION
            SELECT sender_id FROM messages WHERE receiver_id = ?
        )
    ''', (session['user_id'], session['user_id']))
    users_rows = cursor.fetchall()

    users = []
    for u in users_rows:
        u_dict = dict(u)
        u_dict['avatar_url'] = u_dict.get('avatar_url') or 'default.png'
        u_dict['status'] = get_online_status(u_dict.get('last_seen'))
        users.append(u_dict)

    cursor.close()
    conn.close()

    return render_template('messagerie.html', groups=groups, users=users)

@app.route('/profil/<int:user_id>')
def profil_public(user_id):
    if 'user_id' not in session:
        return redirect(url_for('connexion'))

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute('SELECT * FROM users WHERE id = ?', (user_id,))
    user_row = cursor.fetchone()
    if not user_row:
        cursor.close()
        conn.close()
        return "Utilisateur introuvable"

    user_dict = dict(user_row)
    user_dict['status'] = get_online_status(user_dict.get('last_seen'))
    user_dict['avatar_url'] = user_dict['avatar_url'] or 'default.png'
    user_dict['streak_days'] = user_dict.get('streak_days', 0)
    user_dict['bio'] = user_dict.get('bio', '')
    user_dict['border_color'] = user_dict.get('border_color', '#4CAF50')

    cursor.execute(
        'SELECT 1 FROM followers WHERE follower_id = ? AND followed_id = ?',
        (session['user_id'], user_id)
    )
    is_following = cursor.fetchone() is not None

    cursor.execute('SELECT COUNT(*) as count FROM followers WHERE followed_id = ?', (user_id,))
    abonnes_count = cursor.fetchone()['count']

    cursor.execute('SELECT COUNT(*) as count FROM followers WHERE follower_id = ?', (user_id,))
    abonnements_count = cursor.fetchone()['count']

    cursor.execute('''
        SELECT u.id, u.username, u.avatar_url, u.last_seen
        FROM followers f
        JOIN users u ON u.id = f.follower_id
        WHERE f.followed_id = ?
    ''', (user_id,))
    abonnes = []
    for ab in cursor.fetchall():
        ab_dict = dict(ab)
        ab_dict['status'] = get_online_status(ab_dict.get('last_seen'))
        ab_dict['avatar_url'] = ab_dict['avatar_url'] or 'default.png'
        abonnes.append(ab_dict)

    cursor.execute('''
        SELECT u.id, u.username, u.avatar_url, u.last_seen
        FROM followers f
        JOIN users u ON u.id = f.followed_id
        WHERE f.follower_id = ?
    ''', (user_id,))
    abonnements = []
    for abo in cursor.fetchall():
        abo_dict = dict(abo)
        abo_dict['status'] = get_online_status(abo_dict.get('last_seen'))
        abo_dict['avatar_url'] = abo_dict['avatar_url'] or 'default.png'
        abonnements.append(abo_dict)

    cursor.execute('''
        SELECT p.id, p.user_id, u.username, u.avatar_url, p.content, p.image_url, p.created_at,
               COUNT(pl.id) as likes_count
        FROM posts p
        JOIN users u ON u.id = p.user_id
        LEFT JOIN post_likes pl ON p.id = pl.post_id
        WHERE p.user_id = ?
        GROUP BY p.id
        ORDER BY p.created_at DESC
    ''', (user_id,))

    posts_list = []
    for post in cursor.fetchall():
        post_dict = dict(post)
        post_dict['avatar_url'] = post_dict['avatar_url'] or 'default.png'

        cursor.execute('''
            SELECT c.id, c.user_id, c.content, c.created_at,
                   u.username, u.avatar_url,
                   COUNT(cl.id) AS likes_count
            FROM comments c
            JOIN users u ON c.user_id = u.id
            LEFT JOIN comment_likes cl ON c.id = cl.comment_id
            WHERE c.post_id = ?
            GROUP BY c.id
            ORDER BY c.created_at ASC
        ''', (post['id'],))

        comments_list = []
        for c in cursor.fetchall():
            c_dict = dict(c)
            c_dict['avatar_url'] = c_dict['avatar_url'] or 'default.png'
            comments_list.append(c_dict)

        post_dict['comments'] = comments_list
        posts_list.append(post_dict)

    cursor.close()
    conn.close()

    return render_template(
        'profil_public.html',
        user=user_dict,
        is_following=is_following,
        abonnes=abonnes,
        abonnements=abonnements,
        posts=posts_list,
        abonnes_count=abonnes_count,
        abonnements_count=abonnements_count
    )

user_status_cache = {}

@app.route('/all_user_status')
def get_all_user_status():
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT id, last_seen FROM users")
    users = cursor.fetchall()

    statuses = {}
    for u in users:
        statuses[u['id']] = get_online_status(u['last_seen'])

    cursor.close()
    conn.close()

    return jsonify(statuses)

@app.route('/creer_post', methods=['POST'])
def creer_post():
    if 'user_id' not in session:
        return redirect(url_for('connexion'))

    content = request.form.get('content', '').strip()
    image_file = request.files.get('image')
    image_filename = None

    if image_file and image_file.filename != '' and allowed_file(image_file.filename):
        os.makedirs(IMAGE_DIR, exist_ok=True)

        timestamp = int(datetime.now().timestamp())
        filename = secure_filename(f"user_{session['user_id']}_{timestamp}_{image_file.filename}")
        image_path = os.path.join(IMAGE_DIR, filename)
        image_file.save(image_path)
        image_filename = filename

    if not content and not image_filename:
        return redirect(url_for('profil'))

    created_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            'INSERT INTO posts (user_id, content, image_url, created_at) VALUES (?, ?, ?, ?)',
            (session['user_id'], content, image_filename, created_at)
        )
        conn.commit()
    finally:
        cursor.close()
        conn.close()

    return redirect(url_for('profil'))

@app.route('/supprimer_post/<int:post_id>', methods=['POST'])
def supprimer_post(post_id):
    if 'user_id' not in session:
        return redirect(url_for('connexion'))

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute('SELECT image_url FROM posts WHERE id = ? AND user_id = ?', (post_id, session['user_id']))
    post = cursor.fetchone()
    if post and post['image_url']:
        image_path = os.path.join(IMAGE_DIR, post['image_url'])
        if os.path.exists(image_path):
            os.remove(image_path)

    cursor.execute('DELETE FROM post_likes WHERE post_id = ?', (post_id,))
    cursor.execute('DELETE FROM comment_likes WHERE comment_id IN (SELECT id FROM comments WHERE post_id = ?)', (post_id,))
    cursor.execute('DELETE FROM comments WHERE post_id = ?', (post_id,))

    cursor.execute('DELETE FROM posts WHERE id = ? AND user_id = ?', (post_id, session['user_id']))

    conn.commit()
    cursor.close()
    conn.close()

    return redirect(request.referrer or url_for('profil'))

@app.route('/like_post/<int:post_id>', methods=['POST'])
def like_post(post_id):
    if 'user_id' not in session:
        return redirect(url_for('connexion'))

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute(
            'INSERT INTO post_likes (post_id, user_id) VALUES (?, ?)',
            (post_id, session['user_id'])
        )
        conn.commit()

        cursor.execute('SELECT user_id FROM posts WHERE id = ?', (post_id,))
        post_owner = cursor.fetchone()

        if post_owner and post_owner['user_id'] != session['user_id']:
            cursor.execute('''
                INSERT INTO notifications (user_id, type, ref_id, from_user_id, created_at)
                VALUES (?, ?, ?, ?, ?)
            ''', (
                post_owner['user_id'],
                'like_post',
                post_id,
                session['user_id'],
                datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            ))
            conn.commit()

    except sqlite3.IntegrityError:
        cursor.execute(
            'DELETE FROM post_likes WHERE post_id = ? AND user_id = ?',
            (post_id, session['user_id'])
        )
        conn.commit()

    cursor.close()
    conn.close()

    return redirect(request.referrer or url_for('profil'))

@app.route('/ajouter_comment/<int:post_id>', methods=['POST'])
def ajouter_comment(post_id):
    if 'user_id' not in session:
        return redirect(url_for('connexion'))

    content = request.form['content'].strip()

    if content:
        created_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute(
            'INSERT INTO comments (post_id, user_id, content, created_at) VALUES (?, ?, ?, ?)',
            (post_id, session['user_id'], content, created_at)
        )
        conn.commit()

        cursor.execute('SELECT user_id FROM posts WHERE id = ?', (post_id,))
        post_owner = cursor.fetchone()

        if post_owner and post_owner['user_id'] != session['user_id']:
            cursor.execute('''
                INSERT INTO notifications (user_id, type, ref_id, from_user_id, created_at)
                VALUES (?, ?, ?, ?, ?)
            ''', (
                post_owner['user_id'],
                'comment',
                post_id,
                session['user_id'],
                created_at
            ))
            conn.commit()

        cursor.close()
        conn.close()

    return redirect(request.referrer or url_for('profil'))

@app.route('/like_comment/<int:comment_id>', methods=['POST'])
def like_comment(comment_id):
    if 'user_id' not in session:
        return redirect(url_for('connexion'))
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('INSERT INTO comment_likes (comment_id, user_id) VALUES (?, ?)',
                       (comment_id, session['user_id']))
        conn.commit()
    except sqlite3.IntegrityError:
        cursor.execute('DELETE FROM comment_likes WHERE comment_id = ? AND user_id = ?',
                       (comment_id, session['user_id']))
        conn.commit()
    cursor.close()
    conn.close()
    return redirect(request.referrer or url_for('profil'))

@app.route('/follow/<int:user_id>', methods=['POST'])
def follow_user(user_id):
    if 'user_id' not in session:
        return redirect(url_for('connexion'))

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute(
            'INSERT INTO followers (follower_id, followed_id) VALUES (?, ?)',
            (session['user_id'], user_id)
        )
        conn.commit()

        if user_id != session['user_id']:
            cursor.execute('''
                INSERT INTO notifications (user_id, type, ref_id, from_user_id, created_at)
                VALUES (?, ?, ?, ?, ?)
            ''', (
                user_id,
                'follow',
                session['user_id'],
                session['user_id'],
                datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            ))
            conn.commit()

    except sqlite3.IntegrityError:
        cursor.execute(
            'DELETE FROM followers WHERE follower_id = ? AND followed_id = ?',
            (session['user_id'], user_id)
        )
        conn.commit()

    finally:
        cursor.close()
        conn.close()

    return redirect(request.referrer or url_for('profil_public', user_id=user_id))

@app.route('/unfollow/<int:user_id>', methods=['POST'])
def unfollow_user(user_id):
    if 'user_id' not in session:
        return redirect(url_for('connexion'))
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM followers WHERE follower_id = ? AND followed_id = ?',
                   (session['user_id'], user_id))
    conn.commit()
    cursor.close()
    conn.close()
    return redirect(request.referrer or url_for('profil_public', user_id=user_id))


@app.route('/creer_groupe', methods=['POST'])
def creer_groupe():
    if 'user_id' not in session:
        return redirect(url_for('connexion'))
    group_name = request.form['group_name'].strip()
    if not group_name:
        return redirect(url_for('messagerie'))
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('INSERT INTO groupes (name) VALUES (?)', (group_name,))
    group_id = cursor.lastrowid
    cursor.execute('INSERT INTO groupe_users (group_id, user_id) VALUES (?, ?)', (group_id, session['user_id']))
    conn.commit()
    cursor.close()
    conn.close()
    return redirect(url_for('messagerie'))

@app.route('/groupe/<int:group_id>', methods=['GET', 'POST'], endpoint='groupe_page')
def groupe_page(group_id):
    if 'user_id' not in session:
        return redirect(url_for('connexion'))

    user_id = session['user_id']
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute('SELECT * FROM groupes WHERE id = ?', (group_id,))
    groupe = cursor.fetchone()
    if not groupe:
        cursor.close()
        conn.close()
        return "Groupe introuvable", 404

    if request.method == 'POST':
        content = request.form.get('content', '').strip()
        audio_file = request.files.get('audio')
        image_file = request.files.get('image')

        audio_filename = None
        audio_mime = None
        image_filename = None

        if audio_file and audio_file.filename:
            if audio_file.mimetype.startswith('audio'):
                timestamp = int(datetime.utcnow().timestamp())
                filename = secure_filename(f"group_{group_id}_user_{user_id}_{timestamp}.ogg")
                audio_path = os.path.join(AUDIO_DIR, filename)
                os.makedirs(os.path.dirname(audio_path), exist_ok=True)
                audio_file.save(audio_path)
                audio_filename = filename
                audio_mime = 'audio/ogg'

        if image_file and image_file.filename:
            if allowed_file(image_file.filename):
                timestamp = int(datetime.utcnow().timestamp())
                filename = secure_filename(f"group_{group_id}_user_{user_id}_{timestamp}_{image_file.filename}")
                image_path = os.path.join(IMAGE_DIR, filename)
                os.makedirs(os.path.dirname(image_path), exist_ok=True)
                image_file.save(image_path)
                image_filename = filename

        if content or audio_filename or image_filename:
            created_at = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
            cursor.execute(
                '''INSERT INTO group_messages
                   (group_id, sender_id, content, audio_url, audio_mime, image_url, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)''',
                (group_id, user_id, content, audio_filename, audio_mime, image_filename, created_at)
            )

            cursor.execute(
                'SELECT user_id FROM groupe_users WHERE group_id = ? AND user_id != ?',
                (group_id, user_id)
            )
            members = cursor.fetchall()
            for m in members:
                cursor.execute(
                    '''INSERT INTO notifications
                       (user_id, type, ref_id, from_user_id, created_at)
                       VALUES (?, 'group_message', ?, ?, ?)''',
                    (m['user_id'], group_id, user_id, created_at)
                )

            conn.commit()

    cursor.execute('''
        SELECT gm.*, u.username AS sender_name, u.avatar_url AS sender_avatar
        FROM group_messages gm
        JOIN users u ON gm.sender_id = u.id
        WHERE gm.group_id = ?
        ORDER BY gm.created_at ASC
    ''', (group_id,))
    messages = cursor.fetchall()

    cursor.execute('''
        SELECT id, username
        FROM users
        WHERE id != ?
          AND id NOT IN (SELECT user_id FROM groupe_users WHERE group_id = ?)
    ''', (user_id, group_id))
    users_disponibles = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template(
        'groupe.html',
        groupe=groupe,
        messages=messages,
        users_disponibles=users_disponibles
    )

@app.route('/groupe/<int:group_id>/ajouter', methods=['POST'])
def ajouter_utilisateur_groupe(group_id):
    if 'user_id' not in session:
        return redirect(url_for('connexion'))
    user_id = request.form['user_id']
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('INSERT INTO groupe_users (group_id, user_id) VALUES (?, ?)', (group_id, user_id))
    conn.commit()
    cursor.close()
    conn.close()
    return redirect(url_for('groupe_page', group_id=group_id))

@app.route('/groupe/<int:group_id>/quitter', methods=['POST'])
def quitter_groupe(group_id):
    if 'user_id' not in session:
        return redirect(url_for('connexion'))
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM groupe_users WHERE group_id = ? AND user_id = ?', (group_id, session['user_id']))
    conn.commit()
    cursor.close()
    conn.close()
    return redirect(url_for('messagerie'))

from flask import Flask, request, session, redirect, url_for, render_template
from werkzeug.utils import secure_filename
from datetime import datetime
import os

@app.route('/message/<int:receiver_id>', methods=['GET', 'POST'])
def message(receiver_id):
    if 'user_id' not in session:
        return redirect(url_for('connexion'))

    user_id = session['user_id']
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute('SELECT id, username, avatar_url FROM users WHERE id = ?', (receiver_id,))
    receiver = cursor.fetchone()
    if not receiver:
        cursor.close()
        conn.close()
        return "Utilisateur introuvable", 404

    if request.method == 'POST':
        content = request.form.get('content', '').strip()
        audio_file = request.files.get('audio')
        image_file = request.files.get('image')

        audio_filename = None
        audio_mime = None
        image_filename = None

        if audio_file and audio_file.filename != '':
            if audio_file.mimetype.startswith('audio'):
                timestamp = int(datetime.utcnow().timestamp())
                filename = secure_filename(f"user_{user_id}_{timestamp}.ogg")
                audio_path = os.path.join('static', 'audio', filename)
                os.makedirs(os.path.dirname(audio_path), exist_ok=True)
                audio_file.save(audio_path)
                audio_filename = filename
                audio_mime = 'audio/ogg'

        if image_file and image_file.filename != '' and allowed_file(image_file.filename):
            timestamp = int(datetime.utcnow().timestamp())
            filename = secure_filename(f"img_{user_id}_{timestamp}_{image_file.filename}")
            image_path = os.path.join('static', 'images', filename)
            os.makedirs(os.path.dirname(image_path), exist_ok=True)
            image_file.save(image_path)
            image_filename = filename


        if content or audio_filename or image_filename:
            created_at = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
            cursor.execute(
                '''INSERT INTO messages
                   (sender_id, receiver_id, content, audio_url, audio_mime, image_url, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)''',
                (user_id, receiver_id, content, audio_filename, audio_mime, image_filename, created_at)
            )
            message_id = cursor.lastrowid

            cursor.execute(
                '''INSERT INTO notifications (user_id, type, ref_id, from_user_id, created_at)
                   VALUES (?, 'message', ?, ?, ?)''',
                (receiver_id, message_id, user_id, created_at)
            )

            conn.commit()

    cursor.execute('''
        SELECT m.id, m.sender_id, m.receiver_id, m.content,
               m.audio_url, m.audio_mime, m.image_url, m.created_at,
               u.username AS sender_name,
               u.avatar_url AS sender_avatar
        FROM messages m
        JOIN users u ON m.sender_id = u.id
        WHERE (m.sender_id = ? AND m.receiver_id = ?)
           OR (m.sender_id = ? AND m.receiver_id = ?)
        ORDER BY m.created_at ASC
    ''', (user_id, receiver_id, receiver_id, user_id))

    messages = [
        {
            'id': m['id'],
            'sender_id': m['sender_id'],
            'receiver_id': m['receiver_id'],
            'content': m['content'],
            'audio_url': m['audio_url'],
            'audio_mime': m['audio_mime'],
            'image_url': m['image_url'],
            'created_at': m['created_at'],
            'sender_name': m['sender_name'],
            'sender_avatar': m['sender_avatar']
        }
        for m in cursor.fetchall()
    ]

    cursor.close()
    conn.close()

    return render_template('message.html', receiver=receiver, messages=messages)

@app.route('/messages/<int:receiver_id>/new/<int:last_id>')
def new_messages(receiver_id, last_id):
    if 'user_id' not in session:
        return jsonify([])

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute('''
        SELECT m.*, u.username AS sender_name, u.avatar_url AS sender_avatar
        FROM messages m
        JOIN users u ON m.sender_id = u.id
        WHERE ((m.sender_id = ? AND m.receiver_id = ?)
           OR (m.sender_id = ? AND m.receiver_id = ?))
          AND m.id > ?
        ORDER BY m.created_at
    ''', (session['user_id'], receiver_id, receiver_id, session['user_id'], last_id))

    messages = cursor.fetchall()
    cursor.close()
    conn.close()

    result = []
    for m in messages:
        result.append({
            'id': m['id'],
            'sender_name': m['sender_name'],
            'sender_avatar': m['sender_avatar'] or 'default.png',
            'content': m['content'],
            'audio_url': m['audio_url'],
            'audio_mime': m['audio_mime'],
            'created_at': m['created_at']
        })
    return jsonify(result)

@app.route('/serve_audio/<filename>')
def serve_audio(filename):
    file_path = os.path.join(AUDIO_DIR, filename)
    return send_file(
        file_path,
        mimetype='audio/ogg',
        as_attachment=False,
        conditional=True
    )

@app.route('/supprimer_compte', methods=['POST'])
def supprimer_compte():
    if 'user_id' not in session:
        return redirect(url_for('connexion'))

    supprimer_dependances_utilisateur(session['user_id'])

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM users WHERE id = ?', (session['user_id'],))
    conn.commit()
    cursor.close()
    conn.close()

    session.clear()
    return redirect(url_for('connexion'))

@app.route('/feed_abonnement')
def feed_abonnement():
    if 'user_id' not in session:
        return redirect(url_for('connexion'))

    user_id = session['user_id']
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute('SELECT followed_id FROM followers WHERE follower_id = ?', (user_id,))
    followed_users = [row['followed_id'] for row in cursor.fetchall()]

    posts_list = []

    if followed_users:
        query = f'''
            SELECT p.id, p.user_id, u.username, u.avatar_url, p.content, p.image_url, p.created_at,
                   COUNT(pl.id) as likes_count
            FROM posts p
            JOIN users u ON u.id = p.user_id
            LEFT JOIN post_likes pl ON p.id = pl.post_id
            WHERE p.user_id IN ({','.join(['?']*len(followed_users))})
            GROUP BY p.id
            ORDER BY p.created_at DESC
        '''
        cursor.execute(query, followed_users)
        posts = cursor.fetchall()

        for post in posts:
            post_dict = dict(post)
            post_dict['avatar_url'] = post_dict['avatar_url'] if post_dict['avatar_url'] else 'default.png'
            post_dict['image_url'] = post_dict['image_url'] if post_dict['image_url'] else None

            cursor.execute('''
                SELECT c.id, c.user_id, c.content, c.created_at, u.username, u.avatar_url, COUNT(cl.id) AS likes_count
                FROM comments c
                JOIN users u ON c.user_id = u.id
                LEFT JOIN comment_likes cl ON c.id = cl.comment_id
                WHERE c.post_id = ?
                GROUP BY c.id
                ORDER BY c.created_at ASC
            ''', (post['id'],))
            comments_rows = cursor.fetchall()
            comments_list = []

            for c in comments_rows:
                c_dict = dict(c)
                c_dict['avatar_url'] = c_dict['avatar_url'] if c_dict['avatar_url'] else 'default.png'
                comments_list.append(c_dict)

            post_dict['comments'] = comments_list
            posts_list.append(post_dict)

    cursor.close()
    conn.close()

    return render_template('feed_abonnement.html', posts=posts_list)

@app.route('/notifications')
def notifications():
    if 'user_id' not in session:
        return redirect(url_for('connexion'))

    user_id = session['user_id']
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute('''
        SELECT
            n.*,
            g.name AS group_name
        FROM notifications n
        LEFT JOIN groupes g ON n.type = 'group_message' AND n.ref_id = g.id
        WHERE n.user_id = ?
        ORDER BY n.created_at DESC
    ''', (user_id,))
    raw_notifications = cursor.fetchall()

    cursor.execute(
        'UPDATE notifications SET seen = 1 WHERE user_id = ? AND seen = 0',
        (user_id,)
    )
    conn.commit()

    notifications_list = []
    for n in raw_notifications:
        notif = dict(n)

        from_user_id = notif.get('from_user_id')

        if from_user_id:
            cursor.execute('SELECT username FROM users WHERE id = ?', (from_user_id,))
            user_row = cursor.fetchone()
            notif['from_username'] = user_row['username'] if user_row else f"Utilisateur #{from_user_id}"
        else:
            notif['from_username'] = 'Système'

        if notif['type'] == 'message' and from_user_id:
            notif['conversation_link'] = url_for('message', receiver_id=from_user_id)
        elif notif['type'] == 'group_message' and notif.get('ref_id'):
            notif['conversation_link'] = url_for('groupe_page', group_id=notif['ref_id'])
        else:
            notif['conversation_link'] = None

        notifications_list.append(notif)

    cursor.close()
    conn.close()

    return render_template('notifications.html', notifications=notifications_list)


@app.route('/notifications/mark_read', methods=['POST'])
def mark_notifications_read():
    if 'user_id' not in session:
        return redirect(url_for('connexion'))

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            'UPDATE notifications SET seen = 1 WHERE user_id = ?',
            (session['user_id'],)
        )
        conn.commit()
    finally:
        cursor.close()
        conn.close()

    return redirect(url_for('notifications'))

@app.route('/carte')
def carte():
    if 'user_id' not in session:
        return redirect(url_for('connexion'))

    try:
        return render_template('carte.html')
    except Exception as e:
        return f"Erreur lors du chargement de la carte : {e}", 500

@app.route('/api/user_positions')
def user_positions():
    if 'user_id' not in session:
        return jsonify([])

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT id, username, avatar_url, latitude, longitude FROM users WHERE latitude IS NOT NULL AND longitude IS NOT NULL')
    users = cursor.fetchall()
    cursor.close()
    conn.close()

    result = []
    for u in users:
        result.append({
            'id': u['id'],
            'username': u['username'],
            'avatar_url': u['avatar_url'] or 'default.png',
            'lat': u['latitude'],
            'lon': u['longitude']
        })
    return jsonify(result)

@app.route('/update_position', methods=['POST'])
def update_position():
    if 'user_id' not in session:
        return jsonify({'error': 'non connecté'}), 401

    lat = request.form.get('lat')
    lon = request.form.get('lon')

    if lat and lon:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('UPDATE users SET latitude = ?, longitude = ? WHERE id = ?', (lat, lon, session['user_id']))
        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({'success': True})

    return jsonify({'error': 'latitude/longitude manquante'}), 400

@app.route('/modifier_bio', methods=['POST'], endpoint='update_bio')
def update_bio():
    if 'user_id' not in session:
        return redirect(url_for('connexion'))

    nouvelle_bio = request.form.get('bio', '').strip()
    if nouvelle_bio is not None:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('UPDATE users SET bio = ? WHERE id = ?', (nouvelle_bio, session['user_id']))
        conn.commit()
        cursor.close()
        conn.close()

    return redirect(url_for("profil"))

import os
from flask import session, jsonify

@app.route('/supprimer_message/<int:message_id>', methods=['POST'])
def supprimer_message(message_id):
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Non connecté'}), 403

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute(
            'SELECT sender_id, audio_url, image_url FROM messages WHERE id = ?',
            (message_id,)
        )
        msg = cursor.fetchone()

        if not msg or msg['sender_id'] != session['user_id']:
            return jsonify({'success': False, 'error': 'Permission refusée'}), 403

        if msg['audio_url']:
            audio_path = os.path.join(AUDIO_DIR, msg['audio_url'])
            if os.path.exists(audio_path):
                os.remove(audio_path)
        if msg['image_url']:
            image_path = os.path.join(IMAGE_DIR, msg['image_url'])
            if os.path.exists(image_path):
                os.remove(image_path)

        cursor.execute('DELETE FROM messages WHERE id = ?', (message_id,))
        conn.commit()

    finally:
        cursor.close()
        conn.close()

    return jsonify({'success': True})

@app.route('/groupe/<int:group_id>/supprimer_message/<int:message_id>', methods=['POST'])
def supprimer_message_groupe(group_id, message_id):
    if 'user_id' not in session:
        return redirect(url_for('connexion'))

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute(
            'SELECT sender_id, audio_url, image_url FROM group_messages WHERE id = ? AND group_id = ?',
            (message_id, group_id)
        )
        message = cursor.fetchone()
        if not message or message['sender_id'] != session['user_id']:
            return "Message introuvable ou action non autorisée", 403

        if message['audio_url']:
            audio_path = os.path.join(AUDIO_DIR, message['audio_url'])
            if os.path.exists(audio_path):
                os.remove(audio_path)
        if message['image_url']:
            image_path = os.path.join(IMAGE_DIR, message['image_url'])
            if os.path.exists(image_path):
                os.remove(image_path)

        cursor.execute('DELETE FROM group_messages WHERE id = ?', (message_id,))
        conn.commit()

    finally:
        cursor.close()
        conn.close()

    return jsonify({'success': True})

@app.route('/upload_banner', methods=['POST'])
def upload_banner():
    if 'user_id' not in session:
        return redirect(url_for('connexion'))

    if 'banner' not in request.files:
        return redirect(url_for('profil'))

    file = request.files['banner']

    if file.filename == '' or not allowed_file(file.filename):
        return redirect(url_for('profil'))

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT banner_url FROM users WHERE id = ?", (session['user_id'],))
    user = cursor.fetchone()

    if user and user['banner_url']:
        old_path = os.path.join(IMAGE_DIR, user['banner_url'])
        if os.path.exists(old_path):
            os.remove(old_path)

    filename = secure_filename(f"banner_{session['user_id']}_{file.filename}")
    filepath = os.path.join(IMAGE_DIR, filename)
    file.save(filepath)

    cursor.execute(
        'UPDATE users SET banner_url = ? WHERE id = ?',
        (filename, session['user_id'])
    )

    conn.commit()
    cursor.close()
    conn.close()

    return redirect(url_for('profil'))

@app.route('/update_border_color', methods=['POST'])
def update_border_color():
    if 'user_id' not in session:
        return redirect(url_for('connexion'))

    color = request.form.get('border_color', '#4CAF50')
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET border_color = ? WHERE id = ?', (color, session['user_id']))
    conn.commit()
    cursor.close()
    conn.close()
    return redirect(url_for('profil'))

@app.route('/leaderboard')
def leaderboard():
    if 'user_id' not in session:
        return redirect(url_for('connexion'))

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT u.id, u.username, u.avatar_url, COUNT(f.followed_id) as followers_count
        FROM users u
        LEFT JOIN followers f ON u.id = f.followed_id
        GROUP BY u.id
        ORDER BY followers_count DESC
        LIMIT 10
    """)
    top_followers = cursor.fetchall()

    cursor.execute("""
        SELECT u.id, u.username, u.avatar_url, COUNT(pl.id) as total_likes
        FROM users u
        JOIN posts p ON u.id = p.user_id
        LEFT JOIN post_likes pl ON p.id = pl.post_id
        GROUP BY u.id
        ORDER BY total_likes DESC
        LIMIT 10
    """)
    top_likes = cursor.fetchall()

    cursor.execute("""
        SELECT id, username, avatar_url, streak_days
        FROM users
        ORDER BY streak_days DESC
        LIMIT 10
    """)
    top_streak = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template(
        'leaderboard.html',
        top_followers=top_followers,
        top_likes=top_likes,
        top_streak=top_streak
    )

@app.route('/recherche', methods=['GET'])
def recherche():
    if 'user_id' not in session:
        return redirect(url_for('connexion'))

    query = request.args.get('q', '').strip()

    users = []

    if query:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute('''
            SELECT id, username, avatar_url
            FROM users
            WHERE username LIKE ?
              AND id != ?
            LIMIT 20
        ''', (f'%{query}%', session['user_id']))

        users = cursor.fetchall()

        cursor.close()
        conn.close()

    return render_template('recherche.html', users=users, query=query)

@app.route('/feed_global')
def feed_global():
    if 'user_id' not in session:
        return redirect(url_for('connexion'))

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT p.id, p.user_id, u.username, u.avatar_url,
               p.content, p.image_url, p.created_at,
               COUNT(pl.id) as likes_count
        FROM posts p
        JOIN users u ON u.id = p.user_id
        LEFT JOIN post_likes pl ON p.id = pl.post_id
        GROUP BY p.id
        ORDER BY p.created_at DESC
    """)

    posts = cursor.fetchall()

    posts_list = []

    for post in posts:
        post_dict = dict(post)
        post_dict['avatar_url'] = post_dict['avatar_url'] or 'default.png'

        cursor.execute("""
            SELECT c.id,
                   c.user_id,
                   c.content,
                   c.created_at,
                   u.username,
                   u.avatar_url,
                   COUNT(cl.id) AS likes_count
            FROM comments c
            JOIN users u ON c.user_id = u.id
            LEFT JOIN comment_likes cl ON c.id = cl.comment_id
            WHERE c.post_id = ?
            GROUP BY c.id
            ORDER BY c.created_at ASC
        """, (post['id'],))

        comments = cursor.fetchall()

        post_dict['comments'] = [dict(c) for c in comments]
        posts_list.append(post_dict)

    conn.close()

    return render_template('feed_global.html', posts=posts_list)

@app.route('/likes')
def posts_likes():
    if 'user_id' not in session:
        return redirect(url_for('connexion'))

    user_id = session['user_id']
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute('''
        SELECT p.id, p.user_id, u.username, u.avatar_url, p.content, p.image_url, p.created_at,
               COUNT(pl2.id) as likes_count
        FROM post_likes pl
        JOIN posts p ON p.id = pl.post_id
        JOIN users u ON u.id = p.user_id
        LEFT JOIN post_likes pl2 ON p.id = pl2.post_id
        WHERE pl.user_id = ?
        GROUP BY p.id
        ORDER BY p.created_at DESC
    ''', (user_id,))

    posts = cursor.fetchall()
    posts_list = []

    for post in posts:
        post_dict = dict(post)
        post_dict['avatar_url'] = post_dict['avatar_url'] or 'default.png'

        cursor.execute('''
            SELECT c.id, c.user_id, c.content, c.created_at, u.username, u.avatar_url
            FROM comments c
            JOIN users u ON u.id = c.user_id
            WHERE c.post_id = ?
        ''', (post['id'],))

        post_dict['comments'] = [dict(c) for c in cursor.fetchall()]
        posts_list.append(post_dict)

    conn.close()

    return render_template('feed_likes.html', posts=posts_list)

if __name__ == '__main__':
    init_db()
    add_last_seen_column()
    add_location_columns()
    app.run(debug=False, host='0.0.0.0', port=5000)