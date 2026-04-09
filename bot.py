import discord
import json
import os
from datetime import datetime, timedelta, timezone
from flask import Flask
from threading import Thread
from discord.ui import Button, View, Modal, TextInput

# =========================
# 基本設定與 Flask 保活
# =========================
TOKEN = os.getenv("DISCORD_TOKEN")
FILE = "data.json"

app = Flask('')
@app.route('/')
def home(): return "Bot is alive!"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    Thread(target=run_flask).start()

keep_alive()

# =========================
# 資料處理
# =========================
def load_data():
    if not os.path.exists(FILE): return {"transactions": [], "next_id": 1}
    try:
        with open(FILE, "r", encoding="utf-8") as f: return json.load(f)
    except: return {"transactions": [], "next_id": 1}

def save_data(data):
    with open(FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

# =========================
# 全自動彈出視窗 (Modals)
# =========================

# 新增帳目的視窗
class AddRecordModal(Modal, title="新增帳目紀錄"):
    amount = TextInput(label="金額", placeholder="例如: 200", min_length=1)
    desc = TextInput(label="品項描述", placeholder="例如: 晚餐", min_length=1)
    debt = TextInput(label="債務分配", placeholder="例如: joe欠100 (多位請空白隔開)", style=discord.TextStyle.paragraph)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            amt_val = float(self.amount.value)
            desc_val = self.desc.value
            debt_info = self.debt.value.split()
            
            splits = {}
            current_name = None
            for item in debt_info:
                if "欠" in item:
                    if item.startswith("欠"):
                        money_str = item.replace("欠", "")
                        if current_name: splits[current_name] = float(money_str)
                    else:
                        name, money_str = item.split("欠")
                        splits[name] = float(money_str)
                else:
                    current_name = item
            
            if not splits and debt_info:
                share = round(amt_val / len(debt_info), 2)
                for p in debt_info: splits[p] = share

            tw_tz = timezone(timedelta(hours=8))
            now = datetime.now(tw_tz).strftime("%Y/%m/%d %H:%M")
            data = load_data()
            new_t = {
                "id": data["next_id"],
                "payer": interaction.user.name,
                "amount": amt_val,
                "splits": splits,
                "desc": desc_val,
                "time": now
            }
            data["transactions"].append(new_t)
            data["next_id"] += 1
            save_data(data)
            await interaction.response.send_message(f"✅ 已記下「{desc_val}」！", ephemeral=False)
        except Exception as e:
            await interaction.response.send_message(f"❌ 格式錯誤: {e}", ephemeral=True)

# 刪除紀錄的視窗
class DeleteRecordModal(Modal, title="刪除帳目"):
    id_to_del = TextInput(label="要刪除的 ID", placeholder="請輸入數字 ID")

    async def on_submit(self, interaction: discord.Interaction):
        try:
            target_id = int(self.id_to_del.value)
            data = load_data()
            old_len = len(data["transactions"])
            data["transactions"] = [t for t in data["transactions"] if t["id"] != target_id]
            if len(data["transactions"]) == old_len:
                await interaction.response.send_message("❌ 找不到該 ID", ephemeral=True)
            else:
                save_data(data)
                await interaction.response.send_message(f"🗑️ 已刪除 ID:{target_id}", ephemeral=False)
        except:
            await interaction.response.send_message("❌ 請輸入有效的數字 ID", ephemeral=True)

# =========================
# 按鈕選單 (View)
# =========================
class MainMenuView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="➕ 新增帳目", style=discord.ButtonStyle.green)
    async def add_btn(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_modal(AddRecordModal())

    @discord.ui.button(label="📜 查看清單", style=discord.ButtonStyle.blurple)
    async def list_btn(self, interaction: discord.Interaction, button: Button):
        data = load_data()
        ts = data.get("transactions", [])
        if not ts:
            await interaction.response.send_message("📭 目前沒紀錄", ephemeral=True)
            return
        msg = "📜 **所有交易紀錄：**\n"
        for t in ts:
            msg += f"\n🔹 ID:{t['id']} │ {t['time']} │ {t['desc']}\n👤 {t['payer']} 付款\n"
            for name, amt in t.get("splits", {}).items():
                if name != t['payer']: msg += f"   └─ {name} 欠 {amt}\n"
        await interaction.response.send_message(msg, ephemeral=True)

    @discord.ui.button(label="💰 結算債務", style=discord.ButtonStyle.grey)
    async def settle_btn(self, interaction: discord.Interaction, button: Button):
        data = load_data()
        ts = data.get("transactions", [])
        if not ts:
            await interaction.response.send_message("🎉 目前清空狀態！", ephemeral=True)
            return
        msg = "💰 **目前的債務關係：**\n"
        for t in ts:
            lines = "".join([f"└─ {n} 欠 {a} → {t['payer']}\n" for n, a in t.get("splits",{}).items() if str(n) != str(t['payer'])])
            if lines: msg += f"\n**{t['time']}** │ **{t['desc']}**\n" + lines
        await interaction.response.send_message(msg, ephemeral=True)

    @discord.ui.button(label="🗑️ 刪除紀錄", style=discord.ButtonStyle.red)
    async def del_btn(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_modal(DeleteRecordModal())

# =========================
# 機器人啟動與指令
# =========================
intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

@client.event
async def on_ready():
    print(f"✅ 機器人已就緒：{client.user}")

@client.event
async def on_message(message):
    if message.author == client.user: return
    
    # 輸入 !menu 叫出按鈕面板
    if message.content == "!menu":
        await message.channel.send("🏮 **記帳助手主選單**\n點擊下方按鈕進行操作：", view=MainMenuView())

if TOKEN:
    client.run(TOKEN)