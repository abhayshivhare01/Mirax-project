import os
from datetime import timedelta
from functools import wraps

from flask_jwt_extended import (
    JWTManager,
    create_access_token,
    get_jwt,
    get_jwt_identity,
    set_access_cookies,
    unset_jwt_cookies,
    verify_jwt_in_request
)
from flask_jwt_extended.exceptions import JWTExtendedException

from flask import Flask, render_template, request, session, redirect, make_response, g, jsonify
from flask_mysqldb import MySQL
from jwt.exceptions import PyJWTError
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename


app = Flask(__name__)

app.config["JWT_SECRET_KEY"] = "soulspace_secret_key"
app.config["JWT_TOKEN_LOCATION"] = ["cookies"]
app.config["JWT_ACCESS_TOKEN_EXPIRES"] = timedelta(hours=1)
app.config["JWT_COOKIE_CSRF_PROTECT"] = False
jwt = JWTManager(app)

app.secret_key = os.environ.get("SECRET_KEY")

app.config['MYSQL_HOST'] = os.environ.get("MYSQL_HOST")
app.config['MYSQL_USER'] = os.environ.get("MYSQL_USER")
app.config['MYSQL_PASSWORD'] = os.environ.get("MYSQL_PASSWORD")
app.config['MYSQL_DB'] = os.environ.get("MYSQL_DB")
app.config['MYSQL_PORT'] = int(os.environ.get("MYSQL_PORT", 3306))
app.config['MYSQL_CHARSET'] = 'utf8mb4'
app.config['MYSQL_CURSORCLASS'] = 'DictCursor'

mysql=MySQL()
mysql.init_app(app)


def login_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        try:
            verify_jwt_in_request()
            g.user_id = int(get_jwt_identity())
            g.username = get_jwt().get("username")
        except (JWTExtendedException, PyJWTError, ValueError):
            return redirect("/")

        return view(*args, **kwargs)

    return wrapped_view


@app.route("/" , methods=["GET","POST"])
def login_page():
    error = ""
    if request.method == "POST":

        login_data = request.get_json(silent=True) or request.form
        username = login_data["username"]
        password = login_data["password"]

        cur = mysql.connection.cursor()

        cur.execute("SELECT * FROM users WHERE username=%s",[username])

        user = cur.fetchone()
        print(user)
        cur.close()

        if user:

            stored_password = user['password']

            if check_password_hash(stored_password, password):

                session["user_id"] = user['id']
                session["username"] = user['username']
                access_token = create_access_token(
                    identity=str(user['id']),
                    additional_claims={"username": user['username']}
                )

                if request.is_json:
                    return jsonify({
                        "access_token": access_token,
                        "user_id": user['id'],
                        "username": user['username']
                    })

                response = make_response(redirect("/home"))
                set_access_cookies(response, access_token)

                return response
            else:
                error = "Incorrect username or password"

        else:
            error = "Incorrect username or password"

        if request.is_json:
            return jsonify({"error": error}), 401

    return render_template("login_page.html",error=error)


@app.route("/register" , methods=["POST","GET"])
def register_page():
    if request.method == "POST":
        username = request.form["username"]
        email = request.form["email"]
        password = request.form["password"]

        hashed_password = generate_password_hash(password)

        cur = mysql.connection.cursor()

        cur.execute("INSERT INTO users(username, email, password) VALUES (%s, %s, %s)",(username, email, hashed_password))

        mysql.connection.commit()

        cur.close()

        return redirect("/")

    return render_template("register.html")


