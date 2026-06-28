"""
MedAssist AI — Backend v2
Авторизация + SQLite + Admin Panel + Kaggle tunnel proxy
"""

from fastapi import FastAPI, HTTPException, Depends, Response, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
import httpx, uuid, time, sqlite3, hashlib, secrets, os
from datetime import datetime
from pathlib import Path
from contextlib import contextmanager
from functools import wraps

# ── Config ────────────────────────────────────────────────────────────────────
# KAGGLE_URL = "https://big-melons-attend.loca.lt"
KAGGLE_URL = "https://bright-times-jam.loca.lt"
DB_PATH     = "medassist.db"
SECRET_KEY  = os.getenv("SECRET_KEY", "medassist-secret-key-2026")
FRONTEND    = Path(__file__).parent.parent / "frontend"
SESSION_TTL = 60 * 60 * 24 * 7   # 7 дней в секундах

app = FastAPI(title="MedAssist AI v2")
app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_methods=["*"], allow_headers=["*"],
                   allow_credentials=True)

# ── SQLite ─────────────────────────────────────────────────────────────────────
@contextmanager
def db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    try:
        yield con
        con.commit()
    finally:
        con.close()

def init_db():
    with db() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id       TEXT PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            email    TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            role     TEXT NOT NULL DEFAULT 'user',
            created  TEXT NOT NULL,
            active   INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS sessions (
            token    TEXT PRIMARY KEY,
            user_id  TEXT NOT NULL,
            created  INTEGER NOT NULL,
            expires  INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS queries (
            id         TEXT PRIMARY KEY,
            user_id    TEXT NOT NULL,
            message    TEXT NOT NULL,
            response   TEXT NOT NULL DEFAULT '',
            department TEXT,
            blocked    INTEGER NOT NULL DEFAULT 0,
            ms         INTEGER NOT NULL DEFAULT 0,
            created    TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS settings (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        INSERT OR IGNORE INTO settings VALUES ('kaggle_url','https://big-melons-attend.loca.lt');
        """)
        # Создаём admin если его нет
        admin = con.execute("SELECT id FROM users WHERE role='admin'").fetchone()
        if not admin:
            con.execute(
                "INSERT INTO users VALUES (?,?,?,?,?,?,?)",
                (str(uuid.uuid4()), "admin", "admin@medassist.ai",
                 hash_pw("admin123"), "admin", now(), 1)
            )

def hash_pw(pw: str) -> str:
    return hashlib.sha256((pw + SECRET_KEY).encode()).hexdigest()

def now() -> str:
    return datetime.now().isoformat()

init_db()

# ── Auth helpers ───────────────────────────────────────────────────────────────
def get_session(request: Request):
    token = request.cookies.get("session") or request.headers.get("X-Session")
    if not token:
        return None
    with db() as con:
        row = con.execute(
            "SELECT s.user_id, u.role, u.username, u.active "
            "FROM sessions s JOIN users u ON s.user_id=u.id "
            "WHERE s.token=? AND s.expires>?",
            (token, int(time.time()))
        ).fetchone()
    return dict(row) if row else None

def require_auth(request: Request):
    s = get_session(request)
    if not s or not s["active"]:
        raise HTTPException(401, "Требуется авторизация")
    return s

def require_admin(request: Request):
    s = require_auth(request)
    if s["role"] != "admin":
        raise HTTPException(403, "Нет доступа")
    return s

# ── Schemas ────────────────────────────────────────────────────────────────────
class RegisterIn(BaseModel):
    username: str
    email:    str
    password: str

class LoginIn(BaseModel):
    username: str
    password: str

class QueryIn(BaseModel):
    message: str

class TunnelIn(BaseModel):
    url: str

class UserUpdateIn(BaseModel):
    active: bool | None = None
    role:   str  | None = None

# ── Auth routes ────────────────────────────────────────────────────────────────
@app.post("/api/auth/register")
async def register(data: RegisterIn, response: Response):
    if len(data.username) < 3:
        raise HTTPException(400, "Имя пользователя минимум 3 символа")
    if len(data.password) < 6:
        raise HTTPException(400, "Пароль минимум 6 символов")
    if "@" not in data.email:
        raise HTTPException(400, "Некорректный email")
    uid = str(uuid.uuid4())
    try:
        with db() as con:
            con.execute(
                "INSERT INTO users VALUES (?,?,?,?,?,?,?)",
                (uid, data.username.strip(), data.email.strip().lower(),
                 hash_pw(data.password), "user", now(), 1)
            )
    except sqlite3.IntegrityError:
        raise HTTPException(409, "Имя пользователя или email уже заняты")
    token = _create_session(uid)
    response.set_cookie("session", token, max_age=SESSION_TTL,
                        httponly=True, samesite="lax")
    return {"ok": True, "role": "user", "username": data.username, "token": token}

@app.post("/api/auth/login")
async def login(data: LoginIn, response: Response):
    with db() as con:
        row = con.execute(
            "SELECT id, role, username, active FROM users WHERE username=? AND password=?",
            (data.username.strip(), hash_pw(data.password))
        ).fetchone()
    if not row:
        raise HTTPException(401, "Неверный логин или пароль")
    if not row["active"]:
        raise HTTPException(403, "Аккаунт заблокирован")
    token = _create_session(row["id"])
    response.set_cookie("session", token, max_age=SESSION_TTL,
                        httponly=True, samesite="lax")
    return {"ok": True, "role": row["role"], "username": row["username"], "token": token}

@app.post("/api/auth/logout")
async def logout(request: Request, response: Response):
    token = request.cookies.get("session") or request.headers.get("X-Session")
    if token:
        with db() as con:
            con.execute("DELETE FROM sessions WHERE token=?", (token,))
    response.delete_cookie("session")
    return {"ok": True}

@app.get("/api/auth/me")
async def me(request: Request):
    s = get_session(request)
    if not s:
        raise HTTPException(401, "Не авторизован")
    return {"username": s["username"], "role": s["role"]}

def _create_session(uid: str) -> str:
    token = secrets.token_hex(32)
    exp   = int(time.time()) + SESSION_TTL
    with db() as con:
        con.execute("DELETE FROM sessions WHERE user_id=?", (uid,))
        con.execute("INSERT INTO sessions VALUES (?,?,?,?)",
                    (token, uid, int(time.time()), exp))
    return token

# ── Query route ────────────────────────────────────────────────────────────────
@app.post("/api/query")
async def query(req: QueryIn, request: Request):
    session = require_auth(request)
    if not req.message.strip():
        raise HTTPException(400, "Пустой запрос")

    with db() as con:
        row = con.execute("SELECT value FROM settings WHERE key='kaggle_url'").fetchone()
    kaggle_url = row["value"] if row else ""

    t0 = time.time()
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            r = await client.post(
                f"{kaggle_url}/query",
                json={"query": req.message},
                headers={"bypass-tunnel-reminder": "true"},
            )
            r.raise_for_status()
            data = r.json()
    except httpx.ConnectError:
        raise HTTPException(503, "Модель недоступна. Проверьте URL туннеля Kaggle.")
    except Exception as e:
        raise HTTPException(500, str(e))

    ms      = int((time.time() - t0) * 1000)
    resp    = data.get("response", "")
    dept    = data.get("department")
    blocked = data.get("blocked", False)

    # FIX: убираем дублирование — оставляем только текст рекомендации
    if resp and dept:
        # Убираем первую строку если она содержит только название отделения
        lines = resp.strip().split("\n")
        clean_lines = []
        for line in lines:
            stripped = line.strip()
            if stripped == dept or stripped == dept.upper():
                continue
            clean_lines.append(line)
        resp = "\n".join(clean_lines).strip()

    uid  = session["user_id"]
    qid  = str(uuid.uuid4())

    with db() as con:
        con.execute(
            "INSERT INTO queries VALUES (?,?,?,?,?,?,?,?)",
            (qid, uid, req.message, resp, dept, int(blocked), ms, now())
        )
    return {"id": qid, "message": req.message, "response": resp,
            "department": dept, "blocked": blocked, "ms": ms,
            "timestamp": now()}

# ── History & Stats (per user) ─────────────────────────────────────────────────
@app.get("/api/history")
async def history(request: Request, limit: int = 100):
    s = require_auth(request)
    uid = s["user_id"]
    with db() as con:
        rows = con.execute(
            "SELECT * FROM queries WHERE user_id=? ORDER BY created DESC LIMIT ?",
            (uid, limit)
        ).fetchall()
        total = con.execute("SELECT COUNT(*) FROM queries WHERE user_id=?", (uid,)).fetchone()[0]
    return {"items": [dict(r) for r in rows], "total": total}

@app.get("/api/stats")
async def stats(request: Request):
    s = require_auth(request)
    uid = s["user_id"]
    with db() as con:
        total   = con.execute("SELECT COUNT(*) FROM queries WHERE user_id=?", (uid,)).fetchone()[0]
        blocked = con.execute("SELECT COUNT(*) FROM queries WHERE user_id=? AND blocked=1", (uid,)).fetchone()[0]
        avg_ms  = con.execute("SELECT AVG(ms) FROM queries WHERE user_id=?", (uid,)).fetchone()[0]
        depts   = con.execute(
            "SELECT department, COUNT(*) as cnt FROM queries "
            "WHERE user_id=? AND blocked=0 AND department IS NOT NULL "
            "GROUP BY department ORDER BY cnt DESC", (uid,)
        ).fetchall()
    return {
        "total": total, "blocked": blocked,
        "medical": total - blocked,
        "avg_ms": int(avg_ms or 0),
        "departments": [{"name": r["department"], "count": r["cnt"]} for r in depts],
    }

@app.delete("/api/history")
async def clear_history(request: Request):
    s = require_auth(request)
    with db() as con:
        con.execute("DELETE FROM queries WHERE user_id=?", (s["user_id"],))
    return {"ok": True}

@app.get("/api/health")
async def health(request: Request):
    with db() as con:
        row = con.execute("SELECT value FROM settings WHERE key='kaggle_url'").fetchone()
    return {"ok": True, "kaggle_url": row["value"] if row else ""}

# ── Admin routes ───────────────────────────────────────────────────────────────
@app.get("/api/admin/users")
async def admin_users(request: Request):
    require_admin(request)
    with db() as con:
        rows = con.execute(
            "SELECT id, username, email, role, created, active, "
            "(SELECT COUNT(*) FROM queries q WHERE q.user_id=u.id) as query_count "
            "FROM users u ORDER BY created DESC"
        ).fetchall()
    return {"users": [dict(r) for r in rows]}

@app.patch("/api/admin/users/{uid}")
async def admin_update_user(uid: str, data: UserUpdateIn, request: Request):
    require_admin(request)
    s = get_session(request)
    if uid == s["user_id"]:
        raise HTTPException(400, "Нельзя изменить себя")
    updates, vals = [], []
    if data.active is not None:
        updates.append("active=?"); vals.append(int(data.active))
    if data.role is not None:
        if data.role not in ("user", "admin"):
            raise HTTPException(400, "Роль: user или admin")
        updates.append("role=?"); vals.append(data.role)
    if not updates:
        raise HTTPException(400, "Нет полей для обновления")
    vals.append(uid)
    with db() as con:
        con.execute(f"UPDATE users SET {','.join(updates)} WHERE id=?", vals)
    return {"ok": True}

@app.delete("/api/admin/users/{uid}")
async def admin_delete_user(uid: str, request: Request):
    s = require_admin(request)
    if uid == s["user_id"]:
        raise HTTPException(400, "Нельзя удалить себя")
    with db() as con:
        con.execute("DELETE FROM queries WHERE user_id=?", (uid,))
        con.execute("DELETE FROM sessions WHERE user_id=?", (uid,))
        con.execute("DELETE FROM users WHERE id=?", (uid,))
    return {"ok": True}

@app.get("/api/admin/stats")
async def admin_stats(request: Request):
    require_admin(request)
    with db() as con:
        total_u  = con.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        total_q  = con.execute("SELECT COUNT(*) FROM queries").fetchone()[0]
        blocked  = con.execute("SELECT COUNT(*) FROM queries WHERE blocked=1").fetchone()[0]
        avg_ms   = con.execute("SELECT AVG(ms) FROM queries").fetchone()[0]
        depts    = con.execute(
            "SELECT department, COUNT(*) as cnt FROM queries "
            "WHERE blocked=0 AND department IS NOT NULL "
            "GROUP BY department ORDER BY cnt DESC"
        ).fetchall()
        recent   = con.execute(
            "SELECT q.*, u.username FROM queries q "
            "JOIN users u ON q.user_id=u.id "
            "ORDER BY q.created DESC LIMIT 50"
        ).fetchall()
    return {
        "total_users": total_u, "total_queries": total_q,
        "blocked": blocked, "medical": total_q - blocked,
        "avg_ms": int(avg_ms or 0),
        "departments": [{"name": r["department"], "count": r["cnt"]} for r in depts],
        "recent": [dict(r) for r in recent],
    }

@app.get("/api/admin/queries")
async def admin_queries(request: Request, limit: int = 200):
    require_admin(request)
    with db() as con:
        rows = con.execute(
            "SELECT q.*, u.username FROM queries q "
            "JOIN users u ON q.user_id=u.id "
            "ORDER BY q.created DESC LIMIT ?", (limit,)
        ).fetchall()
    return {"items": [dict(r) for r in rows]}

@app.get("/api/admin/settings")
async def admin_get_settings(request: Request):
    require_admin(request)
    with db() as con:
        rows = con.execute("SELECT key, value FROM settings").fetchall()
    return {r["key"]: r["value"] for r in rows}

@app.post("/api/admin/tunnel")
async def admin_set_tunnel(data: TunnelIn, request: Request):
    require_admin(request)
    url = data.url.strip().rstrip("/")
    if not url.startswith("http"):
        raise HTTPException(400, "URL должен начинаться с http")
    with db() as con:
        con.execute("INSERT OR REPLACE INTO settings VALUES ('kaggle_url',?)", (url,))
    return {"ok": True, "url": url}

@app.post("/api/admin/tunnel/test")
async def admin_test_tunnel(request: Request):
    require_admin(request)
    with db() as con:
        row = con.execute("SELECT value FROM settings WHERE key='kaggle_url'").fetchone()
    url = row["value"] if row else ""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(url + "/docs",
                                 headers={"bypass-tunnel-reminder": "true"})
            return {"ok": r.status_code < 500, "status": r.status_code, "url": url}
    except Exception as e:
        return {"ok": False, "error": str(e), "url": url}


# ── Static assets ──────────────────────────────────────────────────────────────
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

app.mount("/css", StaticFiles(directory=str(FRONTEND / "css")), name="css")
app.mount("/js",  StaticFiles(directory=str(FRONTEND / "js")),  name="js")
app.mount("/img", StaticFiles(directory=str(FRONTEND / "img")), name="img")

# ── Clean URL routes ────────────────────────────────────────────────────────────
@app.get("/")
@app.get("/login")
async def serve_login():
    return FileResponse(str(FRONTEND / "login.html"))

@app.get("/chat")
async def serve_chat():
    return FileResponse(str(FRONTEND / "chat.html"))

@app.get("/dashboard")
async def serve_dashboard():
    return FileResponse(str(FRONTEND / "dashboard.html"))

# #
