# import os
# import urllib.parse
# from dotenv import load_dotenv
# from sqlalchemy import create_engine
# from sqlalchemy.orm import sessionmaker

# # 1. Load environment variables from .env (for local) or Vercel Settings (for live)
# load_dotenv()

# DATABASE_URL = os.getenv("DATABASE_URL")

# # 2. Setup the Remote Connection if DATABASE_URL is missing in .env
# if not DATABASE_URL:
    
#     user = "u512872665_user"
#     password = urllib.parse.quote_plus("a3nQyY7RT;G9")  # Encodes special characters
#     host = "auth-db1830.hstgr.io"
#     port = "3306"
#     dbname = "u512872665_db"
    
#     DATABASE_URL = f"mysql+pymysql://{user}:{password}@{host}:{port}/{dbname}"

# # 3. Create the engine with 'pool_pre_ping'
# # This is critical for remote databases to prevent "MySQL server has gone away" errors
# engine = create_engine(
#     DATABASE_URL, 
#     echo=True,
#     pool_pre_ping=True,
#     pool_recycle=3600
# )

# SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# # 4. Dependency to get DB session
# def get_db():
#     db = SessionLocal()
#     try:
#         yield db
#     finally:
#         db.close()







# import os
# from dotenv import load_dotenv
# from sqlalchemy import create_engine
# from sqlalchemy.orm import sessionmaker

# load_dotenv()

# DATABASE_URL = os.getenv("DATABASE_URL")

# if not DATABASE_URL:
#     DATABASE_URL = "mysql+pymysql://root:@127.0.0.1:3306/mewar"

# engine = create_engine(DATABASE_URL, echo=True)

# SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# def get_db():
#     db = SessionLocal()
#     try:
#         yield db
#     finally:
#         db.close()



# import urllib.parse
# from sqlalchemy import create_engine
# from sqlalchemy.orm import sessionmaker

# password = urllib.parse.quote_plus("a3nQyY7RT;G9")

# DATABASE_URL = f"mysql+pymysql://u512872665_user:{password}@127.0.0.1:3306/u512872665_db"

# engine = create_engine(DATABASE_URL, echo=True)

# SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# def get_db():
#     db = SessionLocal()
#     try:
#         yield db
#     finally:
#         db.close()



# import os
# import socket
# import urllib.parse
# import traceback
# from dotenv import load_dotenv

# from sqlalchemy import create_engine, text
# from sqlalchemy.orm import sessionmaker
# from sqlalchemy.exc import OperationalError, SQLAlchemyError

# # ------------------------------------------------------------
# # Load env
# # ------------------------------------------------------------
# load_dotenv()

# def build_database_url() -> str:
#     """
#     Priority:
#     1) DATABASE_URL from env
#     2) Fallback hardcoded (edit only here)
#     """
#     db_url = os.getenv("DATABASE_URL")
#     if db_url and db_url.strip():
#         return db_url.strip()

#     user = "u512872665_mewar_erp"
#     raw_password = "a3nQyY7RT;G9"
#     password = urllib.parse.quote_plus(raw_password)  # encode special chars like ;, @, etc.

#     host = "auth-db1830.hstgr.io"
#     port = "3306"
#     dbname = "u512872665_mewar_erp"

#     return f"mysql+pymysql://{user}:{password}@{host}:{port}/{dbname}?charset=utf8mb4"


# DATABASE_URL = build_database_url()

# # ------------------------------------------------------------
# # Helpful debug: parse host/port from URL + DNS test
# # ------------------------------------------------------------
# def _extract_host_port(url: str) -> tuple[str | None, int | None]:
#     try:
#         parsed = urllib.parse.urlparse(url)
#         return parsed.hostname, (parsed.port or 3306)
#     except Exception:
#         return None, None


# def debug_dns(host: str, port: int) -> None:
#     """
#     Prints DNS resolution info so you can instantly see
#     'getaddrinfo failed' root cause.
#     """
#     try:
#         infos = socket.getaddrinfo(host, port, 0, socket.SOCK_STREAM)
#         ips = sorted({info[4][0] for info in infos})
#         print(f"[DB][DNS] OK: {host}:{port} -> {', '.join(ips)}")
#     except Exception as e:
#         print(f"[DB][DNS] FAIL: {host}:{port} -> {repr(e)}")