@app.route("/add", methods=["GET", "POST"])
@login_required
def add_diary():

    if request.method == "POST":

        title = request.form["title"]
        mood = request.form["mood"]
        content = request.form["content"]
        start_date = request.form["start_date"]
        end_date = request.form["end_date"]
        tagged_people = request.form["tagged_people"]
        folder_name = request.form["folder_name"]

        user_id = g.user_id

        image = request.files.get("image")
        filename = ""

        if image and image.filename:
            filename = secure_filename(image.filename)
            image.save(os.path.join(app.root_path, "static", "uploads", filename))

        cur = mysql.connection.cursor()

        cur.execute("""
                    INSERT INTO diaries 
                    (user_id, title, content, mood, start_date, end_date, tagged_people, folder_name, image)
                        VALUES(%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                        (  user_id,title,content,mood,start_date,end_date,tagged_people,folder_name,filename))


        mysql.connection.commit()
        diary_id = cur.lastrowid

        people = tagged_people.split(",")

        for person in people:

            username = person.strip()

            cur.execute("SELECT id FROM users WHERE username=%s",[username])




            tagged_user = cur.fetchone()

            if tagged_user:
                shared_user_id = tagged_user['id']

                cur.execute("""
                            INSERT INTO shared_diaries
                                (diary_id, shared_with_user_id)
                            VALUES (%s, %s)""",
                            (diary_id, shared_user_id))

        mysql.connection.commit()

        cur.close()

        return redirect("/home")

    return render_template("add.html")
@app.route("/home")
@login_required
def home():

    user_id = g.user_id

    from_date = request.args.get("from_date")
    to_date = request.args.get("to_date")

    cur = mysql.connection.cursor()

    if from_date and to_date:

        cur.execute("""
            SELECT * FROM diaries
            WHERE
            (
                user_id = %s
                OR id IN (
                    SELECT diary_id
                    FROM shared_diaries
                    WHERE shared_with_user_id = %s
                )
            )
            AND
            (
                start_date <= %s
                AND end_date >= %s
            )
        """, (user_id, user_id, to_date, from_date))

    else:

        cur.execute("""SELECT * FROM diaries
            WHERE user_id = %s
            OR id IN (
                SELECT diary_id
                FROM shared_diaries
                WHERE shared_with_user_id = %s
            )
        """, (user_id, user_id))

    diaries = cur.fetchall()

    cur.close()

    return render_template(
        "home.html",
        diaries=diaries
    )

@app.route("/diary/<int:id>")
@login_required
def diary(id):

    cur = mysql.connection.cursor()

    cur.execute("SELECT * FROM diaries WHERE id=%s",[id])

    diary = cur.fetchone()

    return render_template("diary.html",diary=diary )


@app.route("/logout")
def logout():

    session.clear()
    response = make_response(redirect("/"))
    unset_jwt_cookies(response)

    return response
@app.route("/diary")
@login_required
def diary_page():
    return render_template("diary.html")

@app.route("/mood")
@login_required
def mood_page():

    user_id = g.user_id

    cur = mysql.connection.cursor()

    cur.execute("SELECT * FROM diaries WHERE user_id=%s",[user_id])

    diaries = cur.fetchall()

    cur.close()

    return render_template(
        "mood.html",
        diaries=diaries
    )

@app.route("/folder")
@login_required
def folder_page():

    user_id = g.user_id

    cur = mysql.connection.cursor()

    cur.execute("SELECT DISTINCT folder_name FROM diaries WHERE user_id=%s", [user_id])

    folders = cur.fetchall()

    cur.close()

    return render_template(
        "folder.html",
        folders=folders
    )
@app.route("/profile")
@login_required
def profile_page():

    user_id = g.user_id

    cur = mysql.connection.cursor()

    # USER INFO
    cur.execute(
        "SELECT username,email FROM users WHERE id=%s",
        [user_id]
    )

    user = cur.fetchone()

    # TOTAL DIARIES
    cur.execute(
        "SELECT COUNT(*) FROM diaries WHERE user_id=%s",
        [user_id]
    )

    total_diaries = cur.fetchone()[0]

    # HAPPY DIARIES
    cur.execute("""SELECT COUNT(*) FROM diaries WHERE user_id=%s AND mood LIKE '%%Happy%%'""", [user_id])
    happy_days = cur.fetchone()[0]

    cur.close()

    return render_template(
        "profile.html",
        user=user,
        total_diaries=total_diaries,
        happy_days=happy_days
    )

@app.route("/folder_inside_diaries/<folder_name>")
@login_required
def folder_inside_diaries_page(folder_name):

    user_id = g.user_id

    cur = mysql.connection.cursor()

    cur.execute("SELECT *FROM diaries WHERE user_id=%s AND folder_name=%s", (user_id, folder_name))

    diaries = cur.fetchall()

    cur.close()

    return render_template(
        "folder_inside_diaries.html",
        diaries=diaries,
        folder_name=folder_name
    )

@app.route("/delete_diary/<int:id>")
@login_required
def delete_diary(id):

    cur = mysql.connection.cursor()

    cur.execute("DELETE FROM diaries WHERE id=%s", [id])

    mysql.connection.commit()

    cur.close()

    return redirect("/home")

@app.route("/edit_diary/<int:id>", methods=["GET", "POST"])
@login_required
def edit_diary(id):

    cur = mysql.connection.cursor()

    if request.method == "POST":

        title = request.form["title"]
        content = request.form["content"]
        mood = request.form["mood"]

        cur.execute("""
                    UPDATE diaries 
                    SET title=%s,
                        content=%s, 
                        mood=%s
                    WHERE id=%s
                    """,
                    (title, content, mood, id))

        mysql.connection.commit()

        return redirect(f"/diary/{id}")

    cur.execute("SELECT * FROM diaries WHERE id=%s", [id])

    diary = cur.fetchone()

    cur.close()

    return render_template("edit_diary.html", diary=diary)

@app.route("/change_password", methods=["GET", "POST"])
@login_required
def change_password():

    if request.method == "POST":

        old_password = request.form["old_password"]
        new_password = request.form["new_password"]

        user_id = g.user_id

        cur = mysql.connection.cursor()

        cur.execute(
            "SELECT password FROM users WHERE id=%s",
            [user_id]
        )

        user = cur.fetchone()

        stored_password = user[0]

        if check_password_hash(stored_password, old_password):

            new_hashed_password = generate_password_hash(new_password)

            cur.execute("UPDATE users SET password=%s WHERE id=%s",(new_hashed_password, user_id))

            mysql.connection.commit()

            cur.close()

            return redirect("/profile")

        cur.close()

        return "Old password is incorrect"

    return render_template("change_password.html")


if __name__ == "__main__":
 app.run(debug=True)
