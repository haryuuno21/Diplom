from fastapi import FastAPI, Depends, HTTPException, status, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
import logging

from database import init_db, init_redis, SESSION_EXPIRE_SECONDS
from auth import AuthService
from schemas import UserCreate, UserLogin, TokenResponse

# Настройка логгирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Глобальные переменные для сервисов
auth_service = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Инициализация при запуске и очистка при завершении"""
    global auth_service
    
    # Инициализация базы данных и Redis
    db_pool = await init_db()
    redis_client = await init_redis()
    
    auth_service = AuthService(db_pool, redis_client)
    
    logger.info("Auth service initialized")
    
    yield
    
    # Очистка при завершении
    await db_pool.close()
    await redis_client.close()
    logger.info("Auth service shutdown")

app = FastAPI(lifespan=lifespan, title="Auth Server")

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3010"],  # ваш game-сервер
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.post("/api/register", response_model=TokenResponse)
async def register(user: UserCreate):
    """Регистрация нового пользователя"""
    if not user.username or not user.password:
        raise HTTPException(status_code=400, detail="Username and password are required")
    
    if len(user.username) < 3:
        raise HTTPException(status_code=400, detail="Username must be at least 3 characters")
    
    if len(user.password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
    
    success = await auth_service.create_user(user.username, user.password)
    if not success:
        raise HTTPException(status_code=400, detail="User already exists")
    
    return {"message": "User created successfully"}

@app.post("/api/login", response_model=TokenResponse)
async def login(response: Response, user: UserLogin):
    """Вход пользователя"""
    authenticated_user = await auth_service.authenticate_user(user.username, user.password)
    if not authenticated_user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    # Создание сессии
    session_id = await auth_service.create_session(authenticated_user.id, authenticated_user.username)
    
    # Установка HttpOnly cookie
    response.set_cookie(
        key="session_id",
        value=session_id,
        httponly=True,
        secure=False,  # В продакшене установите True
        samesite="lax",
        max_age=SESSION_EXPIRE_SECONDS
    )
    
    return {"message": "Login successful"}

@app.post("/api/logout", response_model=TokenResponse)
async def logout(request: Request, response: Response):
    """Выход пользователя"""
    session_id = request.cookies.get("session_id")
    if session_id:
        await auth_service.delete_session(session_id)
    
    response.delete_cookie("session_id")
    return {"message": "Logged out successfully"}

@app.get("/api/health")
async def health_check():
    """Проверка работоспособности"""
    return {"status": "healthy"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)