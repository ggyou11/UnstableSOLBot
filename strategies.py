from dataclasses import dataclass
import ccxt
import pandas as pd
import numpy as np
import requests
import time
import logging
from typing import Optional, Dict

@dataclass
class RSIConfig:
    rsi_period: int = 14
    oversold: int = 30
    overbought: int = 70
    stop_loss: float = 0.02  # 2% stop loss
    take_profit: float = 0.05  # 5% take profit
    risk_percentage: float = 0.1  # 10% of balance per trade
    ema_window: int = 14  # For Wilder's smoothing

class RSIStrategy:
    def __init__(self, 
                 exchange: ccxt.Exchange,
                 symbol: str,
                 timeframe: str = '5m',
                 config: RSIConfig = RSIConfig(),
                 telegram_bot_token: Optional[str] = None,
                 telegram_chat_id: Optional[str] = None):
        
        self.exchange = exchange
        self.symbol = symbol
        self.timeframe = timeframe
        self.config = config
        self.position: Optional[Dict] = None
        self.telegram_bot_token = telegram_bot_token
        self.telegram_chat_id = telegram_chat_id
        self._validate_symbol()
        
    def _validate_symbol(self):
        """Verify the symbol exists on the exchange"""
        if self.symbol not in self.exchange.markets:
            raise ValueError(f"Invalid symbol: {self.symbol}")

    def fetch_data(self, limit: int = 100) -> Optional[pd.DataFrame]:
        """Fetch historical OHLCV data"""
        try:
            ohlcv = self.exchange.fetch_ohlcv(
                self.symbol, 
                self.timeframe, 
                limit=limit
            )
            df = pd.DataFrame(
                ohlcv, 
                columns=['timestamp', 'open', 'high', 'low', 'close', 'volume']
            )
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            return df
        except Exception as e:
            logging.error(f"Data fetch error: {str(e)}")
            return None

    def _calculate_rsi_wilders(self, df: pd.DataFrame) -> pd.DataFrame:
        """Calculate RSI using Wilder's smoothing (EMA)"""
        delta = df['close'].diff()
        gain = delta.where(delta > 0, 0.0)
        loss = -delta.where(delta < 0, 0.0)

        avg_gain = gain.ewm(
            alpha=1/self.config.ema_window, 
            adjust=False
        ).mean()
        avg_loss = loss.ewm(
            alpha=1/self.config.ema_window, 
            adjust=False
        ).mean()

        rs = avg_gain / (avg_loss + 1e-10)
        df['rsi'] = 100 - (100 / (1 + rs))
        return df

    def generate_signal(self, df: pd.DataFrame) -> str:
        """Generate trading signal"""
        if len(df) < self.config.rsi_period:
            return "HOLD"

        df = self._calculate_rsi_wilders(df)
        latest_rsi = df['rsi'].iloc[-1]

        if latest_rsi < self.config.oversold:
            return "BUY"
        if latest_rsi > self.config.overbought:
            return "SELL"
        return "HOLD"

    def _get_trade_amount(self, price: float) -> Optional[float]:
        """Calculate position size with risk management"""
        try:
            balance = self.exchange.fetch_balance({'type': 'trade'})
            usdt_balance = balance['USDT']['free']
            risk_amount = usdt_balance * self.config.risk_percentage
            return risk_amount / price
        except Exception as e:
            logging.error(f"Balance check error: {str(e)}")
            return None

    def execute_trade(self, signal: str):
        """Execute trade with proper error handling"""
        try:
            ticker = self.exchange.fetch_ticker(self.symbol)
            price = ticker['last']
            
            if signal == "BUY" and not self.position:
                amount = self._get_trade_amount(price)
                if not amount or amount <= 0:
                    return

                # Check minimum order size
                market = self.exchange.market(self.symbol)
                if amount < market['limits']['amount']['min']:
                    logging.warning(f"Order amount below minimum: {amount}")
                    return

                order = self.exchange.create_market_buy_order(
                    self.symbol, 
                    amount
                )
                self.position = {
                    "entry_price": price,
                    "amount": amount,
                    "timestamp": time.time()
                }
                self.send_telegram_message(
                    f"✅ BUY {self.symbol}\n"
                    f"Price: {price:.4f}\n"
                    f"Amount: {amount:.2f}\n"
                    f"RSI: {self._current_rsi:.1f}"
                )

            elif signal == "SELL" and self.position:
                order = self.exchange.create_market_sell_order(
                    self.symbol, 
                    self.position["amount"]
                )
                pl = (price / self.position["entry_price"] - 1) * 100
                self.send_telegram_message(
                    f"✅ SELL {self.symbol}\n"
                    f"Price: {price:.4f}\n"
                    f"P/L: {pl:.2f}%\n"
                    f"RSI: {self._current_rsi:.1f}"
                )
                self.position = None

        except ccxt.InsufficientFunds as e:
            logging.error(f"Insufficient funds: {str(e)}")
            self.send_telegram_message("❌ Insufficient funds for trade")
        except ccxt.NetworkError as e:
            logging.error(f"Network error: {str(e)}")
        except Exception as e:
            logging.error(f"Trade execution error: {str(e)}")

    def _check_position_limits(self):
        """Check if position needs to be closed"""
        if not self.position:
            return

        try:
            ticker = self.exchange.fetch_ticker(self.symbol)
            price = ticker['last']
            entry = self.position["entry_price"]
            elapsed = time.time() - self.position["timestamp"]

            # Check time-based exit (e.g., 4 hours)
            if elapsed > 14400:  # 4 hours
                self.execute_trade("SELL")
                self.send_telegram_message(
                    f"🕒 Time-based exit\n"
                    f"Price: {price:.4f}\n"
                    f"Hold time: {elapsed/3600:.1f}h"
                )
                return

            # Check stop loss/take profit
            if price <= entry * (1 - self.config.stop_loss):
                self.execute_trade("SELL")
                self.send_telegram_message(
                    f"❌ Stop Loss\nPrice: {price:.4f}"
                )
            elif price >= entry * (1 + self.config.take_profit):
                self.execute_trade("SELL")
                self.send_telegram_message(
                    f"🎯 Take Profit\nPrice: {price:.4f}"
                )

        except Exception as e:
            logging.error(f"Position check error: {str(e)}")

    def send_telegram_message(self, message: str):
        """Send formatted Telegram message"""
        if not all([self.telegram_bot_token, self.telegram_chat_id]):
            return

        try:
            response = requests.post(
                f"https://api.telegram.org/bot{self.telegram_bot_token}/sendMessage",
                json={
                    "chat_id": self.telegram_chat_id,
                    "text": message,
                    "parse_mode": "Markdown"
                },
                timeout=5
            )
            response.raise_for_status()
        except Exception as e:
            logging.error(f"Telegram error: {str(e)}")

    def run(self):
        """Main trading loop with improved timing"""
        logging.info(f"Starting RSI strategy for {self.symbol}")
        interval = self.exchange.parse_timeframe(self.timeframe) * 1000
        
        while True:
            start_time = time.time()
            
            try:
                df = self.fetch_data()
                if df is not None and not df.empty:
                    signal = self.generate_signal(df)
                    self._current_rsi = df['rsi'].iloc[-1]
                    logging.debug(f"RSI: {self._current_rsi:.1f} - Signal: {signal}")
                    
                    self.execute_trade(signal)
                    self._check_position_limits()
                
                # Sleep until next candle
                sleep_time = interval - ((time.time() - start_time) % interval)
                time.sleep(max(sleep_time, 10))
                
            except KeyboardInterrupt:
                logging.info("Strategy stopped by user")
                break
            except Exception as e:
                logging.error(f"Main loop error: {str(e)}")
                time.sleep(60)