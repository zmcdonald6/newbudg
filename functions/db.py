# MySQL Abstraction Layer for Musson Group IT's Budget Tracking Application
# Author: Zedaine McDonald
# Date; **

import pymysql
import streamlit as st
from datetime import datetime
import requests

# Initial database connection
def get_db():
    """Returns a MySQL connection using Streamlit secrets"""
    try:
        connection = pymysql.connect(
            host=st.secrets["MYSQL"]["host"],
            user=st.secrets["MYSQL"]["user"],
            password=st.secrets["MYSQL"]["password"],
            database=st.secrets["MYSQL"]["database"],
            cursorclass=pymysql.cursors.DictCursor,
            autocommit=True,
            charset="utf8mb4"
        )
        return connection
    except pymysql.Error as e:
        st.error(f"Error connecting to MySQL database: {e}")
        return None




# Users CRUD operations
def get_user_by_email(email: str):
    db = get_db()
    with db.cursor() as c:
        c.execute("""
            SELECT id, name, username, email, hashed_password, role, first_login
            FROM users
            WHERE LOWER(email) = LOWER(%s)
        """, (email,))
        return c.fetchone()


def get_all_users():
    db = get_db()
    with db.cursor() as c:
        c.execute("""
            SELECT id, name, username, email, role, first_login
            FROM users
            ORDER BY name ASC
        """)
        return c.fetchall()


def add_user(name, username, email, hashed_pw, role="user"):
    db = get_db()
    with db.cursor() as c:
        c.execute("""
            INSERT INTO users (name, username, email, hashed_password, role, first_login)
            VALUES (%s, %s, %s, %s, %s, TRUE)
        """, (name, username, email, hashed_pw, role))
    return True


def update_password(email, hashed_pw):
    db = get_db()
    with db.cursor() as c:
        c.execute("""
            UPDATE users
            SET hashed_password = %s, first_login = FALSE
            WHERE LOWER(email) = LOWER(%s)
        """, (hashed_pw, email))
    return True


def reset_user_password(email, hashed_pw):
    """
    Admin resets password -> first_login becomes TRUE.
    """
    db = get_db()
    with db.cursor() as c:
        c.execute("""
            UPDATE users
            SET hashed_password = %s, first_login = TRUE
            WHERE LOWER(email) = LOWER(%s)
        """, (hashed_pw, email))
    return True


def delete_user(email):
    db = get_db()
    with db.cursor() as c:
        c.execute("DELETE FROM users WHERE LOWER(email) = LOWER(%s)", (email,))
    return True




#Login information CRUD
def log_login_activity(email, activity_type, ip_address):
    db = get_db()
    with db.cursor() as c:
        c.execute("""
            INSERT INTO loginlogs (email, activity_type, status, timestamp)
            VALUES (%s, %s, %s, NOW())
        """, (email, activity_type, ip_address))
    return True


def get_login_logs():
    db = get_db()
    with db.cursor() as c:
        c.execute("""
            SELECT email, activity_type, status, timestamp
            FROM loginlogs
            ORDER BY timestamp DESC
        """)
        return c.fetchall()
    



#File Upload CRUD
def add_uploaded_file(file_name, file_type, uploader_email, file_url):
    db = get_db()
    with db.cursor() as c:
        c.execute("""
            INSERT INTO uploadedfiles
            (file_name, file_type, uploader_email, upload_date, file_url)
            VALUES (%s, %s, %s, NOW(), %s)
        """, (file_name, file_type, uploader_email, file_url))
    return True


def delete_uploaded_file(file_name):
    db = get_db()
    with db.cursor() as c:
        c.execute("DELETE FROM uploadedfiles WHERE file_name = %s", (file_name,))
    return True


def get_uploaded_files():
    db = get_db()
    with db.cursor() as c:
        c.execute("""
            SELECT file_name, file_type, uploader_email, upload_date, file_url
            FROM uploadedfiles
            ORDER BY upload_date DESC
        """)
        return c.fetchall()
    



#Budget State Operations
def load_budget_state_monthly(file_name: str):
    db = get_db()
    with db.cursor() as c:
        c.execute("""
            SELECT category, subcategory, month, amount, status_category
            FROM budget_state
            WHERE file_name = %s
        """, (file_name,))
        rows = c.fetchall()
    return rows


def save_budget_state_monthly(file_name, df_melted, user_email):
    """
    Saves budget-state (the “classification editor” monthly state).
    Replaces the entire file set each save.
    """
    db = get_db()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    rows = df_melted.to_dict(orient="records")

    with db.cursor() as c:
        # remove existing rows for this file
        c.execute("DELETE FROM budget_state WHERE file_name = %s", (file_name,))

        # insert new
        for r in rows:
            c.execute("""
                INSERT INTO budget_state
                (file_name, category, subcategory, month, amount, status_category, updated_by, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                file_name,
                r["Category"],
                r["Sub-Category"],
                r["Month"],
                r["Amount"],
                r["Status Category"],
                user_email,
                now
            ))

    return True




#Generic Helpers
def run_query(sql: str, params=None):
    """Run a SELECT and return all rows as list(dict)."""
    db = get_db()
    with db.cursor() as c:
        c.execute(sql, params or ())
        return c.fetchall()


def run_execute(sql: str, params=None):
    """Run INSERT/UPDATE/DELETE."""
    db = get_db()
    with db.cursor() as c:
        c.execute(sql, params or ())
    return True

#Non-SQL, IP get
def get_ip():
    try:
        response = requests.get("https://api.ipify.org?format=text")
        return response.text
    except:
        return "Unavailable"