from fastapi import FastAPI
from app.routers.chatbot import router as chatbot_router
from app.routers.auth import router as auth_router
# from app.routers.supplier import router as supplier_router
from app.routers.inventory_dropdown import router as inventory_router
# from app.routers.supplier_search import router as supplier_search_router
from app.routers.inventory_smart import router as inventory_smart_router

app = FastAPI()

app.include_router(chatbot_router)
app.include_router(auth_router)
# app.include_router(supplier_router)
app.include_router(inventory_router)
# app.include_router(supplier_search_router)
app.include_router(inventory_smart_router)

@app.get("/")
def root():
    return {"message": "Mewar ERP API running"}

# @app.get("/che     ck-db")
# def check_db(db: Session = Depends(get_db)):
#     result = db.execute(text("SHOW TABLES;"))
#     tables = result.fetchall()
#     return [row[0] for row in tables]

# @app.get("/inventory")
# def get_inventory(db: Session = Depends(get_db)):
#     result = db.execute(text("SELECT * FROM inventories;"))
#     rows = result.fetchall()
#     return {
#         "table": "inventories",
#         "count": len(rows),
#         "data": [dict(row._mapping) for row in rows]
#     }