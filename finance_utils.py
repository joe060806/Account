import os
import json

# 新增交易並打包成標準格式
def add_transaction(transactions, next_id, payer, amount, splits, desc, time_str):
    new_t = {
        "id": next_id,
        "payer": payer,
        "amount": amount,
        "splits": splits,
        "desc": desc,
        "time": time_str
    }
    transactions.append(new_t)
    return new_t

# 核心演算法：將多筆分散交易進行矩陣歸併，計算出群組內「最精簡」的權責轉帳解法
def calculate_consolidated_debts(transactions):
    consolidated = {}
    for t in transactions:
        payer = t.get('payer')
        for debtor, amt in t.get("splits", {}).items():
            if str(debtor) != str(payer):
                # 建立一對一雙向通道，確保 (A, B) 和 (B, A) 能抵銷
                key = (str(debtor), str(payer))
                consolidated[key] = consolidated.get(key, 0.0) + float(amt)
    return consolidated