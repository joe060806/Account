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
class AddRecordModal(Modal, title="➕ 建立新帳目（支援智慧均分）"):
    # 1. 界面更新：更清晰的提示標籤與防呆長度限制
    amount = TextInput(
        label="💰 消費總金額", 
        placeholder="請輸入純數字，例如: 600 (不需打字元)", 
        min_length=1, 
        max_length=10
    )
    desc = TextInput(
        label="🏷️ 品項或活動描述", 
        placeholder="例如: 麥當勞晚餐、好市多採買...", 
        min_length=1, 
        max_length=50
    )
    debt = TextInput(
        label="👥 債務人與金額分配 (留空則不計債務)", 
        placeholder="智慧模式一（自訂）：李欠200 呂欠150\n智慧模式二（均分）：李 呂 偉 (自動平分總金額)", 
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=200
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            # 防禦性清理：過濾掉使用者可能誤打的 "$", "," 等符號
            clean_amount_str = self.amount.value.replace("$", "").replace(",", "").strip()
            amt_val = float(clean_amount_str)
            
            if amt_val <= 0:
                await interaction.response.send_message("❌ 金額必須大於 0 元！", ephemeral=True)
                return

            desc_val = self.desc.value.strip()
            raw_debt_info = self.debt.value.strip()
            
            splits = {}
            
            if raw_debt_info:
                # 將輸入依空白或換行切分成標籤串（Tokens）
                tokens = raw_debt_info.split()
                
                # 判斷使用者是否使用了「模式二：純人名均分模式」
                # 如果所有輸入的字詞裡面，完全沒有任何人打「欠」這個字，就啟動全自動均分
                is_pure_split_mode = all("欠" not in token for token in tokens)
                
                if is_pure_split_mode:
                    # 總金額除以（全體欠錢人數），自動四捨五入到小數後一位
                    share = round(amt_val / len(tokens), 1)
                    for person in tokens:
                        splits[person] = share
                else:
                    # 模式一：解析傳統的「李欠200」自訂模式
                    current_name = None
                    for item in tokens:
                        if "欠" in item:
                            if item.startswith("欠"):
                                money_str = item.replace("欠", "")
                                if current_name: 
                                    splits[current_name] = float(money_str)
                            else:
                                name, money_str = item.split("欠")
                                splits[name] = float(money_str)
                        else:
                            # 處理名字跟「欠」字被空白隔開的邊緣狀況（例如：李 欠200）
                            current_name = item

            # 取得台灣時間 (UTC+8)
            tw_tz = timezone(timedelta(hours=8))
            now = datetime.now(tw_tz).strftime("%Y/%m/%d %H:%M")
            
            # 寫入資料庫
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
            
            # ==========================================
            # 界面更新：送出精緻的動態確認小卡
            # ==========================================
            confirm_msg = f"✅ **成功記帳！**\n"
            confirm_msg += f"─" * 15 + f"\n"
            confirm_msg += f"📝 **品項**：{desc_val}\n"
            confirm_msg += f"👤 **付款人**：`{interaction.user.name}` │ 💰 **總金額**：{amt_val} 元\n"
            
            if splits:
                confirm_msg += "👥 **債務分配結果**：\n"
                for name, amt in splits.items():
                    confirm_msg += f" └─ {name} 應分擔 `{amt}` 元\n"
            else:
                confirm_msg += "✨ *(此筆交易為個人消費，未產生群組債務)*\n"
                
            await interaction.response.send_message(confirm_msg, ephemeral=False)
            
        except ValueError:
            await interaction.response.send_message("❌ **格式錯誤**：請確保『消費總金額』與『債務金額』輸入的是有效數字！", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ **系統異常**：無法處理此記帳請求 ({e})", ephemeral=True)
            
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

        # ==========================================
        # 1. 處理時間與計算相對時間的輔助函式
        # ==========================================
        tw_tz = timezone(timedelta(hours=8))
        now = datetime.now(tw_tz)
        
        def get_relative_time(time_str):
            try:
                # 解析紀錄中的時間字串
                t_time = datetime.strptime(time_str, "%Y/%m/%d %H:%M").replace(tzinfo=tw_tz)
                diff = now - t_time
                
                if diff.days == 0:
                    if diff.seconds < 60: return "剛剛"
                    if diff.seconds < 3600: return f"{diff.seconds // 60} 分鐘前"
                    return f"{diff.seconds // 3600} 小時前"
                elif diff.days == 1: return "昨天"
                elif diff.days == 2: return "前天"
                elif diff.days < 7: return f"{diff.days} 天前"
                else: return "一週以上"
            except:
                return ""

        # ==========================================
        # 2. 時間維度統計（計算本週累計消費）
        # ==========================================
        week_count = 0
        week_total = 0.0
        one_week_ago = now - timedelta(days=7)
        
        for t in ts:
            try:
                t_time = datetime.strptime(t['time'], "%Y/%m/%d %H:%M").replace(tzinfo=tw_tz)
                if t_time >= one_week_ago:
                    week_count += 1
                    week_total += float(t['amount'])
            except: pass

        # ==========================================
        # 3. 渲染輸出介面（加入分頁概念：預設只顯示最新的 5 筆）
        # ==========================================
        msg = f"📊 **【時間維度摘要】**\n📅 過去 7 天內累計記帳：`{week_count}` 筆 │ 總金額：`{round(week_total, 1)}` 元\n"
        msg += "─" * 15 + "\n📜 **最新交易清單 (僅顯示最新 5 筆)：**\n"
        
        # 倒序排列（讓最新建立的帳目排在最上面）
        latest_ts = list(reversed(ts))[:5]
        
        for t in latest_ts:
            rel_time = get_relative_time(t['time'])
            time_display = f"{t['time']} *({rel_time})*" if rel_time else t['time']
            
            msg += f"\n🔹 **ID:{t['id']}** │ 🕒 {time_display} │ 🏷️ **{t['desc']}**\n"
            msg += f"👤 Payer: `{t['payer']}` (付 {t['amount']} 元)\n"
            
            # 優化債務人顯示
            for name, amt in t.get("splits", {}).items():
                if str(name) != str(t['payer']): 
                    msg += f"   └─ 👤 {name} 欠 {amt} 元\n"
                    
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