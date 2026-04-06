import discord
import json
import os
from datetime import datetime
from flask import Flask
from threading import Thread

# 如果您有 account.py，請保留這行；如果沒有，請註解掉
# from account import add_transaction, calculate_balance, settle_debts

# 從 Render 環境變數讀取 TOKEN
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
# Flask 保活伺服器 (解決 Render Port 偵測問題)
# =========================
app = Flask('')

@app.route('/')
def home():
    return "Bot is alive!"

def run_flask():
    # 讀取 Render 分配的 PORT，預設為 10000
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run_flask)
    t.start()

# 啟動 Flask 伺服器
keep_alive()

# =========================
# 資料處理工具
# =========================
def load_data():
    if not os.path.exists(FILE):
        return {"transactions": [], "next_id": 1}
    try:
        with open(FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {"transactions": [], "next_id": 1}

def save_data(data):
    with open(FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

# =========================
# Discord 機器人設定
# =========================
intents = discord.Intents.default()
intents.message_content = True 
intents.members = True          

client = discord.Client(intents=intents)

@client.event
async def on_ready():
    print(f"✅ 機器人已上線：{client.user}")

@client.event
async def on_message(message):
    if message.author == client.user:
        return

    content = message.content.strip()

    # !add 指令
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

            if not splits:
                people = [p for p in debt_info if p != "欠"]
                if people:
                    share = round(amount / len(people), 2)
                    for p in people:
                        splits[p] = share

            now = datetime.now().strftime("%Y/%m/%d %H:%M")
            data = load_data()
            new_t = {
                "id": data["next_id"],
                "payer": message.author.name,
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
            await message.channel.send(f"❌ 錯誤: {e}")

    # !list 指令
    elif content.startswith("!list"):
        data = load_data()
        transactions = data.get("transactions", [])
        if not transactions:
            await message.channel.send("📭 沒有任何交易紀錄")
            return
        msg = "📜 **所有交易紀錄：**\n"
        for t in transactions:
            msg += f"\n🔹 ID:{t['id']} │ {t.get('time','')} │ {t.get('desc','')}\n👤 {t.get('payer','')} 付款\n"
            for name, amt in t.get("splits", {}).items():
                if name != t.get('payer',''):
                    msg += f"   └─ {name} 欠 {amt}\n"
        await message.channel.send(msg)

    # !delete 指令
    elif content.startswith("!delete"):
        try:
            delete_id = int(content.split()[1])
            data = load_data()
            old_len = len(data["transactions"])
            data["transactions"] = [t for t in data["transactions"] if t["id"] != delete_id]
            if len(data["transactions"]) == old_len:
                await message.channel.send("❌ 找不到該 ID")
            else:
                save_data(data)
                await message.channel.send(f"🗑️ 已刪除 ID:{delete_id}")
        except:
            await message.channel.send("❌ 請輸入正確 ID，例如：`!delete 1`")

    # !settle 指令
    elif content.startswith("!settle"):
        data = load_data()
        transactions = data.get("transactions", [])
        if not transactions:
            await message.channel.send("🎉 目前沒有任何紀錄喔！")
            return
        msg = "💰 **目前的債務關係：**\n"
        for t in transactions:
            header = f"\n**{t.get('time','')}** │ **{t.get('desc','')}**\n"
            lines = "".join([f"└─ {n} 欠 {a} → {t['payer']}\n" for n, a in t.get("splits",{}).items() if str(n) != str(t['payer'])])
            if lines: msg += header + lines
        await message.channel.send(msg)

# 啟動機器人
<<<<<<< HEAD
if TOKEN:
    client.run(TOKEN)
else:
    print("❌ 錯誤：找不到 DISCORD_TOKEN 環境變數")
=======
client.run(TOKEN)
>>>>>>> 21c6152cba7b4d9b1beeb3e208e9db2795de5335
