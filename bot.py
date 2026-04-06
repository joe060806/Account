import discord
import json
import os
from datetime import datetime
from flask import Flask
from threading import Thread

from account import add_transaction, calculate_balance, settle_debts

TOKEN = os.getenv("DISCORD_TOKEN")

FILE = "data.json"

app = Flask('')

@app.route('/')
def home():
    return "Bot is alive!"

def run():
    # Render 預設使用 10000 埠口
    app.run(host='0.0.0.0', port=10000)

# 啟動一個背景執行緒跑網頁，這樣不會卡住 Discord 機器人
Thread(target=run).start()

# =========================
# 資料處理工具
# =========================
def load_data():
    """讀取 JSON 資料檔"""
    if not os.path.exists(FILE):
        return {"transactions": [], "next_id": 1}
    try:
        with open(FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {"transactions": [], "next_id": 1}

def save_data(data):
    """儲存資料到 JSON 檔"""
    with open(FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

# =========================
# Discord 機器人設定
# =========================
intents = discord.Intents.default()
intents.message_content = True  # 必須在 Developer Portal 開啟對應開關
intents.members = True          # 建議也開啟成員意圖

client = discord.Client(intents=intents)

@client.event
async def on_ready():
    print(f"✅ 機器人已上線：{client.user}")

@client.event
async def on_message(message):
    # 排除機器人自己的訊息
    if message.author == client.user:
        return

    content = message.content.strip()

    # =========================
    # 指令：!add [金額] [描述] [姓名] [欠金額] ...
    # 範例：!add 200 晚餐 joe 欠120
    # =========================
    if content.startswith("!add"):
        try:
            parts = content.split()
            if len(parts) < 4:
                raise ValueError("參數不足")

            amount = float(parts[1])
            desc = parts[2]
            debt_info = parts[3:]

            splits = {}
            current_name = None

            # 解析人名與欠款 (支援 "joe 欠120" 或 "joe欠120")
            for item in debt_info:
                if "欠" in item:
                    if item.startswith("欠"):
                        money_str = item.replace("欠", "")
                        if current_name and money_str:
                            splits[current_name] = float(money_str)
                    else:
                        name, money_str = item.split("欠")
                        splits[name] = float(money_str)
                else:
                    current_name = item

            # 如果沒寫「欠」，則視為所有提到的人平分
            if not splits:
                people = [p for p in debt_info if p != "欠"]
                if people:
                    share = round(amount / len(people), 2)
                    for p in people:
                        splits[p] = share

            # 取得目前時間
            now = datetime.now().strftime("%Y/%m/%d %H:%M")

            data = load_data()
            new_t = {
                "id": data["next_id"],
                "payer": message.author.name, # 儲存發送者的純文字名字
                "amount": amount,
                "splits": splits,
                "desc": desc,
                "time": now
            }

            data["transactions"].append(new_t)
            data["next_id"] += 1
            save_data(data)

            await message.channel.send(f"✅ 已幫 **{message.author.name}** 記下「{desc}」！")

        except Exception as e:
            print(f"新增錯誤: {e}")
            await message.channel.send("❌ 格式錯誤！範例：`!add 200 晚餐 joe 欠120` 或 `!add 200 晚餐 joe bob` (平分)")

    # =========================
    # 指令：!list（列出所有交易）
    # =========================
    elif content.startswith("!list"):
        data = load_data()
        transactions = data.get("transactions", [])

        if not transactions:
            await message.channel.send("📭 沒有任何交易紀錄")
            return

        msg = "📜 **所有交易紀錄：**\n"

        for t in transactions:
            tid = t["id"]
            time_val = t.get("time", "")
            desc_val = t.get("desc", "")
            payer_val = t.get("payer", "")
            splits_val = t.get("splits", {})

            msg += f"\n🔹 ID:{tid} │ {time_val} │ {desc_val}\n"
            msg += f"👤 {payer_val} 付款\n"

            for name, amt in splits_val.items():
                if name != payer_val:
                    msg += f"   └─ {name} 欠 {amt}\n"

        await message.channel.send(msg)

    # =========================
    # 指令：!delete [ID]
    # =========================
    elif content.startswith("!delete"):
        try:
            parts = content.split()
            if len(parts) != 2:
                raise ValueError("格式錯誤")

            delete_id = int(parts[1])

            data = load_data()
            transactions = data.get("transactions", [])

            new_transactions = [t for t in transactions if t["id"] != delete_id]

            if len(new_transactions) == len(transactions):
                await message.channel.send("❌ 找不到這筆交易 ID")
                return

            data["transactions"] = new_transactions
            save_data(data)

            await message.channel.send(f"🗑️ 已刪除 ID:{delete_id}")

        except:
            await message.channel.send("❌ 格式錯誤：!delete 1")

    # =========================
    # 指令：!settle (查看所有債務關係)
    # =========================
    elif content.startswith("!settle"):
        data = load_data()
        transactions = data.get("transactions", [])

        if not transactions:
            await message.channel.send("🎉 目前沒有任何記帳紀錄喔！")
            return

        msg = "💰 **目前的債務關係：**\n"
        
        for t in transactions:
            time_val = t.get("time", "未知時間")
            desc_val = t.get("desc", "無描述")
            payer_val = t.get("payer", "未知付款人")
            splits_val = t.get("splits", {})

            # 組合單筆交易的標頭
            transaction_header = f"\n **{time_val}** │ **{desc_val}**\n"
            debt_lines = ""

            for name, amt in splits_val.items():
                # 只有當欠錢的人不是付款人時才顯示
                if str(name) != str(payer_val):
                    debt_lines += f"└─ {name} 欠 {amt} → {payer_val}\n"
            
            # 如果這筆交易真的有債務產生，才加入總訊息
            if debt_lines:
                msg += transaction_header + debt_lines

        # 若訊息太長可能會被 Discord 截斷，這裡一次發送
        await message.channel.send(msg)

# 啟動機器人
client.run(TOKEN)