# _db_host, _db_port = _extract_host_port(DATABASE_URL)
# if _db_host:
#     debug_dns(_db_host, _db_port or 3306)

# # ------------------------------------------------------------
# # Engine (Hostinger remote MySQL often needs SSL)
# # ------------------------------------------------------------
# ENGINE_CONNECT_ARGS = {
#     # Safe default for many managed hosts
#     "ssl": {"check_hostname": False}
# }

# # If SSL causes issues on your host, comment above and try:
# # ENGINE_CONNECT_ARGS = {}

# engine = create_engine(
#     DATABASE_URL,
#     echo=False,                 # set True if you want SQL logs
#     pool_pre_ping=True,
#     pool_recycle=3600,
#     pool_size=5,
#     max_overflow=10,
#     connect_args=ENGINE_CONNECT_ARGS,
# )

# SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# # ------------------------------------------------------------
# # Connection test (optional but super useful on startup)
# # ------------------------------------------------------------
# def test_db_connection() -> None:
#     try:
#         with engine.connect() as conn:
#             conn.execute(text("SELECT 1"))
#         print("[DB] Connection test: SUCCESS ✅")
#     except OperationalError as e:
#         print("[DB] Connection test: FAILED ❌ (OperationalError)")
#         print("---- Details ----")
#         print(str(e))
#         print("---- Traceback ----")
#         print(traceback.format_exc())
#         raise
#     except SQLAlchemyError as e:
#         print("[DB] Connection test: FAILED ❌ (SQLAlchemyError)")
#         print("---- Details ----")
#         print(str(e))
#         print("---- Traceback ----")
#         print(traceback.format_exc())
#         raise
#     except Exception as e:
#         print("[DB] Connection test: FAILED ❌ (Unknown Exception)")
#         print("---- Details ----")
#         print(repr(e))
#         print("---- Traceback ----")
#         print(traceback.format_exc())
#         raise


# # Uncomment to test immediately when app starts:
# # test_db_connection()

# # ------------------------------------------------------------
# # FastAPI dependency
# # ------------------------------------------------------------
# def get_db():
#     db = SessionLocal()
#     try:
#         yield db
#     except OperationalError as e:
#         print("[DB] OperationalError during request ❌")
#         print("---- Details ----")
#         print(str(e))
#         print("---- Traceback ----")
#         print(traceback.format_exc())
#         raise
#     except SQLAlchemyError as e:
#         print("[DB] SQLAlchemyError during request ❌")
#         print("---- Details ----")
#         print(str(e))
#         print("---- Traceback ----")
#         print(traceback.format_exc())
#         raise
#     except Exception as e:
#         print("[DB] Unknown error during request ❌")
#         print("---- Details ----")
#         print(repr(e))
#         print("---- Traceback ----")
#         print(traceback.format_exc())
#         raise
#     finally:
#         db.close()


import os
import urllib.parse
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# 1. Load environment variables from .env (for local) or Vercel Settings (for live)
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

# 2. Setup the Remote Connection if DATABASE_URL is missing in .env
if not DATABASE_URL:
    user = "u512872665_user"
    # Adding the @23607 to the end of the password!
    password = urllib.parse.quote_plus("a3nQyY7RT;G9")
    host = "auth-db1830.hstgr.io"         
    port = "3306"
    # Using the database name from the senior's screenshot
    dbname = "u512872665_db"         
    
    DATABASE_URL = f"mysql+pymysql://{user}:{password}@{host}:{port}/{dbname}"

# 3. Create the engine with connection stability settings for remote hosts
engine = create_engine(
    DATABASE_URL, 
    echo=False,           # Live will be noisy with echo=True, so set False. Set True locally if you want SQL logs.
    pool_pre_ping=True, 
    pool_recycle=280,      # 👈 for Hostinger 280`  
    pool_size=5,           # Default connections limit
    max_overflow=10        # Load badhne par extra connections
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# 4. Dependency to get DB session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()