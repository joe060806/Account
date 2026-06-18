import discord
import json
import os
from datetime import datetime, timedelta, timezone
from flask import Flask
from threading import Thread
from discord.ui import Button, View, Modal, TextInput

# 引入自訂的核心演算法庫
from finance_utils import add_transaction, calculate_consolidated_debts

# =========================
# 基本設定與 Flask 保活 (Render 部署必備)
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
# 資料庫安全防護與讀寫
# =========================
def load_data():
    if not os.path.exists(FILE): 
        return {"transactions": [], "next_id": 1, "user_payments": {}}
    try:
        with open(FILE, "r", encoding="utf-8") as f:
            d = json.load(f)
            if "user_payments" not in d: d["user_payments"] = {}
            if "transactions" not in d: d["transactions"] = []
            return d
    except: 
        return {"transactions": [], "next_id": 1, "user_payments": {}}

def save_data(data):
    with open(FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

# =========================
# LINE Pay 轉帳動態按鈕
# =========================
class SettleLinkView(View):
    def __init__(self, debtor_name, payer_name, amount, link):
        super().__init__(timeout=60)
        self.add_item(Button(
            label=f"📱 點我轉帳 {amount} 元給 {payer_name}", 
            url=link, 
            style=discord.ButtonStyle.link
        ))

# =========================
# UI 控制層 - 新增帳目視窗
# =========================
class AddRecordModal(Modal, title="➕ 建立新帳目（支援智慧均分）"):
    amount = TextInput(label="💰 消費總金額", placeholder="例如: 600", min_length=1, max_length=10)
    desc = TextInput(label="🏷️ 品項或活動描述", placeholder="例如: 麥當勞晚餐...", min_length=1, max_length=50)
    debt = TextInput(
        label="👥 債務人與金額分配 (留空則不計債務)", 
        placeholder="智慧均分：李 呂 偉 (自動平分)\n傳統自訂：李欠200 呂欠150", 
        style=discord.TextStyle.paragraph, required=False, max_length=200
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            clean_amount_str = self.amount.value.replace("$", "").replace(",", "").strip()
            amt_val = float(clean_amount_str)
            if amt_val <= 0:
                await interaction.response.send_message("❌ 金額必須大於 0 元！", ephemeral=True)
                return

            desc_val = self.desc.value.strip()
            raw_debt_info = self.debt.value.strip()
            splits = {}
            
            if raw_debt_info:
                tokens = raw_debt_info.split()
                is_pure_split_mode = all("欠" not in token for token in tokens)
                
                if is_pure_split_mode:
                    share = round(amt_val / len(tokens), 1)
                    for person in tokens:
                        splits[person] = share
                else:
                    current_name = None
                    for item in tokens:
                        if "欠" in item:
                            if item.startswith("欠"):
                                money_str = item.replace("欠", "")
                                if current_name: splits[current_name] = float(money_str)
                            else:
                                name, money_str = item.split("欠")
                                splits[name] = float(money_str)
                        else:
                            current_name = item

            tw_tz = timezone(timedelta(hours=8))
            now = datetime.now(tw_tz).strftime("%Y/%m/%d %H:%M")
            
            data = load_data()
            add_transaction(data["transactions"], data["next_id"], interaction.user.name, amt_val, splits, desc_val, now)
            data["next_id"] += 1
            save_data(data)
            
            confirm_msg = f"✅ **成功記帳！**\n" + "─" * 15 + f"\n📝 **品項**：{desc_val}\n👤 **付款人**：`{interaction.user.name}` │ 💰 **總金額**：{amt_val} 元\n"
            if splits:
                confirm_msg += "👥 **債務分配結果**：\n"
                for name, amt in splits.items(): confirm_msg += f" └─ {name} 應分擔 `{amt}` 元\n"
            else:
                confirm_msg += "✨ *(此筆交易為個人消費，未產生群組債務)*\n"
                
            await interaction.response.send_message(confirm_msg, ephemeral=False)
        except ValueError:
            await interaction.response.send_message("❌ **格式錯誤**：請確保金額輸入的是有效數字！", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ **系統異常**：無法處理此記帳請求 ({e})", ephemeral=True)

# =========================
# UI 控制層 - 兩階段刪除確認
# =========================
class DeleteConfirmView(View):
    def __init__(self, target_id, t_desc, t_amount, t_payer, original_user):
        super().__init__(timeout=45)
        self.target_id = target_id
        self.t_desc = t_desc
        self.t_amount = t_amount
        self.t_payer = t_payer
        self.original_user = original_user

    @discord.ui.button(label="🔴 確定刪除，無法復原", style=discord.ButtonStyle.danger)
    async def confirm_delete(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != self.original_user.id:
            await interaction.response.send_message("❌ 你不是發起操作的人！", ephemeral=True)
            return
        try:
            data = load_data()
            old_len = len(data["transactions"])
            data["transactions"] = [t for t in data["transactions"] if t["id"] != self.target_id]
            
            if len(data["transactions"]) == old_len:
                await interaction.response.edit_message(content="❌ 刪除失敗：該帳目不存在。", view=None)
            else:
                save_data(data)
                await interaction.response.edit_message(
                    content=f"🗑️ **帳目已成功刪除！**\n📌 刪除項：ID:{self.target_id} │ {self.t_desc} ({self.t_amount}元)", view=None
                )
        except Exception as e:
            await interaction.response.send_message(f"❌ 系統異常: {e}", ephemeral=True)

    @discord.ui.button(label="🟢 取消操作", style=discord.ButtonStyle.success)
    async def cancel_delete(self, interaction: discord.Interaction, button: Button):
        if interaction.user.id != self.original_user.id: return
        await interaction.response.edit_message(content="🔄 已取消刪除操作。", view=None)

class DeleteRecordModal(Modal, title="🗑️ 安全刪除帳目紀錄"):
    id_to_del = TextInput(label="📌 請輸入要刪除的交易 ID", placeholder="例如: 1", min_length=1, max_length=5)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            clean_id_str = self.id_to_del.value.strip()
            if not clean_id_str.isdigit():
                await interaction.response.send_message("❌ ID 必須為純數字！", ephemeral=True)
                return
                
            target_id = int(clean_id_str)
            data = load_data()
            target_transaction = next((t for t in data.get("transactions", []) if t["id"] == target_id), None)
            
            if not target_transaction:
                await interaction.response.send_message(f"🔍 找不到 ID 為 `{target_id}` 的帳目！", ephemeral=True)
                return
                
            warning_content = f"""⚠️ **【安全刪除確認】您正在嘗試刪除以下帳目紀錄：**
────────────────────
🔹 **帳目 ID**：`{target_id}`
🕒 **記帳時間**：{target_transaction.get("time", "")}
🏷️ **品項描述**：*{target_transaction.get("desc", "")}*
👤 **原付款人**：`{target_transaction.get("payer", "")}` │ 💰 **總金額**：`{target_transaction.get("amount", 0)}` 元
────────────────────
🚨 **警告**：刪除後將重新計算財務債務，請確認是否繼續？"""
            
            await interaction.response.send_message(
                content=warning_content, 
                view=DeleteConfirmView(target_id, target_transaction.get("desc"), target_transaction.get("amount"), target_transaction.get("payer"), interaction.user), 
                ephemeral=True
            )
        except Exception as e:
            await interaction.response.send_message(f"❌ 刪除模組異常: {e}", ephemeral=True)

# =========================
# UI 控制層 - 主選單大廳
# =========================
class MainMenuView(View):
    def __init__(self): super().__init__(timeout=None)

    @discord.ui.button(label="➕ 新增帳目", style=discord.ButtonStyle.green)
    async def add_btn(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_modal(AddRecordModal())

    @discord.ui.button(label="📜 查看清單", style=discord.ButtonStyle.blurple)
    async def list_btn(self, interaction: discord.Interaction, button: Button):
        data = load_data()
        ts = data.get("transactions", [])
        if not ts:
            await interaction.response.send_message("📭 目前沒有任何記帳紀錄", ephemeral=True)
            return

        tw_tz = timezone(timedelta(hours=8))
        now = datetime.now(tw_tz)
        
        def get_relative_time(time_str):
            try:
                t_time = datetime.strptime(time_str, "%Y/%m/%d %H:%M").replace(tzinfo=tw_tz)
                diff = now - t_time
                if diff.days == 0:
                    if diff.seconds < 60: return "剛剛"
                    if diff.seconds < 3600: return f"{diff.seconds // 60} 分鐘前"
                    return f"{diff.seconds // 3600} 小時前"
                elif diff.days == 1: return "昨天"
                else: return f"{diff.days} 天前"
            except: return ""

        week_count, week_total = 0, 0.0
        one_week_ago = now - timedelta(days=7)
        for t in ts:
            try:
                t_time = datetime.strptime(t['time'], "%Y/%m/%d %H:%M").replace(tzinfo=tw_tz)
                if t_time >= one_week_ago:
                    week_count += 1
                    week_total += float(t['amount'])
            except: pass

        msg = f"📊 **【時間維度摘要】**\n📅 過去 7 天內累計記帳：`{week_count}` 筆 │ 總金額：`{round(week_total, 1)}` 元\n" + "────────────────────\n📜 **最新交易清單 (僅顯示最新 5 筆)：**\n"
        for t in list(reversed(ts))[:5]:
            rel_time = get_relative_time(t['time'])
            msg += f"\n🔹 **ID:{t['id']}** │ 🕒 {t['time']} *({rel_time})* │ 🏷️ **{t['desc']}**\n👤 Payer: `{t['payer']}` (付 {t['amount']} 元)\n"
            for name, amt in t.get("splits", {}).items():
                if str(name) != str(t['payer']): msg += f"   └─ 👤 {name} 欠 {amt} 元\n"
                    
        await interaction.response.send_message(msg, ephemeral=True)

    @discord.ui.button(label="💰 結算債務", style=discord.ButtonStyle.grey)
    async def settle_btn(self, interaction: discord.Interaction, button: Button):
        try:
            data = load_data()
            ts = data.get("transactions", [])
            payments = data.get("user_payments", {})
            if not ts:
                await interaction.response.send_message("🎉 目前清空狀態，沒有任何記帳紀錄！", ephemeral=True)
                return
            
            # 🔥 呼叫重構後的函式庫，進行高效債務矩陣計算
            consolidated_debts = calculate_consolidated_debts(ts)
            debt_outputs = []
            
            for (debtor, payer), total_amt in consolidated_debts.items():
                total_amt = round(total_amt, 2)
                if total_amt <= 0: continue
                    
                payer_link = payments.get(payer)
                content = f"👤 **{debtor}** 總共欠 **{payer}** 💰 **{total_amt}元**"
                view = SettleLinkView(debtor, payer, total_amt, payer_link) if payer_link else None
                if not payer_link: content += "\n*(⚠️ 債權人未綁定 LINE Pay 轉帳連結)*"
                debt_outputs.append((content, view))
            
            if not debt_outputs:
                await interaction.response.send_message("🎉 目前所有債務已兩清！", ephemeral=True)
                return
                
            first_content, first_view = debt_outputs[0]
            await interaction.response.send_message(f"💰 **【精簡合併結算】當前債務關係：**\n\n{first_content}", view=first_view, ephemeral=True)
            
            for content, view in debt_outputs[1:]:
                await interaction.followup.send(content, view=view, ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ 結算發生錯誤: {e}", ephemeral=True)

    @discord.ui.button(label="🗑️ 刪除紀錄", style=discord.ButtonStyle.red)
    async def del_btn(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_modal(DeleteRecordModal())

# =========================
# 啟動事件
# =========================
intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

@client.event
async def on_ready(): print(f"✅ 機器人已就緒：{client.user}")

@client.event
async def on_message(message):
    if message.author == client.user: return
    if message.content == "!menu":
        await message.channel.send("🏮 **記帳助手主選單**\n點擊下方按鈕進行操作：", view=MainMenuView())
        
    if message.content.startswith("!setpay "):
        link = next((w for w in message.content.replace("!setpay ", "").split() if "line.me/" in w), None)
        if not link:
            await message.channel.send("❌ 格式不正確！必須包含 line.me/ 轉帳連結。")
            return
        data = load_data()
        data["user_payments"][message.author.name] = link
        save_data(data)
        await message.channel.send(f"✅ 成功為 **{message.author.name}** 綁定 LINE Pay 連結！")

if TOKEN: client.run(TOKEN)