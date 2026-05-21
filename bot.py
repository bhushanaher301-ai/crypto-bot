import os
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from dotenv import load_dotenv, set_key
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from tradingview_ta import TA_Handler, Interval, Exchange

# --- DUMMY WEB SERVER FOR RENDER ---
class DummyHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        self.wfile.write(b"Bot is running 24/7!")

def start_dummy_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(('0.0.0.0', port), DummyHandler)
    server.serve_forever()
# -----------------------------------

# Load environment variables
dotenv_path = os.path.join(os.path.dirname(__file__), '.env')
load_dotenv(dotenv_path)

TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
ALLOWED_USER_ID = os.getenv('ALLOWED_USER_ID')

PORTFOLIO_FILE = os.path.join(os.path.dirname(__file__), 'portfolio.json')
COINS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"]
TRADE_AMOUNT = 1000.0  # Buy $1000 worth of crypto per Strong Buy signal

def load_portfolio():
    if not os.path.exists(PORTFOLIO_FILE):
        return {
            "balance": 10000.0,
            "positions": {},
            "auto_trading": False
        }
    with open(PORTFOLIO_FILE, 'r') as f:
        return json.load(f)

def save_portfolio(data):
    with open(PORTFOLIO_FILE, 'w') as f:
        json.dump(data, f, indent=4)

async def is_allowed(update: Update) -> bool:
    global ALLOWED_USER_ID
    user_id = str(update.effective_user.id)
    
    if not ALLOWED_USER_ID:
        ALLOWED_USER_ID = user_id
        set_key(dotenv_path, 'ALLOWED_USER_ID', user_id)
        await update.message.reply_text(f"🔒 Bot is now locked to your User ID ({user_id}).")
        return True
    
    if user_id == ALLOWED_USER_ID:
        return True
    else:
        await update.message.reply_text("⛔ Unauthorized user.")
        return False

# --- TRADING LOGIC ---

async def analyze_market(context: ContextTypes.DEFAULT_TYPE):
    portfolio = load_portfolio()
    if not portfolio.get("auto_trading", False):
        return
        
    chat_id = ALLOWED_USER_ID
    if not chat_id:
        return
        
    for symbol in COINS:
        try:
            handler = TA_Handler(
                symbol=symbol,
                exchange="BINANCE",
                screener="crypto",
                interval=Interval.INTERVAL_1_MINUTE, # 1-min timeframe
                timeout=None
            )
            analysis = handler.get_analysis()
            rec = analysis.summary['RECOMMENDATION']
            price = analysis.indicators['close']
            
            # Logic for Buying
            if rec == 'STRONG_BUY' or rec == 'BUY':  
                if symbol not in portfolio["positions"] or portfolio["positions"][symbol]["amount"] == 0:
                    if portfolio["balance"] >= TRADE_AMOUNT:
                        amount_to_buy = TRADE_AMOUNT / price
                        portfolio["balance"] -= TRADE_AMOUNT
                        portfolio["positions"][symbol] = {
                            "amount": amount_to_buy,
                            "buy_price": price
                        }
                        save_portfolio(portfolio)
                        msg = f"🟢 **AUTO-BUY ALERT**\nCoin: {symbol}\nAction: BUY\nPrice: ${price}\nAmount: {amount_to_buy:.4f} {symbol}\nCost: ${TRADE_AMOUNT}\nBalance Left: ${portfolio['balance']:.2f}"
                        await context.bot.send_message(chat_id=chat_id, text=msg, parse_mode='Markdown')
            
            # Logic for Selling
            elif rec == 'STRONG_SELL' or rec == 'SELL':
                if symbol in portfolio["positions"] and portfolio["positions"][symbol]["amount"] > 0:
                    amount_to_sell = portfolio["positions"][symbol]["amount"]
                    buy_price = portfolio["positions"][symbol]["buy_price"]
                    revenue = amount_to_sell * price
                    profit = revenue - (amount_to_sell * buy_price)
                    
                    portfolio["balance"] += revenue
                    portfolio["positions"][symbol] = {"amount": 0.0, "buy_price": 0.0}
                    save_portfolio(portfolio)
                    
                    profit_str = f"+${profit:.2f}" if profit >= 0 else f"-${abs(profit):.2f}"
                    emoji = "📈" if profit >= 0 else "📉"
                    
                    msg = f"🔴 **AUTO-SELL ALERT**\nCoin: {symbol}\nAction: SELL\nPrice: ${price}\nRevenue: ${revenue:.2f}\n{emoji} Profit/Loss: {profit_str}\nNew Balance: ${portfolio['balance']:.2f}"
                    await context.bot.send_message(chat_id=chat_id, text=msg, parse_mode='Markdown')
                    
        except Exception as e:
            print(f"Error analyzing {symbol}: {e}")

async def start_auto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_allowed(update): return
    portfolio = load_portfolio()
    portfolio["auto_trading"] = True
    save_portfolio(portfolio)
    await update.message.reply_text("🤖 **Auto-Trading is now ON.** The bot will scan the market every 1 minute and trade automatically.", parse_mode='Markdown')

async def stop_auto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_allowed(update): return
    portfolio = load_portfolio()
    portfolio["auto_trading"] = False
    save_portfolio(portfolio)
    await update.message.reply_text("🛑 **Auto-Trading is now OFF.**", parse_mode='Markdown')

async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_allowed(update): return
    portfolio = load_portfolio()
    await update.message.reply_text(f"💵 **Virtual Balance:** ${portfolio['balance']:.2f} USDT", parse_mode='Markdown')

async def show_portfolio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_allowed(update): return
    portfolio = load_portfolio()
    msg = f"💼 **Your Portfolio**\n💵 Available Cash: ${portfolio['balance']:.2f}\n\n**Active Positions:**\n"
    has_positions = False
    for symbol, data in portfolio["positions"].items():
        if data["amount"] > 0:
            has_positions = True
            msg += f"- **{symbol}**: {data['amount']:.4f} (Bought at ${data['buy_price']:.2f})\n"
    if not has_positions:
        msg += "No active trades currently."
    
    msg += f"\n\n🤖 Auto-Trading Status: {'🟢 ON' if portfolio.get('auto_trading') else '🔴 OFF'}"
    await update.message.reply_text(msg, parse_mode='Markdown')

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_allowed(update): return
    welcome_message = (
        "🤖 **Crypto Trading Bot Online! (Cloud Version)**\n\n"
        "**Trading Commands:**\n"
        "/balance - Check virtual USDT\n"
        "/portfolio - See open trades\n"
        "/startauto - Turn ON Auto-Trading\n"
        "/stopauto - Turn OFF Auto-Trading"
    )
    await update.message.reply_text(welcome_message, parse_mode='Markdown')

if __name__ == '__main__':
    if not TOKEN:
        print("ERROR: TELEGRAM_BOT_TOKEN not found in .env file!")
        exit(1)
        
    print("Starting Dummy Web Server...")
    threading.Thread(target=start_dummy_server, daemon=True).start()
        
    print("Starting bot with Trading Engine...")
    app = ApplicationBuilder().token(TOKEN).build()

    # Commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("balance", balance))
    app.add_handler(CommandHandler("portfolio", show_portfolio))
    app.add_handler(CommandHandler("startauto", start_auto))
    app.add_handler(CommandHandler("stopauto", stop_auto))

    # Background Job
    job_queue = app.job_queue
    # Run analysis every 1 minute (60 seconds), starting 10 seconds after boot
    job_queue.run_repeating(analyze_market, interval=60, first=10)

    print("Bot is polling... Press Ctrl+C to stop.")
    app.run_polling()
