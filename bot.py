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
# 資料處理 (升級防呆機制)
# =========================
def load_data():
    if not os.path.exists(FILE): return {"transactions": [], "next_id": 1, "user_payments": {}}
    try:
        with open(FILE, "r", encoding="utf-8") as f:
            d = json.load(f)
            # 核心向下相容防呆：若舊資料沒這兩個 Key，自動補上，防止 KeyError 崩潰
            if "user_payments" not in d: d["user_payments"] = {}
            if "transactions" not in d: d["transactions"] = []
            return d
    except: 
        return {"transactions": [], "next_id": 1, "user_payments": {}}

def save_data(data):
    with open(FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

# =========================
# 動態產生結算按鈕的 View
# =========================
class SettleLinkView(View):
    def __init__(self, debtor_name, payer_name, amount, link):
        super().__init__(timeout=60)
        # 建立一個 URL 按鈕，點擊後會直接開啟網頁/喚醒 App
        self.add_item(Button(
            label=f"📱 點我轉帳 {amount} 元給 {payer_name}", 
            url=link, 
            style=discord.ButtonStyle.link
        ))

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
        try:
            data = load_data()
            ts = data.get("transactions", [])
            payments = data.get("user_payments", {})
            
            if not ts:
                await interaction.response.send_message("🎉 目前清空狀態，沒有任何記帳紀錄！", ephemeral=True)
                return
            
            # ==========================================
            # 核心演算法：合併同債務人與債權人的所有金額
            # ==========================================
            # 結構會長這樣：{(debtor, payer): total_amount}
            consolidated_debts = {}
            
            for t in ts:
                payer = t['payer']
                for debtor, amt in t.get("splits", {}).items():
                    if str(debtor) != str(payer):
                        # 建立唯一的 (欠錢人, 收錢人) 鑰匙
                        key = (str(debtor), str(payer))
                        # 如果已經存在，就累加金額；不存在就給初始值
                        consolidated_debts[key] = consolidated_debts.get(key, 0.0) + float(amt)
            
            # ==========================================
            # UI 渲染：發送合併後的結果
            # ==========================================
            debt_outputs = []
            
            for (debtor, payer), total_amt in consolidated_debts.items():
                # 四捨五入到小數點後第一位或整數（依據你的顯示習慣，這裡維持四捨五入）
                total_amt = round(total_amt, 2)
                
                # 跳過金額為 0 的無效債務
                if total_amt <= 0:
                    continue
                    
                payer_link = payments.get(payer)
                content = f"👤 **{debtor}** 總共欠 **{payer}** 💰 **{total_amt}元**"
                
                if payer_link:
                    # 這裡會帶入合併後的總金額總數！
                    view = SettleLinkView(debtor_name=debtor, payer_name=payer, amount=total_amt, link=payer_link)
                    debt_outputs.append((content, view))
                else:
                    content += "\n*(⚠️ 債權人未綁定 LINE Pay 轉帳連結，無法顯示按鈕)*"
                    debt_outputs.append((content, None))
            
            # 檢查最後有沒有實質債務
            if not debt_outputs:
                await interaction.response.send_message("🎉 目前所有債務已兩清，沒有產生實質債務關係！", ephemeral=True)
                return
                
            # 第一筆用 response 發送
            first_content, first_view = debt_outputs[0]
            if first_view:
                await interaction.response.send_message(f"💰 **【合併結算】目前的總債務關係：**\n\n{first_content}", view=first_view, ephemeral=True)
            else:
                await interaction.response.send_message(f"💰 **【合併結算】目前的總債務關係：**\n\n{first_content}", ephemeral=True)
                
            # 第二筆以上才用 followup 發送
            if len(debt_outputs) > 1:
                for content, view in debt_outputs[1:]:
                    if view:
                        await interaction.followup.send(content, view=view, ephemeral=True)
                    else:
                        await interaction.followup.send(content, ephemeral=True)
                        
        except Exception as e:
            print(f"【合併結算崩潰】: {e}")
            try:
                await interaction.response.send_message(f"❌ 結算發生錯誤: {e}", ephemeral=True)
            except:
                await interaction.followup.send(f"❌ 結算發生錯誤: {e}", ephemeral=True)

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
    
    # 指令一：叫出選單
    if message.content == "!menu":
        await message.channel.send("🏮 **記帳助手主選單**\n點擊下方按鈕進行操作：", view=MainMenuView())
        
    # 指令二：綁定個人的 Line Pay 連結 (強效防呆重構版)
    if message.content.startswith("!setpay "):
        raw_text = message.content.replace("!setpay ", "").strip()
        
        # 自動從輸入的段落中，精準過濾出包含 line 轉帳的 URL 標籤
        link = None
        for word in raw_text.split():
            if "line.me/" in word:
                link = word
                break
                
        if not link:
            await message.channel.send("❌ 格式不正確！請確認輸入的內容包含合法的 LINE 轉帳連結。")
            return
            
        data = load_data()
        data["user_payments"][message.author.name] = link
        save_data(data)
        await message.channel.send(f"✅ 成功為使用者 **{message.author.name}** 綁定 LINE Pay 轉帳連結！")

if TOKEN:
    client.run(TOKEN)