from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import json
import os

from account import add_transaction, calculate_balance, settle_debts

app = FastAPI()

# CORS（前端要用）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

FILE = "data.json"

# =========================
# 資料模型
# =========================
class Transaction(BaseModel):
    payer: str
    amount: float
    splits: dict
    desc: str


# =========================
# 資料處理
# =========================
def load_data():
    if not os.path.exists(FILE):
        return {"transactions": [], "next_id": 1}
    with open(FILE, "r") as f:
        return json.load(f)


def save_data(data):
    with open(FILE, "w") as f:
        json.dump(data, f, indent=4)


# =========================
# API
# =========================

@app.get("/")
def root():
    return {"message": "API running"}


@app.get("/transactions")
def get_transactions():
    data = load_data()
    return data["transactions"]


@app.post("/transactions")
def create_transaction(t: Transaction):
    data = load_data()

    new_t = add_transaction(
        data["transactions"],
        data["next_id"],
        t.payer,
        t.amount,
        t.splits,
        t.desc
    )

    data["next_id"] += 1
    save_data(data)

    return new_t


@app.get("/settle")
def settle():
    data = load_data()

    balance = calculate_balance(data["transactions"])
    result = settle_debts(balance)

    return result