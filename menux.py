# menu.py
import locale
import curses
import os
import logging
from dotenv import load_dotenv
import ccxt
import requests
from strategies import RSIStrategy
import time
from typing import Tuple, Optional

# Configure logging
logging.basicConfig(filename='trading_bot.log', level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')

# Set locale for terminal compatibility
locale.setlocale(locale.LC_ALL, '')

# Load environment variables
load_dotenv()

class TradingBot:
    def __init__(self):
        self._init_exchange()
        self.strategy: Optional[RSIStrategy] = None
        self._init_strategy()
        
    def _init_exchange(self):
        """Initialize cryptocurrency exchange connection"""
        try:
            self.exchange = ccxt.kucoin({
                'apiKey': os.getenv("apikey"),
                'secret': os.getenv("secret"),
                'password': os.getenv("password"),
                'enableRateLimit': True,
                'options': {'adjustForTimeDifference': True}
            })
            self.exchange.load_markets()
            logging.info("Exchange initialized successfully")
        except Exception as e:
            logging.error(f"Exchange initialization failed: {str(e)}")
            raise

    def _init_strategy(self):
        """Initialize trading strategy"""
        try:
            self.strategy = RSIStrategy(
                exchange=self.exchange,
                symbol="XRP/USDT",
                timeframe="5m",
                telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN"),
                telegram_chat_id=os.getenv("ID_CHAT")
            )
            logging.info("Strategy initialized successfully")
        except Exception as e:
            logging.error(f"Strategy initialization failed: {str(e)}")
            raise

    def get_usdt_balance(self) -> Tuple[str, str]:
        """Get USDT balance and send to Telegram"""
        try:
            balance = self.exchange.fetch_balance({'type': 'trade'})
            usdt_balance = balance['USDT']
            balance_info = (
                f"Total: {usdt_balance['total']:.2f}\n"
                f"Free: {usdt_balance['free']:.2f}\n"
                f"Used: {usdt_balance['used']:.2f}"
            )

            terminal_msg = f"USDT Balance:\n{balance_info}"
            telegram_msg = f"💰 USDT Balance Update:\n{balance_info}"

            response = requests.post(
                f"https://api.telegram.org/bot{self.strategy.telegram_bot_token}/sendMessage",
                json={"chat_id": self.strategy.telegram_chat_id, "text": telegram_msg},
                timeout=10
            )

            response.raise_for_status()
            return terminal_msg, "Telegram: [✓] Sent"
            
        except requests.exceptions.RequestException as e:
            logging.error(f"Telegram API error: {str(e)}")
            return terminal_msg, "Telegram: [✗] Failed - Network Error"
        except Exception as e:
            logging.error(f"Balance check error: {str(e)}")
            return f"Error: {str(e)}", ""

# ASCII Art (Simplified)
LOGO = [
    r"  _______  ______   _______  _______  _        _  _______ ",
    r" (  ____ \(  __  \ (  ___  )(  ____ \| \    /\( )(  ____ \/",
    r" | (    \/| (  \  )| (   ) || (    \/|  \  / /| || (    \/",
    r" | (_____ | |   ) || |   | || |      |  (_/ / | || (__    ",
    r" (_____  )| |   | || |   | || | ____ |   _ (  | ||  __)   ",
    r"       ) || |   ) || |   | || | \_  )|  ( \ \ | || (      ",
    r" /\____) || (__/  )| (___) || (___) ||  /  \ \| || (____/\/",
    r" \_______)(______/ (_______)(_______)|_/    \/(_)(_______/",
]

NAME = ["TRADING BOT v1.1", "by ggyou96"]

class TerminalUI:
    MIN_HEIGHT = 5
    MIN_WIDTH = 20
    
    def __init__(self, stdscr):
        self.stdscr = stdscr
        self.bot = TradingBot()
        self.options = ["Check USDT Balance", "Start Trading", "Exit"]
        self.current_option = 0
        self.trading_active = False

    def _check_terminal_size(self):
        """Ensure terminal meets minimum size requirements"""
        h, w = self.stdscr.getmaxyx()
        if h < self.MIN_HEIGHT or w < self.MIN_WIDTH:
            msg = f"Terminal too small (min {self.MIN_WIDTH}x{self.MIN_HEIGHT})"
            self.stdscr.addstr(0, 0, msg, curses.A_BOLD)
            return False
        return True

    def _draw_header(self):
        """Draw logo and name"""
        h, w = self.stdscr.getmaxyx()
        
        # Draw logo
        start_y = 2
        for i, line in enumerate(LOGO):
            x = (w - len(line)) // 2
            try:
                self.stdscr.addstr(start_y + i, x, line, curses.A_BOLD)
            except curses.error:
                pass

        # Draw name
        name_y = h // 2 - len(NAME) // 2
        for i, line in enumerate(NAME):
            x = (w - len(line)) // 2
            try:
                self.stdscr.addstr(name_y + i, x, line, curses.A_BOLD | curses.COLOR_CYAN)
            except curses.error:
                pass

    def _draw_menu(self):
        """Draw interactive menu"""
        if self.trading_active:
            return  # Hide menu when trading

        h, w = self.stdscr.getmaxyx()
        menu_y = h - len(self.options) - 5
        
        for i, option in enumerate(self.options):
            x = (w - len(option)) // 2
            y = menu_y + i
            attr = curses.A_REVERSE if i == self.current_option else curses.A_NORMAL
            try:
                self.stdscr.addstr(y, x, option, attr)
            except curses.error:
                pass

    def _handle_input(self):
        """Handle user input and navigation"""
        key = self.stdscr.getch()
        
        if key == curses.KEY_UP and self.current_option > 0:
            self.current_option -= 1
        elif key == curses.KEY_DOWN and self.current_option < len(self.options) - 1:
            self.current_option += 1
        elif key in (10, 13):  # Enter key
            return self.options[self.current_option]
        return None

    def _show_message(self, message, duration=3):
        """Display temporary message"""
        h, w = self.stdscr.getmaxyx()
        for i, line in enumerate(message):
            x = (w - len(line)) // 2
            y = h - 5 + i
            try:
                self.stdscr.addstr(y, x, line)
            except curses.error:
                pass
        self.stdscr.refresh()
        time.sleep(duration)

    def _handle_trading_display(self):
        """Show trading activity while trading is active"""
        self.stdscr.clear()
        h, w = self.stdscr.getmaxyx()

        try:
            while self.trading_active:
                df = self.bot.strategy.fetch_data()
                if df is not None and not df.empty:
                    signal = self.bot.strategy.generate_signal(df)
                    rsi = df['rsi'].iloc[-1]

                    message = [
                        f"RSI: {rsi:.1f}",
                        f"Signal: {signal}",
                        "Press ESC to stop trading"
                    ]

                    for i, line in enumerate(message):
                        x = (w - len(line)) // 2
                        y = h // 2 + i
                        try:
                            self.stdscr.addstr(y, x, line, curses.A_BOLD)
                        except curses.error:
                            pass

                    self.stdscr.refresh()
                    self.bot.strategy.execute_trade(signal)
                    time.sleep(5)

                key = self.stdscr.getch()
                if key == 27:  # ESC key
                    self.trading_active = False
                    break
        except KeyboardInterrupt:
            self.trading_active = False

    def run(self):
        curses.curs_set(0)
        self.stdscr.timeout(100)  # Non-blocking input
        
        while True:
            self.stdscr.clear()
            if not self._check_terminal_size():
                self.stdscr.refresh()
                continue

            self._draw_header()
            self._draw_menu()
            
            selected = self._handle_input()
            if selected == "Exit":
                break
            elif selected == "Check USDT Balance":
                balance_result, telegram_status = self.bot.get_usdt_balance()
                self._show_message([balance_result, telegram_status])
            elif selected == "Start Trading":
                self.trading_active = True
                self._handle_trading_display()

            self.stdscr.refresh()

def main(stdscr):
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(1, curses.COLOR_CYAN, -1)
    ui = TerminalUI(stdscr)
    ui.run()

if __name__ == "__main__":
    try:
        curses.wrapper(main)
    except KeyboardInterrupt:
        print("\nApplication terminated by user")