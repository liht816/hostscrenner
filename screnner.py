# ═══════════════════════════════════════════════════════════════
# FLASK WEB SERVER ДЛЯ RENDER + UPTIMEROBOT
# ═══════════════════════════════════════════════════════════════
from flask import Flask, jsonify
import threading
import os

flask_app = Flask(__name__)

@flask_app.route('/')
def home():
    return jsonify({
        "status": "running",
        "bot": "MEXC Screener v9.0",
        "message": "Bot is active!"
    })

@flask_app.route('/health')
def health():
    return jsonify({"status": "healthy", "code": 200}), 200

@flask_app.route('/ping')
def ping():
    return "pong", 200

def run_flask():
    port = int(os.environ.get('PORT', 10000))
    flask_app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)

# ═══════════════════════════════════════════════════════════════

import requests
import time
from datetime import datetime
import threading
import json
import os
from concurrent.futures import ThreadPoolExecutor
import io

# Matplotlib для графиков
import matplotlib
matplotlib.use('Agg')  # Важно! Для работы без GUI
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

# ═══════════════════════════════════════════════════════════════
TELEGRAM_BOT_TOKEN = "7589870613:AAFtTcUROflTN40AMsoQZvS4oy6AmrjEBXI"
ADMIN_LINK = "https://t.me/kingpumpdump"
SETTINGS_FILE = "user_settings.json"
SUBSCRIPTION_CONFIG_FILE = "subscription_config.json"
SUBSCRIPTIONS_FILE = "subscriptions.json"
USED_TRANSACTIONS_FILE = "used_transactions.json"
# ═══════════════════════════════════════════════════════════════


class SettingsManager:
    """Менеджер сохранения/загрузки настроек"""
    
    def __init__(self, filename=SETTINGS_FILE):
        self.filename = filename
        self.settings = {}
        self.lock = threading.Lock()
        self.load()
    
    def load(self):
        try:
            if os.path.exists(self.filename):
                with open(self.filename, 'r', encoding='utf-8') as f:
                    self.settings = json.load(f)
                print(f"✅ Настройки загружены: {len(self.settings)} пользователей")
        except Exception as e:
            print(f"❌ Ошибка загрузки настроек: {e}")
            self.settings = {}
    
    def save(self):
        with self.lock:
            try:
                with open(self.filename, 'w', encoding='utf-8') as f:
                    json.dump(self.settings, f, ensure_ascii=False, indent=2)
            except Exception as e:
                print(f"❌ Ошибка сохранения настроек: {e}")
    
    def get_user_settings(self, chat_id):
        return self.settings.get(str(chat_id), {})
    
    def set_user_setting(self, chat_id, key, value):
        chat_id = str(chat_id)
        with self.lock:
            if chat_id not in self.settings:
                self.settings[chat_id] = {}
            self.settings[chat_id][key] = value
        self.save()
    
    def get_all_settings(self, chat_id):
        """Получить все настройки пользователя с дефолтными значениями"""
        defaults = {
            'timeframe': '5m',
            'min_pump': 5.0,
            'min_dump': 5.0,
            'signal_mode': 'both',
            'candle_mode': 'current',
            'scan_interval': 5,
            'market_type_filter': 'all',
            'spot_quote_filter': 'all',
            'min_volume_usdt': 0,
            'alert_cooldown': 60,
            'allow_duplicates': True,
            'send_charts': True
        }
        user = self.get_user_settings(chat_id).copy()
        for key, value in defaults.items():
            if key not in user:
                user[key] = value
        return user
    
    def save_all_settings(self, chat_id, settings_dict):
        chat_id = str(chat_id)
        with self.lock:
            self.settings[chat_id] = settings_dict
        self.save()


class MEXCFullScreener:
    def __init__(self, send_func, chat_id, settings_manager, send_photo_func=None):
        self.base_url = "https://contract.mexc.com"
        self.spot_url = "https://api.mexc.com"
        
        self.sent_alerts = {}
        self.timeframe = "Min5"
        self.timeframe_display = "5m"
        self.min_pump = 5.0
        self.min_dump = 5.0
        self.send_telegram = send_func
        self.send_telegram_photo = send_photo_func
        self.chat_id = chat_id
        
        self.signal_mode = "both"
        self.candle_mode = "current"
        self.scan_interval = 5
        self.send_charts = True
        
        self.futures_symbols = []
        self.spot_symbols = []
        self.all_symbols = []
        self.funding_rates = {}
        self.last_update = 0
        
        self.cached_futures_tickers = {}
        self.cached_spot_tickers = {}
        self.tickers_cache_time = 0
        
        self.min_volume_usdt = 0
        self.market_type_filter = "all"
        self.spot_quote_filter = "all"
        
        self.alert_cooldown = 60
        self.allow_duplicates = True
        
        self.price_alerts = {}
        self.max_alerts_per_user = 20
        
        self.signal_history = []
        self.max_history = 5000
        self.daily_signal_count = {}
        
        self.settings_manager = settings_manager
        self.running = False
        
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'application/json'
        }
        
        self.tf_map = {
            "1m": "Min1", "5m": "Min5", "15m": "Min15",
            "30m": "Min30", "1h": "Min60", "4h": "Hour4", "1d": "Day1"
        }
        
        self.spot_tf_map = {
            "1m": "1m", "5m": "5m", "15m": "15m",
            "30m": "30m", "1h": "1h", "4h": "4h", "1d": "1d"
        }
        
        self.tf_seconds = {
            "1m": 60, "5m": 300, "15m": 900, "30m": 1800,
            "1h": 3600, "4h": 14400, "1d": 86400
        }
        
        self.load_user_settings()
        self._load_price_alerts()
    
    def load_user_settings(self):
        settings = self.settings_manager.get_all_settings(self.chat_id)
        self.timeframe_display = settings.get('timeframe', '5m')
        self.timeframe = self.tf_map.get(self.timeframe_display, 'Min5')
        self.min_pump = settings.get('min_pump', 5.0)
        self.min_dump = settings.get('min_dump', 5.0)
        self.signal_mode = settings.get('signal_mode', 'both')
        self.candle_mode = settings.get('candle_mode', 'current')
        self.scan_interval = settings.get('scan_interval', 5)
        self.market_type_filter = settings.get('market_type_filter', 'all')
        self.spot_quote_filter = settings.get('spot_quote_filter', 'all')
        self.min_volume_usdt = settings.get('min_volume_usdt', 0)
        self.alert_cooldown = settings.get('alert_cooldown', 60)
        self.allow_duplicates = settings.get('allow_duplicates', True)
        self.send_charts = settings.get('send_charts', True)
    
    def save_user_settings(self):
        settings = {
            'timeframe': self.timeframe_display,
            'min_pump': self.min_pump,
            'min_dump': self.min_dump,
            'signal_mode': self.signal_mode,
            'candle_mode': self.candle_mode,
            'scan_interval': self.scan_interval,
            'market_type_filter': self.market_type_filter,
            'spot_quote_filter': self.spot_quote_filter,
            'min_volume_usdt': self.min_volume_usdt,
            'alert_cooldown': self.alert_cooldown,
            'allow_duplicates': self.allow_duplicates,
            'send_charts': self.send_charts
        }
        self.settings_manager.save_all_settings(self.chat_id, settings)
    
    def format_number(self, num):
        if num >= 1_000_000_000:
            return f"{num/1_000_000_000:.2f}B"
        elif num >= 1_000_000:
            return f"{num/1_000_000:.2f}M"
        elif num >= 1_000:
            return f"{num/1_000:.2f}K"
        return f"{num:.2f}"
    
    def format_price(self, price):
        if price >= 100:
            return f"{price:.2f}"
        elif price >= 1:
            return f"{price:.4f}"
        elif price >= 0.0001:
            return f"{price:.6f}"
        return f"{price:.8f}"
    
    def format_time_remaining(self, seconds):
        if seconds <= 0:
            return "закрыта"
        m, s = int(seconds // 60), int(seconds % 60)
        return f"{m}м {s}с" if m > 0 else f"{s}с"
    
# ═══════════════════════════════════════════════════════════════
# SUBSCRIPTION MANAGER
# ═══════════════════════════════════════════════════════════════

class SubscriptionManager:
    """Менеджер подписок с проверкой оплаты через блокчейн"""
    
    def __init__(self):
        self.config = self._load_config()
        self.subscriptions = self._load_subscriptions()
        self.used_transactions = self._load_used_transactions()
        self.pending_payments = {}  # chat_id -> {plan, network, amount, created_at}
        self.lock = threading.Lock()
    
    def _load_config(self):
        """Загрузка конфигурации"""
        try:
            if os.path.exists(SUBSCRIPTION_CONFIG_FILE):
                with open(SUBSCRIPTION_CONFIG_FILE, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    print(f"✅ Subscription config loaded")
                    return config
        except Exception as e:
            print(f"❌ Error loading subscription config: {e}")
        
        # Дефолтный конфиг
        return {
            "admin_ids": [7167732063],
            "wallets": {
                "TRC20": "TUuW5YBWKdhBvq7PD2rgFDDA79efmnu2L7",
                "BEP20": "0x9dc57bd0550d2e32a60b8462789b9b7aedd267b4"
            },
            "api_keys": {
                "bscscan": "AI752D1YTPV4NXCMUE1S2DPKP5IG1WRIE6"
            },
            "prices_usdt": {
                "1_month": 10,
                "3_months": 25,
                "6_months": 45,
                "1_year": 80
            },
            "plan_names": {
                "1_month": "1 месяц",
                "3_months": "3 месяца",
                "6_months": "6 месяцев",
                "1_year": "1 год"
            },
            "plan_days": {
                "1_month": 30,
                "3_months": 90,
                "6_months": 180,
                "1_year": 365
            }
        }
    
    def _load_subscriptions(self):
        """Загрузка подписок пользователей"""
        try:
            if os.path.exists(SUBSCRIPTIONS_FILE):
                with open(SUBSCRIPTIONS_FILE, 'r', encoding='utf-8') as f:
                    content = f.read().strip()
                    if content:
                        subs = json.load(f) if not content else json.loads(content)
                        print(f"✅ Subscriptions loaded: {len(subs)} users")
                        return subs
        except Exception as e:
            print(f"❌ Error loading subscriptions: {e}")
        return {}
    
    def _save_subscriptions(self):
        """Сохранение подписок"""
        with self.lock:
            try:
                with open(SUBSCRIPTIONS_FILE, 'w', encoding='utf-8') as f:
                    json.dump(self.subscriptions, f, ensure_ascii=False, indent=2)
            except Exception as e:
                print(f"❌ Error saving subscriptions: {e}")
    
    def _load_used_transactions(self):
        """Загрузка использованных транзакций"""
        try:
            if os.path.exists(USED_TRANSACTIONS_FILE):
                with open(USED_TRANSACTIONS_FILE, 'r', encoding='utf-8') as f:
                    content = f.read().strip()
                    if content:
                        return json.loads(content)
        except Exception as e:
            print(f"❌ Error loading used transactions: {e}")
        return []
    
    def _save_used_transactions(self):
        """Сохранение использованных транзакций"""
        with self.lock:
            try:
                with open(USED_TRANSACTIONS_FILE, 'w', encoding='utf-8') as f:
                    json.dump(self.used_transactions, f, ensure_ascii=False, indent=2)
            except Exception as e:
                print(f"❌ Error saving used transactions: {e}")
    
    def is_admin(self, chat_id):
        """Проверка, является ли пользователь админом"""
        return chat_id in self.config.get('admin_ids', [])
    
    def has_subscription(self, chat_id):
        """Проверка наличия активной подписки"""
        # Админы всегда имеют доступ
        if self.is_admin(chat_id):
            return True
        
        chat_id_str = str(chat_id)
        if chat_id_str not in self.subscriptions:
            return False
        
        sub = self.subscriptions[chat_id_str]
        expires_at = sub.get('expires_at', 0)
        
        return time.time() < expires_at
    
    def get_subscription_info(self, chat_id):
        """Получение информации о подписке"""
        if self.is_admin(chat_id):
            return {
                'active': True,
                'is_admin': True,
                'expires_at': None,
                'plan': 'admin'
            }
        
        chat_id_str = str(chat_id)
        if chat_id_str not in self.subscriptions:
            return {'active': False}
        
        sub = self.subscriptions[chat_id_str]
        expires_at = sub.get('expires_at', 0)
        active = time.time() < expires_at
        
        return {
            'active': active,
            'is_admin': False,
            'expires_at': expires_at,
            'plan': sub.get('plan', ''),
            'activated_at': sub.get('activated_at', 0)
        }
    
    def activate_subscription(self, chat_id, plan):
        """Активация подписки"""
        chat_id_str = str(chat_id)
        days = self.config['plan_days'].get(plan, 30)
        
        current_time = time.time()
        
        # Если уже есть активная подписка — продлеваем
        if chat_id_str in self.subscriptions:
            old_expires = self.subscriptions[chat_id_str].get('expires_at', 0)
            if old_expires > current_time:
                # Продление от текущей даты окончания
                new_expires = old_expires + (days * 86400)
            else:
                # Новая подписка от текущего момента
                new_expires = current_time + (days * 86400)
        else:
            new_expires = current_time + (days * 86400)
        
        self.subscriptions[chat_id_str] = {
            'plan': plan,
            'activated_at': current_time,
            'expires_at': new_expires
        }
        
        self._save_subscriptions()
        return new_expires
    
    def get_prices(self):
        """Получение цен"""
        return self.config.get('prices_usdt', {})
    
    def get_plan_name(self, plan):
        """Получение названия плана"""
        return self.config.get('plan_names', {}).get(plan, plan)
    
    def get_wallet(self, network):
        """Получение адреса кошелька"""
        return self.config.get('wallets', {}).get(network, '')
    
    def set_pending_payment(self, chat_id, plan, network):
        """Установка ожидающего платежа"""
        amount = self.config['prices_usdt'].get(plan, 0)
        self.pending_payments[chat_id] = {
            'plan': plan,
            'network': network,
            'amount': amount,
            'created_at': time.time()
        }
    
    def get_pending_payment(self, chat_id):
        """Получение ожидающего платежа"""
        return self.pending_payments.get(chat_id)
    
    def clear_pending_payment(self, chat_id):
        """Очистка ожидающего платежа"""
        if chat_id in self.pending_payments:
            del self.pending_payments[chat_id]
    
    def is_transaction_used(self, tx_hash):
        """Проверка, была ли транзакция уже использована"""
        return tx_hash.lower() in [t.lower() for t in self.used_transactions]
    
    def mark_transaction_used(self, tx_hash):
        """Отметить транзакцию как использованную"""
        self.used_transactions.append(tx_hash.lower())
        self._save_used_transactions()
    
    def verify_transaction_trc20(self, tx_hash, expected_amount):
        """Проверка TRC20 транзакции через Tronscan API"""
        try:
            # Приводим к нижнему регистру для сравнения
            my_wallet = self.get_wallet('TRC20').lower()
            
            # Tronscan API
            url = f"https://apilist.tronscanapi.com/api/transaction-info?hash={tx_hash}"
            
            response = requests.get(url, timeout=15)
            if response.status_code != 200:
                return False, "Ошибка API Tronscan"
            
            data = response.json()
            
            if not data or 'contractData' not in data:
                return False, "Транзакция не найдена"
            
            # Проверяем статус
            if not data.get('confirmed', False):
                return False, "Транзакция ещё не подтверждена. Подождите 1-2 минуты."
            
            # Проверяем что это TRC20 transfer
            contract_data = data.get('contractData', {})
            
            # Получатель
            to_address = contract_data.get('to_address', '').lower()
            if to_address != my_wallet:
                return False, "Неверный адрес получателя"
            
            # Сумма (в USDT 6 decimals)
            amount = float(contract_data.get('amount', 0)) / 1_000_000
            
            # Проверяем сумму с небольшой погрешностью (0.01 USDT)
            if abs(amount - expected_amount) > 0.01:
                return False, f"Неверная сумма: {amount} USDT (ожидалось {expected_amount} USDT)"
            
            # Проверяем что это USDT
            token_name = data.get('tokenTransferInfo', {}).get('symbol', '')
            if token_name.upper() not in ['USDT', 'TETHER']:
                # Альтернативная проверка
                contract_address = contract_data.get('contract_address', '')
                usdt_contract = 'TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t'.lower()
                if contract_address.lower() != usdt_contract:
                    return False, "Это не USDT транзакция"
            
            return True, "OK"
            
        except Exception as e:
            print(f"TRC20 verification error: {e}")
            return False, f"Ошибка проверки: {str(e)}"
    
    def verify_transaction_bep20(self, tx_hash, expected_amount):
        """Проверка BEP20 транзакции через BSCScan API"""
        try:
            my_wallet = self.get_wallet('BEP20').lower()
            api_key = self.config.get('api_keys', {}).get('bscscan', '')
            
            # Убираем 0x если есть для чистоты
            if not tx_hash.startswith('0x'):
                tx_hash = '0x' + tx_hash
            
            # BSCScan API - получаем информацию о транзакции
            url = f"https://api.bscscan.com/api?module=proxy&action=eth_getTransactionReceipt&txhash={tx_hash}&apikey={api_key}"
            
            response = requests.get(url, timeout=15)
            if response.status_code != 200:
                return False, "Ошибка API BSCScan"
            
            data = response.json()
            
            if data.get('error') or not data.get('result'):
                return False, "Транзакция не найдена"
            
            result = data['result']
            
            # Проверяем статус транзакции
            if result.get('status') != '0x1':
                return False, "Транзакция не подтверждена или неуспешна"
            
            # Ищем Transfer event в logs
            logs = result.get('logs', [])
            
            usdt_contract = '0x55d398326f99059ff775485246999027b3197955'.lower()  # BSC USDT
            transfer_topic = '0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef'  # Transfer event
            
            for log in logs:
                # Проверяем что это USDT контракт
                if log.get('address', '').lower() != usdt_contract:
                    continue
                
                topics = log.get('topics', [])
                if len(topics) < 3:
                    continue
                
                # Первый topic - это событие Transfer
                if topics[0].lower() != transfer_topic:
                    continue
                
                # Третий topic (index 2) - это адрес получателя (с padding)
                to_address = '0x' + topics[2][-40:].lower()
                
                if to_address != my_wallet:
                    continue
                
                # Сумма в data (18 decimals для BSC USDT)
                amount_hex = log.get('data', '0x0')
                amount_wei = int(amount_hex, 16)
                amount = amount_wei / 1e18
                
                # Проверяем сумму
                if abs(amount - expected_amount) > 0.01:
                    return False, f"Неверная сумма: {amount:.2f} USDT (ожидалось {expected_amount} USDT)"
                
                return True, "OK"
            
            return False, "USDT перевод на ваш кошелёк не найден в транзакции"
            
        except Exception as e:
            print(f"BEP20 verification error: {e}")
            return False, f"Ошибка проверки: {str(e)}"
    
    def verify_payment(self, chat_id, tx_hash):
        """Проверка платежа по TX Hash"""
        pending = self.get_pending_payment(chat_id)
        if not pending:
            return False, "Нет ожидающего платежа"
        
        # Проверяем что транзакция не использовалась
        if self.is_transaction_used(tx_hash):
            return False, "Эта транзакция уже была использована"
        
        network = pending['network']
        amount = pending['amount']
        
        # Проверяем в соответствующем блокчейне
        if network == 'TRC20':
            success, message = self.verify_transaction_trc20(tx_hash, amount)
        elif network == 'BEP20':
            success, message = self.verify_transaction_bep20(tx_hash, amount)
        else:
            return False, "Неизвестная сеть"
        
        if success:
            # Отмечаем транзакцию как использованную
            self.mark_transaction_used(tx_hash)
            
            # Активируем подписку
            plan = pending['plan']
            expires_at = self.activate_subscription(chat_id, plan)
            
            # Очищаем pending
            self.clear_pending_payment(chat_id)
            
            return True, expires_at
        
        return False, message
    
    def format_expires_date(self, timestamp):
        """Форматирование даты окончания"""
        if timestamp is None:
            return "∞ Навсегда"
        return datetime.fromtimestamp(timestamp).strftime('%d.%m.%Y %H:%M')
    
    def get_days_remaining(self, expires_at):
        """Получение оставшихся дней"""
        if expires_at is None:
            return 999999
        remaining = expires_at - time.time()
        return max(0, int(remaining / 86400))
    
    # ═══════════════════════════════════════════════════════════════
    # ГЕНЕРАЦИЯ ГРАФИКОВ (БЕЗ ЛИНИИ, ТОЛЬКО ЗАЛИВКА)
    # ═══════════════════════════════════════════════════════════════
    
    def generate_chart(self, symbol, klines, signal_type, current_price=None, change_percent=0):
       
        if not klines or len(klines) < 2:
            return None
    
        try:
            # Сортируем свечи по времени
            sorted_klines = sorted(klines, key=lambda x: x.get('time', 0))
        
            # Подготовка данных
            times = []
            opens = []
            closes = []
            highs = []
            lows = []
            volumes = []
        
            for candle in sorted_klines:
                ts = candle.get('time', 0)
                if ts > 1000000000000:  # миллисекунды
                    dt = datetime.fromtimestamp(ts / 1000)
                else:
                    dt = datetime.fromtimestamp(ts)
                times.append(dt)
                opens.append(float(candle.get('open', 0)))
                closes.append(float(candle.get('close', 0)))
                highs.append(float(candle.get('high', 0)))
                lows.append(float(candle.get('low', 0)))
                volumes.append(float(candle.get('vol', 0)))
        
            # Добавляем текущую цену как последнюю точку если есть
            if current_price and current_price > 0 and len(times) > 0:
                # Обновляем последнюю свечу
                closes[-1] = current_price
                if current_price > highs[-1]:
                    highs[-1] = current_price
                if current_price < lows[-1]:
                    lows[-1] = current_price
        
            # Настройка стиля
            plt.style.use('dark_background')
        
            # Создаём фигуру с двумя subplot (цена + объём)
            fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 8), 
                                            gridspec_kw={'height_ratios': [3, 1]},
                                            facecolor='#0d1117')
            ax1.set_facecolor('#0d1117')
            ax2.set_facecolor('#0d1117')
        
            # Цвета в зависимости от типа сигнала
            if signal_type == 'pump':
                main_color = '#00FF88'
                accent_color = '#00CC6A'
                glow_color = '#00FF8844'
                signal_emoji = '🚀'
                signal_text = 'PUMP'
            else:
                main_color = '#FF3366'
                accent_color = '#CC2952'
                glow_color = '#FF336644'
                signal_emoji = '💥'
                signal_text = 'DUMP'
        
            # ═══ РИСУЕМ СВЕЧИ ═══
            candle_width = 0.6
        
            for i in range(len(times)):
                # Определяем цвет свечи
                if closes[i] >= opens[i]:
                    candle_color = '#00FF88'  # Зелёная (рост)
                    edge_color = '#00CC6A'
                else:
                    candle_color = '#FF3366'  # Красная (падение)
                    edge_color = '#CC2952'
            
                # Тело свечи
                body_bottom = min(opens[i], closes[i])
                body_height = abs(closes[i] - opens[i])
                if body_height == 0:
                    body_height = closes[i] * 0.0001  # Минимальная высота
            
                # Рисуем тень (фитиль)
                ax1.plot([i, i], [lows[i], highs[i]], 
                        color=candle_color, linewidth=1.5, alpha=0.8)
            
                # Рисуем тело свечи
                from matplotlib.patches import Rectangle
                rect = Rectangle((i - candle_width/2, body_bottom), 
                                candle_width, body_height,
                                facecolor=candle_color, 
                                edgecolor=edge_color,
                                linewidth=1,
                                alpha=0.9)
                ax1.add_patch(rect)
        
            # ═══ ЗАЛИВКА ПОД ГРАФИКОМ ═══
            min_price = min(lows) * 0.9995
            ax1.fill_between(range(len(closes)), closes, min_price, 
                            alpha=0.15, color=main_color)
        
            # ═══ ПОДСВЕТКА ПОСЛЕДНЕЙ ТОЧКИ ═══
            last_idx = len(closes) - 1
            # Большой круг свечения
            ax1.scatter([last_idx], [closes[-1]], s=500, 
                    color=main_color, alpha=0.2, zorder=6)
            # Средний круг
            ax1.scatter([last_idx], [closes[-1]], s=200, 
                    color=main_color, alpha=0.4, zorder=7)
            # Основная точка
            ax1.scatter([last_idx], [closes[-1]], s=100, 
                    color=main_color, edgecolor='white', 
                    linewidth=2, zorder=8)
        
            # ═══ ГОРИЗОНТАЛЬНАЯ ЛИНИЯ ТЕКУЩЕЙ ЦЕНЫ ═══
            ax1.axhline(y=closes[-1], color=main_color, 
                    linestyle=':', alpha=0.5, linewidth=1)
        
            # ═══ АННОТАЦИЯ С ЦЕНОЙ ═══
            price_str = self.format_price(closes[-1])
        
            # Позиция аннотации
            ax1.annotate(f'${price_str}', 
                        xy=(last_idx, closes[-1]),
                        xytext=(last_idx + 0.5, closes[-1]),
                        fontsize=14,
                        fontweight='bold',
                        color=main_color,
                        va='center',
                        bbox=dict(boxstyle='round,pad=0.4', 
                                facecolor='#0d1117', 
                                edgecolor=main_color, 
                                alpha=0.95,
                                linewidth=2))
        
            # ═══ МИН/МАКС МЕТКИ ═══
            min_close = min(closes)
            max_close = max(closes)
            min_idx = closes.index(min_close)
            max_idx = closes.index(max_close)
        
            # Метка минимума
            ax1.annotate(f'MIN\n${self.format_price(min_close)}',
                        xy=(min_idx, min_close),
                        xytext=(min_idx, min_close - (max_close - min_close) * 0.15),
                        fontsize=9,
                        fontweight='bold',
                        color='#FF6B6B',
                        ha='center',
                        va='top',
                        bbox=dict(boxstyle='round,pad=0.3', 
                                facecolor='#1a1a2e', 
                                edgecolor='#FF6B6B', 
                                alpha=0.9))
        
            # Метка максимума
            ax1.annotate(f'MAX\n${self.format_price(max_close)}',
                        xy=(max_idx, max_close),
                        xytext=(max_idx, max_close + (max_close - min_close) * 0.1),
                        fontsize=9,
                        fontweight='bold',
                        color='#4ECDC4',
                        ha='center',
                        va='bottom',
                        bbox=dict(boxstyle='round,pad=0.3', 
                                facecolor='#1a1a2e', 
                                edgecolor='#4ECDC4', 
                                alpha=0.9))
        
            # ═══ ОБЪЁМЫ (нижний график) ═══
            colors = ['#00FF88' if closes[i] >= opens[i] else '#FF3366' 
                    for i in range(len(closes))]
            ax2.bar(range(len(volumes)), volumes, color=colors, alpha=0.7, width=0.8)
        
            # ═══ ЗАГОЛОВОК ═══
            display_symbol = symbol.replace('_', '')
            change_str = f'+{change_percent:.2f}%' if change_percent > 0 else f'{change_percent:.2f}%'
        
            title = f'{signal_emoji} {display_symbol}  |  {signal_text}  |  {self.timeframe_display}  |  {change_str}'
            ax1.set_title(title, fontsize=20, fontweight='bold', 
                        color='white', pad=20, loc='center')
        
            # ═══ НАСТРОЙКА ОСЕЙ ═══
            # Ось X - время
            time_labels = [t.strftime('%H:%M') for t in times]
        
            # Показываем только некоторые метки
            step = max(1, len(times) // 8)
            tick_positions = list(range(0, len(times), step))
            tick_labels = [time_labels[i] for i in tick_positions]
        
            ax1.set_xticks(tick_positions)
            ax1.set_xticklabels([])  # Убираем метки с верхнего графика
            ax2.set_xticks(tick_positions)
            ax2.set_xticklabels(tick_labels, fontsize=10, color='#888888', rotation=45)
        
            # Ось Y
            ax1.set_ylabel('Цена (USDT)', fontsize=11, color='#888888', labelpad=10)
            ax2.set_ylabel('Объём', fontsize=10, color='#888888', labelpad=10)
        
            # Настройка границ
            price_range = max_close - min_close
            ax1.set_ylim(min_close - price_range * 0.2, max_close + price_range * 0.25)
            ax1.set_xlim(-0.5, len(closes) + 1)
            ax2.set_xlim(-0.5, len(closes) + 1)
        
            # Цвет меток
            ax1.tick_params(colors='#888888', labelsize=10)
            ax2.tick_params(colors='#888888', labelsize=9)
        
            # ═══ СЕТКА ═══
            ax1.grid(True, alpha=0.1, color='white', linestyle='-', linewidth=0.5)
            ax1.grid(True, which='minor', alpha=0.05)
            ax2.grid(True, alpha=0.1, color='white', linestyle='-', linewidth=0.5)
        
            # ═══ РАМКИ ═══
            for ax in [ax1, ax2]:
                for spine in ax.spines.values():
                    spine.set_color('#333333')
                    spine.set_linewidth(1)
        
            # ═══ ИНФОРМАЦИОННАЯ ПАНЕЛЬ ═══
            info_text = f'Open: ${self.format_price(opens[0])}  |  Close: ${self.format_price(closes[-1])}  |  High: ${self.format_price(max(highs))}  |  Low: ${self.format_price(min(lows))}'
            fig.text(0.5, 0.02, info_text, fontsize=10, color='#666666',
                    ha='center', va='bottom')
        
            # ═══ ВОДЯНОЙ ЗНАК ═══
            fig.text(0.99, 0.01, '👑 KING SCREENER', fontsize=11, 
                    color='#333333', ha='right', va='bottom', 
                    fontweight='bold', alpha=0.7)
        
            # ═══ ВРЕМЯ ГЕНЕРАЦИИ ═══
            gen_time = datetime.now().strftime('%H:%M:%S')
            fig.text(0.01, 0.01, f'🕐 {gen_time}', fontsize=9, 
                    color='#444444', ha='left', va='bottom')
        
            # Оптимизация расположения
            plt.tight_layout()
            plt.subplots_adjust(bottom=0.08, hspace=0.05)
        
            # ═══ СОХРАНЕНИЕ В БУФЕР ═══
            buf = io.BytesIO()
            plt.savefig(buf, format='png', dpi=120, 
                    facecolor='#0d1117', edgecolor='none',
                    bbox_inches='tight', pad_inches=0.2)
            buf.seek(0)
            plt.close(fig)
        
            return buf
        
        except Exception as e:
            print(f"❌ Chart generation error: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    # ═══════════════════════════════════════════════════════════════
    # PRICE ALERTS
    # ═══════════════════════════════════════════════════════════════
    
    def add_price_alert(self, symbol, condition, target_price, market_type):
        chat_id = self.chat_id
        if chat_id not in self.price_alerts:
            self.price_alerts[chat_id] = []
        if len(self.price_alerts[chat_id]) >= self.max_alerts_per_user:
            return False, "Достигнут лимит алертов"
        for alert in self.price_alerts[chat_id]:
            if alert['symbol'] == symbol and alert['condition'] == condition and alert['target_price'] == target_price:
                return False, "Такой алерт уже существует"
        self.price_alerts[chat_id].append({
            'symbol': symbol, 'condition': condition, 'target_price': target_price,
            'market_type': market_type, 'created_at': time.time(), 'triggered': False
        })
        self._save_price_alerts()
        return True, "Алерт создан"
    
    def remove_price_alert(self, index):
        chat_id = self.chat_id
        if chat_id in self.price_alerts and 0 <= index < len(self.price_alerts[chat_id]):
            removed = self.price_alerts[chat_id].pop(index)
            self._save_price_alerts()
            return True, removed
        return False, None
    
    def clear_price_alerts(self):
        chat_id = self.chat_id
        if chat_id in self.price_alerts:
            count = len(self.price_alerts[chat_id])
            self.price_alerts[chat_id] = []
            self._save_price_alerts()
            return count
        return 0
    
    def get_user_alerts(self):
        return self.price_alerts.get(self.chat_id, [])
    
    def _save_price_alerts(self):
        try:
            all_alerts = {}
            if os.path.exists('price_alerts.json'):
                try:
                    with open('price_alerts.json', 'r', encoding='utf-8') as f:
                        content = f.read().strip()
                        if content:
                            all_alerts = json.loads(content)
                except:
                    pass
            
            if self.chat_id in self.price_alerts:
                all_alerts[str(self.chat_id)] = self.price_alerts[self.chat_id]
            
            with open('price_alerts.json', 'w', encoding='utf-8') as f:
                json.dump(all_alerts, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"❌ Ошибка сохранения алертов: {e}")
    
    def _load_price_alerts(self):
        try:
            if os.path.exists('price_alerts.json'):
                with open('price_alerts.json', 'r', encoding='utf-8') as f:
                    content = f.read().strip()
                    if content:
                        data = json.loads(content)
                        if str(self.chat_id) in data:
                            self.price_alerts[self.chat_id] = data[str(self.chat_id)]
                        print(f"✅ Загружено алертов для {self.chat_id}: {len(self.price_alerts.get(self.chat_id, []))}")
        except Exception as e:
            print(f"❌ Ошибка загрузки алертов: {e}")
    
    def get_current_price(self, symbol, market_type):
        try:
            if market_type == 'futures':
                tickers = self.get_futures_tickers(use_cache=True)
                if symbol in tickers:
                    return float(tickers[symbol].get('lastPrice', 0))
            else:
                tickers = self.get_spot_tickers(use_cache=True)
                if symbol in tickers:
                    return float(tickers[symbol].get('lastPrice', 0))
        except:
            pass
        return None
    
    def check_price_alerts(self):
        chat_id = self.chat_id
        triggered = []
        if chat_id not in self.price_alerts:
            return triggered
        alerts_to_remove = []
        for i, alert in enumerate(self.price_alerts[chat_id]):
            if alert.get('triggered'):
                continue
            current_price = self.get_current_price(alert['symbol'], alert['market_type'])
            if current_price is None:
                continue
            condition_met = False
            if alert['condition'] == 'above' and current_price >= alert['target_price']:
                condition_met = True
            elif alert['condition'] == 'below' and current_price <= alert['target_price']:
                condition_met = True
            if condition_met:
                triggered.append({
                    'symbol': alert['symbol'], 'condition': alert['condition'],
                    'target_price': alert['target_price'], 'current_price': current_price,
                    'market_type': alert['market_type']
                })
                alerts_to_remove.append(i)
        for i in reversed(alerts_to_remove):
            self.price_alerts[chat_id].pop(i)
        if alerts_to_remove:
            self._save_price_alerts()
        return triggered
    
    def format_price_alert_notification(self, alert_data):
        symbol = alert_data['symbol']
        condition = "ВЫШЕ" if alert_data['condition'] == 'above' else "НИЖЕ"
        condition_icon = "📈" if alert_data['condition'] == 'above' else "📉"
        target = self.format_price(alert_data['target_price'])
        current = self.format_price(alert_data['current_price'])
        market_icon = "🔮" if alert_data['market_type'] == 'futures' else "💱"
        return f"""━━━━━━━━━━━━━━━━━━━━━━━━━━━
🎯 PRICE ALERT! 🎯
━━━━━━━━━━━━━━━━━━━━━━━━━━━

{market_icon} {symbol}

{condition_icon} Цена достигла ${target}!
💰 Текущая: ${current}

📊 Ваша цель: ${target}
✅ Условие: {condition}

━━━━━━━━━━━━━━━━━━━━━━━━━━━
👑 Admin: {ADMIN_LINK}
━━━━━━━━━━━━━━━━━━━━━━━━━━━"""
    
    # ═══════════════════════════════════════════════════════════════
    # АНАЛИТИКА
    # ═══════════════════════════════════════════════════════════════
    
    def add_to_history(self, signal_data):
        self.signal_history.append({
            'symbol': signal_data.get('symbol', ''),
            'display_symbol': signal_data.get('display_symbol', ''),
            'signal_type': signal_data.get('signal_type', ''),
            'change': signal_data.get('change_percent', 0),
            'volume_24h': signal_data.get('volume_24h', 0),
            'volume_usdt': signal_data.get('volume_usdt', 0),
            'market_type': signal_data.get('market_type', ''),
            'timeframe': signal_data.get('timeframe', ''),
            'timestamp': time.time(),
            'is_closed': signal_data.get('is_closed', False)
        })
        if len(self.signal_history) > self.max_history:
            self.signal_history = self.signal_history[-self.max_history:]
        today = datetime.now().strftime('%Y-%m-%d')
        self.daily_signal_count[today] = self.daily_signal_count.get(today, 0) + 1
    
    def get_analytics(self, hours=24):
        cutoff = time.time() - (hours * 3600)
        signals = [s for s in self.signal_history if s['timestamp'] >= cutoff]
        if not signals:
            return None
        total = len(signals)
        pumps = [s for s in signals if s['signal_type'] == 'pump']
        dumps = [s for s in signals if s['signal_type'] == 'dump']
        avg_change = sum(abs(s['change']) for s in signals) / total if total > 0 else 0
        best_pump = max(signals, key=lambda x: x['change']) if signals else None
        worst_dump = min(signals, key=lambda x: x['change']) if signals else None
        max_volume = max(signals, key=lambda x: x['volume_24h']) if signals else None
        futures_signals = [s for s in signals if s['market_type'] == 'futures']
        spot_signals = [s for s in signals if s['market_type'] == 'spot']
        tf_stats = {}
        for s in signals:
            tf = s.get('timeframe', 'unknown')
            if tf not in tf_stats:
                tf_stats[tf] = {'count': 0, 'total_change': 0}
            tf_stats[tf]['count'] += 1
            tf_stats[tf]['total_change'] += abs(s['change'])
        coin_stats = {}
        for s in signals:
            sym = s.get('display_symbol', s.get('symbol', ''))
            if sym not in coin_stats:
                coin_stats[sym] = {'count': 0, 'total_change': 0, 'market_type': s['market_type']}
            coin_stats[sym]['count'] += 1
            coin_stats[sym]['total_change'] += abs(s['change'])
        top_coins = sorted(coin_stats.items(), key=lambda x: x[1]['count'], reverse=True)[:5]
        time_activity = {0: 0, 6: 0, 12: 0, 18: 0}
        for s in signals:
            hour = datetime.fromtimestamp(s['timestamp']).hour
            period = (hour // 6) * 6
            time_activity[period] += 1
        return {
            'total': total, 'pumps': len(pumps), 'dumps': len(dumps), 'avg_change': avg_change,
            'best_pump': best_pump, 'worst_dump': worst_dump, 'max_volume': max_volume,
            'futures_count': len(futures_signals), 'spot_count': len(spot_signals),
            'tf_stats': tf_stats, 'top_coins': top_coins, 'time_activity': time_activity, 'hours': hours
        }
    
    def format_analytics(self, analytics):
        if not analytics:
            return "❌ Нет данных за этот период"
        hours = analytics['hours']
        period_name = {1: "1Ч", 6: "6Ч", 24: "24Ч", 168: "7 ДНЕЙ"}.get(hours, f"{hours}Ч")
        total = analytics['total']
        pumps = analytics['pumps']
        dumps = analytics['dumps']
        pump_pct = (pumps / total * 100) if total > 0 else 0
        dump_pct = (dumps / total * 100) if total > 0 else 0
        msg = f"""📈 АНАЛИТИКА ЗА {period_name}
━━━━━━━━━━━━━━━━━━━━━━━━

📊 ОБЩАЯ СТАТИСТИКА:
├ Всего сигналов: {total}
├ 🚀 PUMP: {pumps} ({pump_pct:.0f}%)
├ 💥 DUMP: {dumps} ({dump_pct:.0f}%)
└ Средний %: ±{analytics['avg_change']:.1f}%

💎 РЕКОРДЫ:"""
        if analytics['best_pump']:
            bp = analytics['best_pump']
            msg += f"\n├ 🚀 Лучший: +{bp['change']:.1f}% {bp['display_symbol']}"
        if analytics['worst_dump']:
            wd = analytics['worst_dump']
            msg += f"\n├ 💀 Худший: {wd['change']:.1f}% {wd['display_symbol']}"
        if analytics['max_volume']:
            mv = analytics['max_volume']
            msg += f"\n└ 💰 Макс объём: ${self.format_number(mv['volume_24h'])} {mv['display_symbol']}"
        fut = analytics['futures_count']
        spt = analytics['spot_count']
        fut_pct = (fut / total * 100) if total > 0 else 0
        spt_pct = (spt / total * 100) if total > 0 else 0
        msg += f"""

🏪 ПО РЫНКАМ:
├ 🔮 Futures: {fut} ({fut_pct:.0f}%)
└ 💱 Spot: {spt} ({spt_pct:.0f}%)

━━━━━━━━━━━━━━━━━━━━━━━━"""
        return msg
    
    def get_today_signal_count(self):
        today = datetime.now().strftime('%Y-%m-%d')
        return self.daily_signal_count.get(today, 0)

    # ═══════════════════════════════════════════════════════════════
    # MARKET DATA
    # ═══════════════════════════════════════════════════════════════
    
    def get_funding_rates(self):
        funding = {}
        try:
            response = requests.get(f"{self.base_url}/api/v1/contract/funding_rate",
                                   headers=self.headers, timeout=15)
            if response.status_code == 200:
                data = response.json()
                if data.get('success'):
                    for item in data.get('data', []):
                        symbol = item.get('symbol')
                        rate = float(item.get('fundingRate', 0))
                        funding[symbol] = rate * 100
        except Exception as e:
            print(f"Funding error: {e}")
        return funding
    
    def get_futures_symbols(self):
        symbols = {}
        print(f"   🔍 [{self.chat_id}] Сбор ВСЕХ деривативов MEXC...")
        try:
            response = requests.get(f"{self.base_url}/api/v1/contract/detail", 
                                   headers=self.headers, timeout=30)
            if response.status_code == 200:
                data = response.json()
                if data.get('success'):
                    for item in data.get('data', []):
                        symbol = item.get('symbol')
                        if symbol:
                            symbols[symbol] = {'symbol': symbol, 'state': item.get('state', 0)}
            print(f"      📋 Contract detail: {len(symbols)}")
        except Exception as e:
            print(f"      ❌ Contract detail error: {e}")
        try:
            response = requests.get(f"{self.base_url}/api/v1/contract/ticker",
                                   headers=self.headers, timeout=30)
            if response.status_code == 200:
                data = response.json()
                if data.get('success'):
                    for item in data.get('data', []):
                        symbol = item.get('symbol')
                        if symbol and symbol not in symbols:
                            symbols[symbol] = {'symbol': symbol, 'type': 'from_ticker', 'state': 0}
            print(f"      📊 После тикеров: {len(symbols)}")
        except Exception as e:
            print(f"      ❌ Ticker error: {e}")
        active_symbols = []
        for sym, info in symbols.items():
            if info.get('state', 0) == 0 or info.get('type') in ['from_ticker', 'perpetual']:
                active_symbols.append(sym)
        print(f"   ✅ ИТОГО деривативов: {len(active_symbols)}")
        return active_symbols
    
    def get_spot_symbols(self):
        symbols = {}
        print(f"   🔍 [{self.chat_id}] Сбор ВСЕХ спот пар MEXC...")
        
        try:
            response = requests.get(f"{self.spot_url}/api/v3/exchangeInfo",
                                   headers=self.headers, timeout=60)
            if response.status_code == 200:
                data = response.json()
                for item in data.get('symbols', []):
                    sym = item.get('symbol', '')
                    status = item.get('status', '')
                    if status == 'TRADING' and sym:
                        symbols[sym] = {'symbol': sym, 'status': status}
                print(f"      📋 ExchangeInfo: {len(symbols)}")
        except Exception as e:
            print(f"      ❌ ExchangeInfo error: {e}")
        
        if self.spot_quote_filter != "all":
            quote_upper = self.spot_quote_filter.upper()
            filtered = {k: v for k, v in symbols.items() if k.endswith(quote_upper)}
            print(f"   ✅ ИТОГО спот (фильтр {quote_upper}): {len(filtered)}")
            return list(filtered.keys())
        
        print(f"   ✅ ИТОГО спот: {len(symbols)}")
        return list(symbols.keys())
    
    def get_all_symbols(self, force_reload=False):
        if not force_reload and self.all_symbols and (time.time() - self.last_update) < 300:
            return self._filter_symbols()
        print("=" * 50)
        print(f"📊 [{self.chat_id}] ЗАГРУЗКА ВСЕХ ТОРГОВЫХ ПАР MEXC")
        print("=" * 50)
        self.futures_symbols = self.get_futures_symbols()
        self.spot_symbols = self.get_spot_symbols()
        self.funding_rates = self.get_funding_rates()
        print(f"   💰 Funding rates: {len(self.funding_rates)}")
        self.all_symbols = []
        for sym in self.futures_symbols:
            self.all_symbols.append({'symbol': sym, 'type': 'futures', 'display': sym.replace('_', '')})
        for sym in self.spot_symbols:
            self.all_symbols.append({'symbol': sym, 'type': 'spot', 'display': sym})
        self.last_update = time.time()
        print("=" * 50)
        print(f"📊 ИТОГО: {len(self.futures_symbols)} деривативов + {len(self.spot_symbols)} спот = {len(self.all_symbols)} пар")
        print("=" * 50)
        return self._filter_symbols()
    
    def _filter_symbols(self):
        if self.market_type_filter == "futures":
            return [s for s in self.all_symbols if s['type'] == 'futures']
        elif self.market_type_filter == "spot":
            return [s for s in self.all_symbols if s['type'] == 'spot']
        return self.all_symbols
    
    def get_futures_tickers(self, use_cache=False):
        if use_cache and self.cached_futures_tickers and (time.time() - self.tickers_cache_time) < 10:
            return self.cached_futures_tickers
        tickers = {}
        try:
            response = requests.get(f"{self.base_url}/api/v1/contract/ticker",
                                   headers=self.headers, timeout=30)
            if response.status_code == 200:
                data = response.json()
                if data.get('success'):
                    for item in data.get('data', []):
                        tickers[item['symbol']] = item
            self.cached_futures_tickers = tickers
            self.tickers_cache_time = time.time()
        except:
            pass
        return tickers
    
    def get_spot_tickers(self, use_cache=False):
        if use_cache and self.cached_spot_tickers and (time.time() - self.tickers_cache_time) < 10:
            return self.cached_spot_tickers
        tickers = {}
        try:
            response = requests.get(f"{self.spot_url}/api/v3/ticker/24hr",
                                   headers=self.headers, timeout=60)
            if response.status_code == 200:
                for item in response.json():
                    tickers[item['symbol']] = item
            self.cached_spot_tickers = tickers
            self.tickers_cache_time = time.time()
        except:
            pass
        return tickers
    
    def get_futures_klines(self, symbol, limit=5):
        try:
            url = f"{self.base_url}/api/v1/contract/kline/{symbol}"
            params = {'interval': self.timeframe, 'limit': limit}
            response = requests.get(url, params=params, headers=self.headers, timeout=5)
            if response.status_code == 200:
                data = response.json()
                if data.get('success') and data.get('data'):
                    kdata = data['data']
                    if isinstance(kdata, dict) and 'time' in kdata:
                        candles = []
                        times = kdata.get('time', [])
                        for i in range(len(times)):
                            candles.append({
                                'time': times[i],
                                'open': float(kdata['open'][i]) if i < len(kdata.get('open', [])) else 0,
                                'high': float(kdata['high'][i]) if i < len(kdata.get('high', [])) else 0,
                                'low': float(kdata['low'][i]) if i < len(kdata.get('low', [])) else 0,
                                'close': float(kdata['close'][i]) if i < len(kdata.get('close', [])) else 0,
                                'vol': float(kdata['vol'][i]) if i < len(kdata.get('vol', [])) else 0
                            })
                        return candles
        except:
            pass
        return None
    
    def get_spot_klines(self, symbol, limit=5):
        try:
            interval = self.spot_tf_map.get(self.timeframe_display, '5m')
            url = f"{self.spot_url}/api/v3/klines"
            params = {'symbol': symbol, 'interval': interval, 'limit': limit}
            response = requests.get(url, params=params, headers=self.headers, timeout=5)
            if response.status_code == 200:
                data = response.json()
                candles = []
                for k in data:
                    candles.append({
                        'time': k[0], 'open': float(k[1]), 'high': float(k[2]),
                        'low': float(k[3]), 'close': float(k[4]), 'vol': float(k[5])
                    })
                return candles
        except:
            pass
        return None
    
    def is_candle_closed(self, candle_time):
        tf_seconds = self.tf_seconds.get(self.timeframe_display, 300)
        candle_end_time = candle_time + (tf_seconds * 1000)
        current_time = int(time.time() * 1000)
        return current_time >= candle_end_time
    
    def get_time_until_close(self, candle_time):
        tf_seconds = self.tf_seconds.get(self.timeframe_display, 300)
        candle_end_time = candle_time + (tf_seconds * 1000)
        current_time = int(time.time() * 1000)
        remaining = (candle_end_time - current_time) / 1000
        return max(0, remaining)
    
    def analyze_context(self, klines, current_idx):
        if not klines or len(klines) < 2:
            return {'prev_change': 0, 'impulse_series': 1}
        klines_sorted = sorted(klines, key=lambda x: x.get('time', 0))
        actual_idx = len(klines_sorted) + current_idx if current_idx < 0 else current_idx
        prev_change = 0
        if actual_idx > 0:
            prev = klines_sorted[actual_idx - 1]
            if prev.get('open', 0) > 0:
                prev_change = ((prev.get('close', 0) - prev.get('open', 0)) / prev.get('open', 0)) * 100
        impulse_series = 1
        current = klines_sorted[actual_idx]
        current_change = 0
        if current.get('open', 0) > 0:
            current_change = ((current.get('close', 0) - current.get('open', 0)) / current.get('open', 0)) * 100
        is_pump = current_change > 0
        for i in range(actual_idx - 1, max(actual_idx - 5, -1), -1):
            if i >= 0:
                candle = klines_sorted[i]
                if candle.get('open', 0) > 0:
                    change = ((candle.get('close', 0) - candle.get('open', 0)) / candle.get('open', 0)) * 100
                    if is_pump and change >= self.min_pump * 0.5:
                        impulse_series += 1
                    elif not is_pump and change <= -self.min_dump * 0.5:
                        impulse_series += 1
                    else:
                        break
        return {'prev_change': prev_change, 'impulse_series': impulse_series}
    
    def calculate_liquidity_score(self, volume_24h, spread):
        score = 0
        if volume_24h >= 1000000: score += 50
        elif volume_24h >= 100000: score += 35
        elif volume_24h >= 10000: score += 20
        elif volume_24h >= 1000: score += 10
        if spread is not None:
            if spread < 0.1: score += 50
            elif spread < 0.5: score += 35
            elif spread < 1: score += 20
            elif spread < 2: score += 10
        else:
            score += 25
        return min(score, 100)
    
    def should_send_alert(self, symbol, candle_time, is_closed):
        current_time = time.time()
        key = f"{symbol}_{self.timeframe}_{candle_time}" if is_closed else f"{symbol}_{self.timeframe}_live"
        if self.allow_duplicates:
            if key in self.sent_alerts:
                last_time, last_candle = self.sent_alerts[key]
                if not is_closed:
                    if (current_time - last_time) >= self.alert_cooldown:
                        self.sent_alerts[key] = (current_time, candle_time)
                        return True
                    return False
                if candle_time != last_candle or (current_time - last_time) >= self.alert_cooldown:
                    self.sent_alerts[key] = (current_time, candle_time)
                    return True
                return False
            else:
                self.sent_alerts[key] = (current_time, candle_time)
                return True
        else:
            full_key = f"{symbol}_{candle_time}_{self.timeframe}"
            if full_key in self.sent_alerts:
                return False
            self.sent_alerts[full_key] = True
            return True
    
    def analyze_symbol(self, symbol_info, futures_tickers, spot_tickers):
        symbol = symbol_info['symbol']
        market_type = symbol_info['type']
        
        if market_type == 'futures':
            klines = self.get_futures_klines(symbol)
            ticker = futures_tickers.get(symbol, {})
        else:
            klines = self.get_spot_klines(symbol)
            ticker = spot_tickers.get(symbol, {})
        
        if not klines or len(klines) < 2:
            return None
        
        results = []
        try:
            klines_sorted = sorted(klines, key=lambda x: x.get('time', 0))
            
            candles_to_check = []
            if self.candle_mode == "current":
                candles_to_check = [(-1, False)]
            elif self.candle_mode == "closed":
                last = klines_sorted[-1]
                if self.is_candle_closed(last['time']):
                    candles_to_check = [(-1, True)]
                elif len(klines_sorted) >= 2:
                    candles_to_check = [(-2, True)]
            else:
                candles_to_check = [(-1, False)]
                if len(klines_sorted) >= 2:
                    candles_to_check.append((-2, True))
            
            realtime_price = float(ticker.get('lastPrice', 0) or 0)
            
            for idx, force_closed in candles_to_check:
                if len(klines_sorted) >= abs(idx):
                    candle = klines_sorted[idx]
                    
                    open_price = candle.get('open', 0)
                    close_price = candle.get('close', 0)
                    high_price = candle.get('high', 0)
                    low_price = candle.get('low', 0)
                    volume = candle.get('vol', 0)
                    candle_time = candle.get('time', 0)
                    
                    if open_price <= 0:
                        continue
                    
                    is_closed = force_closed or self.is_candle_closed(candle_time)
                    
                    if not is_closed and realtime_price > 0:
                        effective_close = realtime_price
                        if realtime_price > high_price:
                            high_price = realtime_price
                        if realtime_price < low_price:
                            low_price = realtime_price
                    else:
                        effective_close = close_price
                    
                    change = ((effective_close - open_price) / open_price) * 100
                    
                    is_pump = change >= self.min_pump
                    is_dump = change <= -self.min_dump
                    
                    if self.signal_mode == "pump" and not is_pump:
                        continue
                    elif self.signal_mode == "dump" and not is_dump:
                        continue
                    elif self.signal_mode == "both" and not (is_pump or is_dump):
                        continue
                    
                    if not (is_pump or is_dump):
                        continue
                    
                    time_remaining = 0 if is_closed else self.get_time_until_close(candle_time)
                    volume_usdt = volume * effective_close
                    
                    if market_type == 'futures':
                        vol24 = float(ticker.get('volume24', 0) or 0) * effective_close
                    else:
                        vol24 = float(ticker.get('quoteVolume', 0) or 0)
                    
                    if self.min_volume_usdt > 0 and vol24 < self.min_volume_usdt:
                        continue
                    
                    spread = None
                    if market_type == 'futures':
                        bid = float(ticker.get('bid1', 0) or 0)
                        ask = float(ticker.get('ask1', 0) or 0)
                        if bid > 0 and ask > 0:
                            spread = ((ask - bid) / bid) * 100
                    else:
                        bid = float(ticker.get('bidPrice', 0) or 0)
                        ask = float(ticker.get('askPrice', 0) or 0)
                        if bid > 0 and ask > 0:
                            spread = ((ask - bid) / bid) * 100
                    
                    funding_rate = self.funding_rates.get(symbol, None)
                    context = self.analyze_context(klines_sorted, idx)
                    liquidity_score = self.calculate_liquidity_score(vol24, spread)
                    signal_type = "pump" if is_pump else "dump"
                    current_price = realtime_price if realtime_price > 0 else effective_close
                    
                    results.append({
                        'symbol': symbol,
                        'display_symbol': symbol_info['display'],
                        'market_type': market_type,
                        'signal_type': signal_type,
                        'open_price': open_price,
                        'close_price': effective_close,
                        'current_price': current_price,
                        'high_price': high_price,
                        'low_price': low_price,
                        'change_percent': change,
                        'volume': volume,
                        'volume_usdt': volume_usdt,
                        'volume_24h': vol24,
                        'spread': spread,
                        'funding_rate': funding_rate,
                        'candle_time': candle_time,
                        'timeframe': self.timeframe_display,
                        'prev_change': context['prev_change'],
                        'impulse_series': context['impulse_series'],
                        'liquidity_score': liquidity_score,
                        'is_closed': is_closed,
                        'time_remaining': time_remaining,
                        'klines': klines_sorted
                    })
            
            return results if results else None
        except Exception as e:
            return None
    
    def format_alert(self, data):
        symbol = data['display_symbol']
        market_type = "Futures" if data['market_type'] == 'futures' else "Spot"
        signal_type = data['signal_type']
        is_closed = data.get('is_closed', True)
        open_price = self.format_price(data['open_price'])
        close_price = self.format_price(data['close_price'])
        current_price = self.format_price(data.get('current_price', data['close_price']))
        change = data['change_percent']
        volume = data['volume']
        vol_usdt = self.format_number(data['volume_usdt'])
        vol_24h = self.format_number(data['volume_24h'])
        spread = data['spread']
        funding = data.get('funding_rate')
        tf = data['timeframe']
        prev_change = data.get('prev_change', 0)
        impulse_series = data.get('impulse_series', 1)
        liq_score = data.get('liquidity_score', 50)
        
        market_icon = "🔮" if market_type == "Futures" else "💱"
        candle_status = "CLOSED" if is_closed else "LIVE"
        
        if signal_type == "pump":
            header = f"🟢 [MEXC] ONE-CANDLE PUMP | {candle_status} | 🟢"
            change_icon = "🟢"
            change_str = f"+{change:.2f}%"
        else:
            header = f"🔴 [MEXC] ONE-CANDLE DUMP | {candle_status} | 🔴"
            change_icon = "🔴"
            change_str = f"{change:.2f}%"
        
        if volume >= 1_000_000_000:
            vol_coins = f"{volume/1_000_000_000:.1f}B"
        elif volume >= 1_000_000:
            vol_coins = f"{volume/1_000_000:.1f}M"
        elif volume >= 1_000:
            vol_coins = f"{volume/1_000:.1f}K"
        else:
            vol_coins = f"{volume:.0f}"
        
        if spread is not None:
            if spread > 2:
                spread_text = f"{spread:.2f}% ⚠️ (Высокий!)"
            elif spread > 1:
                spread_text = f"{spread:.2f}% ⚡ (Средний)"
            else:
                spread_text = f"{spread:.2f}% ✅"
        else:
            spread_text = "N/A"
        
        if impulse_series == 1:
            series_text = "1 импульсная свеча"
        elif impulse_series < 5:
            series_text = f"{impulse_series} импульсных свечи"
        else:
            series_text = f"{impulse_series} импульсных свечей"
        
        if liq_score >= 70:
            liq_icon = "🟢"
        elif liq_score >= 40:
            liq_icon = "🟡"
        else:
            liq_icon = "🔴"
        
        msg = f"""━━━━━━━━━━━━━━━━━━━━━━━━━━
{header}
━━━━━━━━━━━━━━━━━━━━━━━━━━

{market_icon} Пара: {symbol} ({market_type})
⏱ ТФ: {tf} | Изм: {change_str} {change_icon}
💰 Цена: {open_price} ➔ {close_price}
💰 Текущая цена: {current_price}

📊 Объемы и Риск:
• Объём свечи: ${vol_usdt} ({vol_coins} монет)
• Объём 24h: ${vol_24h}
• Спред: {spread_text}

⚙️ Тех. Детали:
• Серия: {series_text}
• Контекст: пред. свеча {prev_change:+.1f}%"""
        
        if data['market_type'] == 'futures' and funding is not None:
            msg += f"\n• Funding: {funding:+.4f}%"
        
        msg += f"""
• Ликвидность: {liq_score}% {liq_icon}

━━━━━━━━━━━━━━━━━━━━━━━━━━
👑 Admin: {ADMIN_LINK}"""
        return msg
    
    def set_timeframe(self, tf):
        if tf in self.tf_map:
            self.timeframe = self.tf_map[tf]
            self.timeframe_display = tf
            return True
        return False
    
    def get_volume_reliability(self, volume_24h):
        if volume_24h >= 10_000_000:
            return "🟢🟢🟢 Высокая"
        elif volume_24h >= 1_000_000:
            return "🟢🟢 Хорошая"
        elif volume_24h >= 100_000:
            return "🟢 Средняя"
        elif volume_24h >= 10_000:
            return "🟡 Низкая"
        else:
            return "🔴 Очень низкая"
    
    def get_top_movers(self, period="24h", limit=10, mode="gainers", progress_callback=None):
        results = []
        period_names = {
            "1m": "1 минуту", "5m": "5 минут", "15m": "15 минут",
            "30m": "30 минут", "1h": "1 час", "4h": "4 часа", "24h": "24 часа"
        }
        period_name = period_names.get(period, period)
        futures_tickers = self.get_futures_tickers() if self.market_type_filter in ["all", "futures"] else {}
        spot_tickers = self.get_spot_tickers() if self.market_type_filter in ["all", "spot"] else {}
        
        if period == "24h":
            for sym, data in futures_tickers.items():
                try:
                    change = float(data.get('riseFallRate', 0)) * 100
                    price = float(data.get('lastPrice', 0))
                    vol = float(data.get('volume24', 0)) * price
                    if self.min_volume_usdt > 0 and vol < self.min_volume_usdt:
                        continue
                    results.append({
                        'symbol': sym.replace('_', ''), 'type': 'futures', 'type_icon': '🔮',
                        'change': change, 'volume': vol, 'price': price,
                        'funding': self.funding_rates.get(sym), 'reliability': self.get_volume_reliability(vol)
                    })
                except:
                    continue
            
            for sym, data in spot_tickers.items():
                try:
                    change = float(data.get('priceChangePercent', 0))
                    vol = float(data.get('quoteVolume', 0) or 0)
                    price = float(data.get('lastPrice', 0) or 0)
                    if self.min_volume_usdt > 0 and vol < self.min_volume_usdt:
                        continue
                    results.append({
                        'symbol': sym, 'type': 'spot', 'type_icon': '💱',
                        'change': change, 'volume': vol, 'price': price,
                        'funding': None, 'reliability': self.get_volume_reliability(vol)
                    })
                except:
                    continue
        
        if mode == "gainers":
            results = [r for r in results if r['change'] > 0]
            results.sort(key=lambda x: x['change'], reverse=True)
        else:
            results = [r for r in results if r['change'] < 0]
            results.sort(key=lambda x: x['change'])
        
        return results[:limit], period_name
    
    def scan(self):
        now = datetime.now().strftime('%H:%M:%S')
        mode_names = {"pump": "PUMP", "dump": "DUMP", "both": "PUMP+DUMP"}
        candle_names = {"current": "LIVE", "closed": "CLOSED", "both": "ALL"}
        all_symbols = self.get_all_symbols()
        
        if not all_symbols:
            print(f"[{now}] [{self.chat_id}] ❌ Нет пар")
            return
        
        fut = len([s for s in all_symbols if s['type'] == 'futures'])
        spot = len([s for s in all_symbols if s['type'] == 'spot'])
        print(f"[{now}] [{self.chat_id}] 🔍 {self.timeframe_display} | {mode_names[self.signal_mode]} | {candle_names[self.candle_mode]} | 🔮{fut} 💱{spot} | REST")
        
        futures_tickers = self.get_futures_tickers() if self.market_type_filter in ["all", "futures"] else {}
        spot_tickers = self.get_spot_tickers() if self.market_type_filter in ["all", "spot"] else {}
        signals = []
        errors = [0]
        
        def analyze(sym):
            try:
                return self.analyze_symbol(sym, futures_tickers, spot_tickers)
            except:
                errors[0] += 1
                return None
        
        with ThreadPoolExecutor(max_workers=30) as ex:
            for result in ex.map(analyze, all_symbols):
                if result:
                    for signal in result:
                        if self.should_send_alert(signal['symbol'], signal['candle_time'], signal['is_closed']):
                            signals.append(signal)
        
        signals.sort(key=lambda x: abs(x['change_percent']), reverse=True)
        
        for signal in signals:
            icon = "🚀" if signal['signal_type'] == 'pump' else "💥"
            status = "|LIVE|" if not signal['is_closed'] else "|CLOSED|"
            change_str = f"+{signal['change_percent']:.2f}%" if signal['signal_type'] == 'pump' else f"{signal['change_percent']:.2f}%"
            print(f"  [{self.chat_id}] {icon} {status} {signal['display_symbol']} {change_str}")
            self.add_to_history(signal)
            
            # ═══ ФОРМИРУЕМ ТЕКСТ СООБЩЕНИЯ ═══
            msg = self.format_alert(signal)
            
            # ═══ ОТПРАВКА С ГРАФИКОМ ИЛИ БЕЗ ═══
            if self.send_charts and self.send_telegram_photo:
                try:
                    if signal['market_type'] == 'futures':
                        chart_klines = self.get_futures_klines(signal['symbol'], limit=30)
                    else:
                        chart_klines = self.get_spot_klines(signal['symbol'], limit=30)
                    
                    if chart_klines and len(chart_klines) >= 2:
                        chart_buf = self.generate_chart(
                            signal['symbol'],
                            chart_klines,
                            signal['signal_type'],
                            signal.get('current_price'),
                            signal.get('change_percent', 0)
                        )
                        
                        if chart_buf:
                            # Отправляем фото с полным текстом как caption
                            self.send_telegram_photo(self.chat_id, chart_buf, msg)
                            chart_buf.close()
                        else:
                            # Если график не удалось создать - отправляем только текст
                            self.send_telegram(self.chat_id, msg)
                    else:
                        # Если нет данных для графика - отправляем только текст
                        self.send_telegram(self.chat_id, msg)
                except Exception as e:
                    print(f"  ❌ [{self.chat_id}] Chart error: {e}")
                    # При ошибке отправляем текст
                    self.send_telegram(self.chat_id, msg)
            else:
                # Графики отключены - отправляем только текст
                self.send_telegram(self.chat_id, msg)
            
            time.sleep(0.1)
        
        # Проверяем Price Alerts
        triggered_alerts = self.check_price_alerts()
        for alert in triggered_alerts:
            alert_msg = self.format_price_alert_notification(alert)
            self.send_telegram(self.chat_id, alert_msg)
            print(f"  [{self.chat_id}] 🎯 PRICE ALERT: {alert['symbol']} {alert['condition']} {alert['target_price']}")
            time.sleep(0.03)
        
        pumps = len([s for s in signals if s['signal_type'] == 'pump'])
        dumps = len([s for s in signals if s['signal_type'] == 'dump'])
        print(f"  [{self.chat_id}] ✅ 🚀{pumps} 💥{dumps} ❌{errors[0]}")
        
        if len(self.sent_alerts) > 5000:
            ct = time.time()
            self.sent_alerts = {k: v for k, v in self.sent_alerts.items() if isinstance(v, tuple) and (ct - v[0]) < 3600}
    
class TelegramBot:
    def __init__(self):
        self.token = TELEGRAM_BOT_TOKEN
        self.base_url = f"https://api.telegram.org/bot{self.token}"
        
        self.settings_manager = SettingsManager()
        
        self.subscription_manager = SubscriptionManager()

        self.user_screeners = {}
        self.user_threads = {}
        self.running_users = set()
        
        self.waiting_for_input = {}
        self.top_mode = {}
        self.last_menu_message = {}
        self.alert_creation_state = {}
        self.selected_alert_index = {}
        
        self.lock = threading.Lock()
    
    def get_screener(self, chat_id):
        with self.lock:
            if chat_id not in self.user_screeners:
                self.user_screeners[chat_id] = MEXCFullScreener(
                    self.send_message, 
                    chat_id, 
                    self.settings_manager,
                    self.send_photo
                )
            return self.user_screeners[chat_id]
    
    def send_message(self, chat_id, text, reply_markup=None):
        try:
            data = {'chat_id': chat_id, 'text': text, 'disable_web_page_preview': True}
            if reply_markup:
                data['reply_markup'] = json.dumps(reply_markup)
            response = requests.post(f"{self.base_url}/sendMessage", data=data, timeout=10)
            return response.json()
        except:
            return None
    
    def send_photo(self, chat_id, photo, caption=None):
        """Отправляет изображение с текстом в одном сообщении"""
        try:
            files = {'photo': ('chart.png', photo, 'image/png')}
            data = {'chat_id': chat_id}
            if caption:
                # Telegram лимит caption = 1024 символа
                data['caption'] = caption[:1024]
            
            response = requests.post(
                f"{self.base_url}/sendPhoto", 
                data=data, 
                files=files, 
                timeout=30
            )
            return response.json()
        except Exception as e:
            print(f"❌ Send photo error: {e}")
            return None
    
    def edit_message(self, chat_id, message_id, text, reply_markup=None):
        try:
            data = {'chat_id': chat_id, 'message_id': message_id, 'text': text, 'disable_web_page_preview': True}
            if reply_markup:
                data['reply_markup'] = json.dumps(reply_markup)
            response = requests.post(f"{self.base_url}/editMessageText", data=data, timeout=10)
            return response.json()
        except:
            return None
    
    def get_main_keyboard(self):
        return {"keyboard": [
            [{"text": "🚀 Старт"}, {"text": "🛑 Стоп"}, {"text": "📊 Статус"}],
            [{"text": "🔥 ТОП"}, {"text": "📈 Аналитика"}],
            [{"text": "🎯 Price Alerts"}, {"text": "📋 Пары"}],
            [{"text": "⚙️ Настройки"}, {"text": "💎 Подписка"}]
        ], "resize_keyboard": True}
    
    def get_top_mode_keyboard(self):
        return {"keyboard": [[{"text": "📈 ТОП Роста"}], [{"text": "📉 ТОП Падения"}], [{"text": "🔙 Главное меню"}]], "resize_keyboard": True}
    
    def get_top_period_keyboard(self):
        return {"keyboard": [[{"text": "⏱ 1m"}, {"text": "⏱ 5m"}, {"text": "⏱ 15m"}], [{"text": "⏱ 30m"}, {"text": "⏱ 1h"}, {"text": "⏱ 4h"}], [{"text": "⏱ 24h"}, {"text": "🔙 Назад"}]], "resize_keyboard": True}
    
    def get_settings_keyboard(self):
        return {"keyboard": [
            [{"text": "⏱ Таймфрейм"}, {"text": "💹 Мин. процент"}],
            [{"text": "🎯 Режим сигналов"}, {"text": "🕯 Режим свечей"}],
            [{"text": "🏪 Тип рынка"}, {"text": "💰 Мин. объём"}],
            [{"text": "🔄 Дубликаты"}, {"text": "⏰ Кулдаун"}, {"text": "⚡ Скорость"}],
            [{"text": "💱 Quote фильтр"}, {"text": "📊 Графики"}],
            [{"text": "🔙 Главное меню"}]
        ], "resize_keyboard": True}
    
    def get_charts_keyboard(self, screener):
        return {"keyboard": [
            [{"text": f"{'✅' if screener.send_charts else '⬜'} 📊 Графики ВКЛ"}],
            [{"text": f"{'✅' if not screener.send_charts else '⬜'} 📊 Графики ВЫКЛ"}],
            [{"text": "🔙 Настройки"}]
        ], "resize_keyboard": True}
    
    def get_quote_filter_keyboard(self, screener):
        c = screener.spot_quote_filter
        return {"keyboard": [[{"text": f"{'✅' if c == 'all' else '⬜'} 🌐 Все пары"}], [{"text": f"{'✅' if c == 'usdt' else '⬜'} 💵 Только USDT"}], [{"text": f"{'✅' if c == 'btc' else '⬜'} 🟠 Только BTC"}], [{"text": f"{'✅' if c == 'eth' else '⬜'} 🔷 Только ETH"}], [{"text": f"{'✅' if c == 'usdc' else '⬜'} 💲 Только USDC"}], [{"text": "🔙 Настройки"}]], "resize_keyboard": True}
    
    def get_signal_mode_keyboard(self, screener):
        c = screener.signal_mode
        return {"keyboard": [[{"text": f"{'✅' if c == 'pump' else '⬜'} 🚀 Только PUMP"}], [{"text": f"{'✅' if c == 'dump' else '⬜'} 💥 Только DUMP"}], [{"text": f"{'✅' if c == 'both' else '⬜'} 📊 PUMP + DUMP"}], [{"text": "🔙 Настройки"}]], "resize_keyboard": True}
    
    def get_candle_mode_keyboard(self, screener):
        c = screener.candle_mode
        return {"keyboard": [[{"text": f"{'✅' if c == 'current' else '⬜'} 🟡 Текущая |LIVE|"}], [{"text": f"{'✅' if c == 'closed' else '⬜'} ✅ Закрытая |CLOSED|"}], [{"text": f"{'✅' if c == 'both' else '⬜'} 📊 Обе"}], [{"text": "🔙 Настройки"}]], "resize_keyboard": True}
    
    def get_speed_keyboard(self, screener):
        c = screener.scan_interval
        return {"keyboard": [
            [{"text": f"{'✅' if c == 1 else '⬜'} ⚡ 1 сек"}, {"text": f"{'✅' if c == 2 else '⬜'} ⚡ 2 сек"}],
            [{"text": f"{'✅' if c == 3 else '⬜'} ⚡ 3 сек"}, {"text": f"{'✅' if c == 5 else '⬜'} ⚡ 5 сек"}],
            [{"text": f"{'✅' if c == 10 else '⬜'} ⚡ 10 сек"}, {"text": f"{'✅' if c == 15 else '⬜'} ⚡ 15 сек"}],
            [{"text": f"{'✅' if c == 30 else '⬜'} ⚡ 30 сек"}, {"text": f"{'✅' if c == 60 else '⬜'} ⚡ 60 сек"}],
            [{"text": "🔙 Настройки"}]
        ], "resize_keyboard": True}
    
    def get_timeframe_keyboard(self):
        return {"keyboard": [[{"text": "🕐 1m"}, {"text": "🕐 5m"}, {"text": "🕐 15m"}], [{"text": "🕐 30m"}, {"text": "🕐 1h"}, {"text": "🕐 4h"}], [{"text": "🕐 1d"}, {"text": "🔙 Настройки"}]], "resize_keyboard": True}
    
    def get_percent_keyboard(self):
        return {"keyboard": [[{"text": "📊 0.5%"}, {"text": "📊 1%"}, {"text": "📊 2%"}], [{"text": "📊 3%"}, {"text": "📊 5%"}, {"text": "📊 10%"}], [{"text": "📊 15%"}, {"text": "📊 20%"}, {"text": "✏️ Свой %"}], [{"text": "🔙 Настройки"}]], "resize_keyboard": True}
    
    def get_market_keyboard(self, screener):
        c = screener.market_type_filter
        return {"keyboard": [[{"text": f"{'✅' if c == 'all' else '⬜'} 🌐 Все рынки"}], [{"text": f"{'✅' if c == 'futures' else '⬜'} 🔮 Только Фьючерсы"}], [{"text": f"{'✅' if c == 'spot' else '⬜'} 💱 Только Спот"}], [{"text": "🔙 Настройки"}]], "resize_keyboard": True}
    
    def get_volume_keyboard(self):
        return {"keyboard": [[{"text": "💵 Без фильтра"}, {"text": "💵 $1K+"}], [{"text": "💵 $10K+"}, {"text": "💵 $50K+"}], [{"text": "💵 $100K+"}, {"text": "💵 $500K+"}], [{"text": "💵 $1M+"}, {"text": "✏️ Свой объём"}], [{"text": "🔙 Настройки"}]], "resize_keyboard": True}
    
    def get_duplicates_keyboard(self):
        return {"keyboard": [[{"text": "✅ Дубли ВКЛ"}, {"text": "❌ Дубли ВЫКЛ"}], [{"text": "🔙 Настройки"}]], "resize_keyboard": True}
    
    def get_cooldown_keyboard(self):
        return {"keyboard": [[{"text": "🔔 0с"}, {"text": "🔔 15с"}, {"text": "🔔 30с"}], [{"text": "🔔 60с"}, {"text": "🔔 120с"}, {"text": "🔔 300с"}], [{"text": "✏️ Свой КД"}, {"text": "🔙 Настройки"}]], "resize_keyboard": True}
    
    def get_price_alerts_keyboard(self, screener):
        alerts_count = len(screener.get_user_alerts())
        return {"keyboard": [[{"text": "➕ Создать алерт"}], [{"text": f"📋 Мои алерты ({alerts_count})"}], [{"text": "🗑 Очистить все"}, {"text": "🔙 Главное меню"}]], "resize_keyboard": True}
    
    def get_alert_symbol_keyboard(self):
        return {"keyboard": [[{"text": "BTC_USDT"}, {"text": "ETH_USDT"}, {"text": "SOL_USDT"}], [{"text": "PEPE_USDT"}, {"text": "WIF_USDT"}, {"text": "DOGE_USDT"}], [{"text": "XRP_USDT"}, {"text": "BNB_USDT"}, {"text": "SHIB_USDT"}], [{"text": "🔙 Отмена"}]], "resize_keyboard": True}
    
    def get_alert_condition_keyboard(self):
        return {"keyboard": [[{"text": "📈 Цена ВЫШЕ (рост)"}], [{"text": "📉 Цена НИЖЕ (падение)"}], [{"text": "🔙 Назад"}]], "resize_keyboard": True}
    
    def get_alert_price_keyboard(self, screener, current_price, condition):
        if condition == 'above':
            percentages = [1, 3, 5, 10, 15, 20]
        else:
            percentages = [-1, -3, -5, -10, -15, -20]
        keyboard = []
        row = []
        for pct in percentages:
            target = current_price * (1 + pct/100)
            text = f"{pct:+d}% (${screener.format_price(target)})"
            row.append({"text": text})
            if len(row) == 3:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)
        keyboard.append([{"text": "🔙 Назад"}])
        return {"keyboard": keyboard, "resize_keyboard": True}
    
    def get_alerts_list_keyboard(self, alerts):
        keyboard = []
        row = []
        for i, alert in enumerate(alerts):
            sym_short = alert['symbol'].replace('_USDT', '').replace('USDT', '')[:6]
            row.append({"text": f"{i+1}️⃣ {sym_short}"})
            if len(row) == 3:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)
        keyboard.append([{"text": "➕ Добавить ещё"}])
        keyboard.append([{"text": "🗑 Удалить все"}, {"text": "🔙 Назад"}])
        return {"keyboard": keyboard, "resize_keyboard": True}
    
    def get_alert_manage_keyboard(self):
        return {"keyboard": [[{"text": "🗑 Удалить этот алерт"}], [{"text": "🔙 К списку"}]], "resize_keyboard": True}
    
    def get_analytics_keyboard(self):
        return {"keyboard": [[{"text": "📊 1 час"}, {"text": "📊 6 часов"}], [{"text": "📊 24 часа"}, {"text": "📊 7 дней"}], [{"text": "🔙 Главное меню"}]], "resize_keyboard": True}
    
    def get_analytics_result_keyboard(self):
        return {"keyboard": [[{"text": "📊 1ч"}, {"text": "📊 6ч"}, {"text": "📊 24ч"}, {"text": "📊 7д"}], [{"text": "🔄 Обновить"}, {"text": "🔙 Главное меню"}]], "resize_keyboard": True}
    
    def get_subscription_keyboard(self):
        return {"keyboard": [
            [{"text": "💳 Купить подписку"}],
            [{"text": "📋 Моя подписка"}],
            [{"text": "🔙 Главное меню"}]
        ], "resize_keyboard": True}
    
    def get_plan_keyboard(self):
        prices = self.subscription_manager.get_prices()
        return {"keyboard": [
            [{"text": f"📅 1 месяц — ${prices.get('1_month', 10)}"}],
            [{"text": f"📅 3 месяца — ${prices.get('3_months', 25)}"}],
            [{"text": f"📅 6 месяцев — ${prices.get('6_months', 45)}"}],
            [{"text": f"📅 1 год — ${prices.get('1_year', 80)}"}],
            [{"text": "🔙 Назад"}]
        ], "resize_keyboard": True}
    
    def get_network_keyboard(self):
        return {"keyboard": [
            [{"text": "🔷 TRC20 (Tron)"}],
            [{"text": "🟡 BEP20 (BSC)"}],
            [{"text": "🔙 Назад"}]
        ], "resize_keyboard": True}
    
    def get_payment_keyboard(self):
        return {"keyboard": [
            [{"text": "✅ Я оплатил"}],
            [{"text": "❌ Отменить"}]
        ], "resize_keyboard": True}
    
    def get_payment_retry_keyboard(self):
        return {"keyboard": [
            [{"text": "🔄 Попробовать снова"}],
            [{"text": "💬 Написать админу"}],
            [{"text": "🔙 Назад"}]
        ], "resize_keyboard": True}
    
    def get_no_subscription_keyboard(self):
        return {"keyboard": [
            [{"text": "💳 Купить подписку"}],
            [{"text": "🔙 Главное меню"}]
        ], "resize_keyboard": True}

    def show_status(self, chat_id):
        s = self.get_screener(chat_id)
        fut, spot, active = len(s.futures_symbols), len(s.spot_symbols), len(s.get_all_symbols())
        filter_names = {"all": "Все", "futures": "FUTURES", "spot": "SPOT"}
        mode_names = {"pump": "🚀 Только PUMP", "dump": "💥 Только DUMP", "both": "📊 PUMP + DUMP"}
        candle_names = {"current": "🟡 |LIVE|", "closed": "✅ |CLOSED|", "both": "📊 Обе"}
        quote_names = {"all": "Все", "usdt": "USDT", "btc": "BTC", "eth": "ETH", "usdc": "USDC"}
        vol_filter = f"${s.format_number(s.min_volume_usdt)}" if s.min_volume_usdt > 0 else "Выкл"
        alerts_count = len(s.get_user_alerts())
        today_signals = s.get_today_signal_count()
        is_running = chat_id in self.running_users
        
        msg = f"""📊 СТАТУС СКРИНЕРА
━━━━━━━━━━━━━━━━━━━━━━━━
{"🟢 РАБОТАЕТ" if is_running else "🔴 ОСТАНОВЛЕН"}
━━━━━━━━━━━━━━━━━━━━━━━━

🔌 ПОДКЛЮЧЕНИЕ:
└ 🔄 REST API

⚙️ НАСТРОЙКИ:
├ ⏱ Таймфрейм: {s.timeframe_display}
├ 🎯 Режим: {mode_names[s.signal_mode]}
├ 🕯 Свеча: {candle_names[s.candle_mode]}
├ 📊 Мин. изменение: {s.min_pump}%
├ 🏪 Рынок: {filter_names[s.market_type_filter]}
├ 💱 Quote: {quote_names[s.spot_quote_filter]}
├ 💰 Мин. объём: {vol_filter}
├ 🔄 Дубликаты: {"ВКЛ" if s.allow_duplicates else "ВЫКЛ"}
├ ⏰ Кулдаун: {s.alert_cooldown}с
├ ⚡ Скорость: {s.scan_interval}с
└ 📊 Графики: {"ВКЛ" if s.send_charts else "ВЫКЛ"}

📊 ПАРЫ:
├ 🔮 Деривативов: {fut}
├ 💱 Спот: {spot}
└ 🎯 Активных: {active}

🎯 Price Alerts: {alerts_count} активных
📨 Сегодня сигналов: {today_signals}
💾 Автосохранение: ✅ ВКЛ
━━━━━━━━━━━━━━━━━━━━━━━━"""
        self.send_message(chat_id, msg, self.get_main_keyboard())
    
    def show_settings(self, chat_id):
        s = self.get_screener(chat_id)
        filter_names = {"all": "Все", "futures": "FUTURES", "spot": "SPOT"}
        mode_names = {"pump": "🚀 PUMP", "dump": "💥 DUMP", "both": "📊 PUMP+DUMP"}
        candle_names = {"current": "🟡 |LIVE|", "closed": "✅ |CLOSED|", "both": "📊 ОБЕ"}
        quote_names = {"all": "Все", "usdt": "USDT", "btc": "BTC", "eth": "ETH", "usdc": "USDC"}
        vol_filter = f"${s.format_number(s.min_volume_usdt)}" if s.min_volume_usdt > 0 else "Выкл"
        msg = f"""⚙️ НАСТРОЙКИ
━━━━━━━━━━━━━━━━━━━━━━━━
💾 Автосохранение: ✅ ВКЛ
━━━━━━━━━━━━━━━━━━━━━━━━

📋 Текущие значения:
├ ⏱ Таймфрейм: {s.timeframe_display}
├ 💹 Мин. изменение: {s.min_pump}%
├ 🎯 Сигналы: {mode_names[s.signal_mode]}
├ 🕯 Свеча: {candle_names[s.candle_mode]}
├ 🏪 Рынок: {filter_names[s.market_type_filter]}
├ 💱 Quote: {quote_names[s.spot_quote_filter]}
├ 💰 Мин. объём: {vol_filter}
├ 🔄 Дубликаты: {"ВКЛ" if s.allow_duplicates else "ВЫКЛ"}
├ ⏰ Кулдаун: {s.alert_cooldown}с
├ ⚡ Скорость: {s.scan_interval}с
└ 📊 Графики: {"ВКЛ" if s.send_charts else "ВЫКЛ"}

Выберите параметр:
━━━━━━━━━━━━━━━━━━━━━━━━"""
        self.send_message(chat_id, msg, self.get_settings_keyboard())
    
    def show_top(self, chat_id, period="24h"):
        s = self.get_screener(chat_id)
        user_top_mode = self.top_mode.get(chat_id, "gainers")
        mode_name = "📈 РОСТ" if user_top_mode == "gainers" else "📉 ПАДЕНИЕ"
        self.send_message(chat_id, f"⚡ Загрузка {mode_name} за {period}...")
        s.funding_rates = s.get_funding_rates()
        top, period_name = s.get_top_movers(period, 10, user_top_mode)
        if not top:
            self.send_message(chat_id, "❌ Нет данных", self.get_top_period_keyboard())
            return
        filter_names = {"all": "Все", "futures": "FUTURES", "spot": "SPOT"}
        vol_filter = f">${s.format_number(s.min_volume_usdt)}" if s.min_volume_usdt > 0 else "Без фильтра"
        if user_top_mode == "gainers":
            header = "🚀 ТОП-10 РОСТ"
            medals = ["🥇", "🥈", "🥉"]
        else:
            header = "💥 ТОП-10 ПАДЕНИЕ"
            medals = ["💀", "☠️", "👻"]
        msg = f"""{header} за {period_name}
━━━━━━━━━━━━━━━━━━━━━━━━
📊 Рынок: {filter_names[s.market_type_filter]}
💰 Мин. объём: {vol_filter}
━━━━━━━━━━━━━━━━━━━━━━━━

"""
        for i, d in enumerate(top):
            vol = s.format_number(d['volume'])
            change_str = f"+{d['change']:.2f}%" if user_top_mode == "gainers" else f"{d['change']:.2f}%"
            if i < 3:
                msg += f"""{medals[i]} {d['type_icon']} {d['symbol']}
   {change_str} | ${vol}
   {d['reliability']}
"""
                if d['funding'] is not None:
                    msg += f"   💰 Funding: {d['funding']:+.4f}%\n"
                msg += "\n"
            else:
                funding_txt = f" | F:{d['funding']:+.3f}%" if d['funding'] else ""
                msg += f"{i+1}. {d['type_icon']} {d['symbol']} {change_str} | ${vol}{funding_txt}\n"
        msg += f"\n━━━━━━━━━━━━━━━━━━━━━━━━\n👑 Admin: {ADMIN_LINK}"
        self.send_message(chat_id, msg, self.get_top_period_keyboard())
    
    def show_pairs(self, chat_id):
        s = self.get_screener(chat_id)
        self.send_message(chat_id, "⚡ Загрузка ВСЕХ пар...")
        old_filter, old_quote = s.market_type_filter, s.spot_quote_filter
        s.market_type_filter, s.spot_quote_filter = "all", "all"
        s.get_all_symbols(force_reload=True)
        s.market_type_filter, s.spot_quote_filter = old_filter, old_quote
        fut, spot, active = len(s.futures_symbols), len(s.spot_symbols), len(s.get_all_symbols())
        filter_names = {"all": "Все", "futures": "Только FUTURES", "spot": "Только SPOT"}
        quote_names = {"all": "Все", "usdt": "USDT", "btc": "BTC", "eth": "ETH", "usdc": "USDC"}
        msg = f"""📊 ТОРГОВЫЕ ПАРЫ MEXC
━━━━━━━━━━━━━━━━━━━━━━━━
🔮 Деривативы: {fut}
💱 Спот: {spot}
━━━━━━━━━━━━━━━━━━━━━━━━
📊 ВСЕГО: {fut + spot} пар
━━━━━━━━━━━━━━━━━━━━━━━━
🎯 Фильтр рынка: {filter_names[s.market_type_filter]}
💱 Фильтр Quote: {quote_names[s.spot_quote_filter]}
📌 Активных: {active}
━━━━━━━━━━━━━━━━━━━━━━━━"""
        self.send_message(chat_id, msg, self.get_main_keyboard())
    
    def save_and_confirm(self, chat_id, setting_name):
        s = self.get_screener(chat_id)
        s.save_user_settings()
        return f"✅ {setting_name}\n\n💾 Настройка сохранена!"
    
    def user_loop(self, chat_id):
        s = self.get_screener(chat_id)
        while chat_id in self.running_users:
            try:
                s.scan()
                time.sleep(s.scan_interval)
            except Exception as e:
                print(f"❌ [{chat_id}] Loop error: {e}")
                time.sleep(5)
    
    def start_user_screener(self, chat_id):
        with self.lock:
            if chat_id in self.running_users:
                return False
            self.running_users.add(chat_id)
            thread = threading.Thread(target=self.user_loop, args=(chat_id,), daemon=True)
            self.user_threads[chat_id] = thread
            thread.start()
            return True
    
    def stop_user_screener(self, chat_id):
        with self.lock:
            if chat_id in self.running_users:
                self.running_users.discard(chat_id)
                return True
            return False
    
    def check_subscription(self, chat_id):
        """Проверка подписки. Возвращает True если есть доступ"""
        if self.subscription_manager.has_subscription(chat_id):
            return True
        return False
    
    def send_no_subscription_message(self, chat_id):
        """Отправка сообщения об отсутствии подписки"""
        msg = f"""━━━━━━━━━━━━━━━━━━━━━━━━━━━
❌ ПОДПИСКА НЕ АКТИВНА
━━━━━━━━━━━━━━━━━━━━━━━━━━━

У вас нет активной подписки.

💎 Приобретите подписку:
├ 🔮 Фьючерсы + Спот
├ 🚀 PUMP/DUMP сигналы
├ 📊 Графики
├ 🎯 Price Alerts
└ ⚡ Мгновенные уведомления

━━━━━━━━━━━━━━━━━━━━━━━━━━━
👑 Admin: {ADMIN_LINK}
━━━━━━━━━━━━━━━━━━━━━━━━━━━"""
        self.send_message(chat_id, msg, self.get_no_subscription_keyboard())
    
    def handle(self, message):
        chat_id = message['chat']['id']
        text = message.get('text', '').strip()
        
        s = self.get_screener(chat_id)
        
        # Обработка ввода
        if chat_id in self.waiting_for_input:
            inp = self.waiting_for_input.pop(chat_id)
            
            if inp == 'enter_tx_hash':
                tx_hash = text.strip()
                if len(tx_hash) < 20:
                    self.waiting_for_input[chat_id] = 'enter_tx_hash'
                    self.send_message(chat_id, "❌ Слишком короткий TX Hash. Попробуйте ещё раз:")
                    return
                
                self.send_message(chat_id, "⏳ Проверяю транзакцию...")
                
                success, result = self.subscription_manager.verify_payment(chat_id, tx_hash)
                
                if success:
                    expires_str = self.subscription_manager.format_expires_date(result)
                    pending = self.subscription_manager.pending_payments.get(chat_id, {})
                    plan = pending.get('plan', '1_month')
                    plan_name = self.subscription_manager.get_plan_name(plan)
                    amount = self.subscription_manager.get_prices().get(plan, 0)
                    
                    msg = f"""━━━━━━━━━━━━━━━━━━━━━━━━━━━
✅ ПОДПИСКА АКТИВИРОВАНА!
━━━━━━━━━━━━━━━━━━━━━━━━━━━

🎉 Поздравляем!

📦 Тариф: {plan_name}
📅 Активна до: {expires_str}
💰 Оплачено: {amount} USDT

━━━━━━━━━━━━━━━━━━━━━━━━━━━

Вам доступны:
✅ Фьючерсы + Спот
✅ PUMP/DUMP сигналы
✅ Графики
✅ Price Alerts
✅ Все настройки

━━━━━━━━━━━━━━━━━━━━━━━━━━━
👑 Приятного использования!
━━━━━━━━━━━━━━━━━━━━━━━━━━━"""
                    self.send_message(chat_id, msg, self.get_main_keyboard())
                else:
                    msg = f"""━━━━━━━━━━━━━━━━━━━━━━━━━━━
❌ ОПЛАТА НЕ НАЙДЕНА
━━━━━━━━━━━━━━━━━━━━━━━━━━━

{result}

💡 Возможные причины:
• Транзакция ещё обрабатывается
• Неверная сумма
• Неверная сеть  
• Неверный TX Hash

⏳ Подождите 5-10 минут и попробуйте снова.

При проблемах: {ADMIN_LINK}

━━━━━━━━━━━━━━━━━━━━━━━━━━━"""
                    self.send_message(chat_id, msg, self.get_payment_retry_keyboard())
                return
            
            elif inp == 'select_network' or inp == 'waiting_payment':
                # Игнорируем неожиданный ввод в этих состояниях
                return
            
            elif inp == 'percent':
                try:
                    v = float(text.replace('%', '').replace(',', '.'))
                    if 0 < v <= 100:
                        s.min_pump = s.min_dump = v
                        self.send_message(chat_id, self.save_and_confirm(chat_id, f"Мин. изменение: {v}%"), self.get_percent_keyboard())
                    else:
                        self.send_message(chat_id, "❌ Введите от 0.1 до 100", self.get_percent_keyboard())
                except:
                    self.send_message(chat_id, "❌ Неверный формат", self.get_percent_keyboard())
                return
            
            elif inp == 'volume':
                try:
                    t = text.upper().replace('$', '').replace(' ', '')
                    m = 1
                    if t.endswith('K'): m, t = 1000, t[:-1]
                    elif t.endswith('M'): m, t = 1000000, t[:-1]
                    v = float(t.replace(',', '.')) * m
                    s.min_volume_usdt = v
                    self.send_message(chat_id, self.save_and_confirm(chat_id, f"Мин. объём: ${s.format_number(v)}"), self.get_volume_keyboard())
                except:
                    self.send_message(chat_id, "❌ Примеры: 5000, 50K, 1M", self.get_volume_keyboard())
                return
            
            elif inp == 'cooldown':
                try:
                    v = int(text.replace('с', '').replace('s', ''))
                    if 0 <= v <= 3600:
                        s.alert_cooldown = v
                        self.send_message(chat_id, self.save_and_confirm(chat_id, f"Кулдаун: {v}с"), self.get_cooldown_keyboard())
                    else:
                        self.send_message(chat_id, "❌ От 0 до 3600", self.get_cooldown_keyboard())
                except:
                    self.send_message(chat_id, "❌ Введите число", self.get_cooldown_keyboard())
                return
        
        # Price Alert - ввод цены
        if chat_id in self.alert_creation_state and self.alert_creation_state[chat_id].get('step') == 'price':
            if text == "🔙 Назад":
                self.alert_creation_state[chat_id]['step'] = 'condition'
                self.send_message(chat_id, "📊 Выберите условие:", self.get_alert_condition_keyboard())
                return
            state = self.alert_creation_state[chat_id]
            try:
                if '%' in text and '$' in text:
                    price_str = text.split('$')[1].replace(')', '').strip()
                    target_price = float(price_str.replace(',', ''))
                else:
                    target_price = float(text.replace('$', '').replace(',', '.').strip())
                if target_price <= 0:
                    raise ValueError()
                success, message = s.add_price_alert(state['symbol'], state['condition'], target_price, state['market_type'])
                if success:
                    market_icon = "🔮" if state['market_type'] == 'futures' else "💱"
                    condition_text = "ВЫШЕ" if state['condition'] == 'above' else "НИЖЕ"
                    condition_icon = "📈" if state['condition'] == 'above' else "📉"
                    current_price = state['current_price']
                    diff_pct = ((target_price - current_price) / current_price) * 100
                    msg = f"""✅ ALERT СОЗДАН!
━━━━━━━━━━━━━━━━━━━━━━━━

{market_icon} {state['symbol']}
{condition_icon} Уведомить когда: {condition_text} ${s.format_price(target_price)}

💰 Текущая цена: ${s.format_price(current_price)}
📊 До цели: {diff_pct:+.1f}%

💾 Алерт сохранён!
━━━━━━━━━━━━━━━━━━━━━━━━"""
                    del self.alert_creation_state[chat_id]
                    self.send_message(chat_id, msg, self.get_price_alerts_keyboard(s))
                else:
                    self.send_message(chat_id, f"❌ {message}", self.get_price_alerts_keyboard(s))
                    del self.alert_creation_state[chat_id]
            except:
                self.send_message(chat_id, "❌ Неверный формат. Введите число: 70000", self.get_alert_price_keyboard(s, state['current_price'], state['condition']))
            return
        
        # Основные команды
        if text in ['/start', '/help']:
            msg = f"""👑 KING |PUMP/DUMP| SCREENER
━━━━━━━━━━━━━━━━━━━━━━━━
🔮 Фьючерсы + 💱 Спот
🚀 PUMP + 💥 DUMP
🟡 |LIVE| + ✅ |CLOSED|
📊 Графики сигналов
━━━━━━━━━━━━━━━━━━━━━━━━

📌 КОМАНДЫ:
├ 🚀 Старт / 🛑 Стоп
├ 📊 Статус
├ 🔥 ТОП - лидеры
├ 📈 Аналитика
├ 🎯 Price Alerts
├ 📋 Пары
└ ⚙️ Настройки

💾 Автосохранение настроек
👥 Мультипользовательский режим
📊 Графики с каждым сигналом
━━━━━━━━━━━━━━━━━━━━━━━━
👑 Admin: {ADMIN_LINK}"""
            self.send_message(chat_id, msg, self.get_main_keyboard())
        
        elif text == "🚀 Старт":
            if not self.check_subscription(chat_id):
                self.send_no_subscription_message(chat_id)
                return
            if self.start_user_screener(chat_id):
                mode_names = {"pump": "🚀 PUMP", "dump": "💥 DUMP", "both": "📊 PUMP+DUMP"}
                candle_names = {"current": "🟡 |LIVE|", "closed": "✅ |CLOSED|", "both": "📊 ОБЕ"}
                msg = f"""✅ СКРИНЕР ЗАПУЩЕН!
━━━━━━━━━━━━━━━━━━━━━━━━

🔌 ПОДКЛЮЧЕНИЕ:
└ 🔄 REST API

⚙️ ПАРАМЕТРЫ:
├ ⏱ ТФ: {s.timeframe_display}
├ 🎯 Режим: {mode_names[s.signal_mode]}
├ 🕯 Свеча: {candle_names[s.candle_mode]}
├ 📊 Мин: {s.min_pump}%
├ ⚡ Скорость: {s.scan_interval}с
└ 📊 Графики: {"ВКЛ" if s.send_charts else "ВЫКЛ"}

━━━━━━━━━━━━━━━━━━━━━━━━"""
                self.send_message(chat_id, msg, self.get_main_keyboard())
            else:
                self.send_message(chat_id, "⚠️ Уже работает", self.get_main_keyboard())
        
        elif text == "🛑 Стоп":
            if self.stop_user_screener(chat_id):
                self.send_message(chat_id, "🛑 Остановлен", self.get_main_keyboard())
            else:
                self.send_message(chat_id, "⚠️ Скринер не запущен", self.get_main_keyboard())
        
        elif text == "📊 Статус":
            self.show_status(chat_id)
        
        elif text == "🔥 ТОП":
            if not self.check_subscription(chat_id):
                self.send_no_subscription_message(chat_id)
                return
            self.top_mode[chat_id] = None
            self.send_message(chat_id, "🔥 Выберите тип:", self.get_top_mode_keyboard())
        
        elif text == "📈 ТОП Роста":
            self.top_mode[chat_id] = "gainers"
            self.send_message(chat_id, "✅ 📈 ТОП РОСТА\n\nВыберите период:", self.get_top_period_keyboard())
        
        elif text == "📉 ТОП Падения":
            self.top_mode[chat_id] = "losers"
            self.send_message(chat_id, "✅ 📉 ТОП ПАДЕНИЯ\n\nВыберите период:", self.get_top_period_keyboard())
        
        elif text == "🔙 Назад":
            self.top_mode[chat_id] = None
            self.send_message(chat_id, "🔥 Выберите тип:", self.get_top_mode_keyboard())
        
        elif text.startswith("⏱ ") and text[2:] in ["1m", "5m", "15m", "30m", "1h", "4h", "24h"]:
            if self.top_mode.get(chat_id):
                threading.Thread(target=self.show_top, args=(chat_id, text[2:]), daemon=True).start()
            else:
                self.send_message(chat_id, "❌ Сначала выберите тип", self.get_top_mode_keyboard())
        
        elif text == "📋 Пары":
            threading.Thread(target=self.show_pairs, args=(chat_id,), daemon=True).start()
        
        elif text == "⚙️ Настройки":
            if not self.check_subscription(chat_id):
                self.send_no_subscription_message(chat_id)
                return
            self.show_settings(chat_id)
        
        elif text == "🔙 Главное меню":
            self.top_mode[chat_id] = None
            if chat_id in self.alert_creation_state:
                del self.alert_creation_state[chat_id]
            self.send_message(chat_id, "🏠 Главное меню", self.get_main_keyboard())

              # ═══════════════════════════════════════════════════════════════
        # SUBSCRIPTION HANDLERS
        # ═══════════════════════════════════════════════════════════════
        
        elif text == "💎 Подписка":
            sub_info = self.subscription_manager.get_subscription_info(chat_id)
            if sub_info['active']:
                if sub_info.get('is_admin'):
                    msg = f"""💎 ВАША ПОДПИСКА
━━━━━━━━━━━━━━━━━━━━━━━━━━━

👑 Статус: АДМИНИСТРАТОР

✅ У вас полный доступ навсегда!

━━━━━━━━━━━━━━━━━━━━━━━━━━━"""
                else:
                    expires_str = self.subscription_manager.format_expires_date(sub_info['expires_at'])
                    days_left = self.subscription_manager.get_days_remaining(sub_info['expires_at'])
                    plan_name = self.subscription_manager.get_plan_name(sub_info['plan'])
                    msg = f"""💎 ВАША ПОДПИСКА
━━━━━━━━━━━━━━━━━━━━━━━━━━━

✅ Статус: АКТИВНА

📦 Тариф: {plan_name}
📅 Действует до: {expires_str}
⏳ Осталось: {days_left} дней

━━━━━━━━━━━━━━━━━━━━━━━━━━━"""
                self.send_message(chat_id, msg, self.get_subscription_keyboard())
            else:
                msg = f"""💎 ПОДПИСКА
━━━━━━━━━━━━━━━━━━━━━━━━━━━

❌ Статус: НЕ АКТИВНА

Приобретите подписку для доступа
к функциям скринера.

━━━━━━━━━━━━━━━━━━━━━━━━━━━"""
                self.send_message(chat_id, msg, self.get_subscription_keyboard())
        
        elif text == "📋 Моя подписка":
            sub_info = self.subscription_manager.get_subscription_info(chat_id)
            if sub_info['active']:
                if sub_info.get('is_admin'):
                    msg = """👑 ВЫ АДМИНИСТРАТОР

Полный доступ ко всем функциям навсегда!"""
                else:
                    expires_str = self.subscription_manager.format_expires_date(sub_info['expires_at'])
                    days_left = self.subscription_manager.get_days_remaining(sub_info['expires_at'])
                    plan_name = self.subscription_manager.get_plan_name(sub_info['plan'])
                    activated = datetime.fromtimestamp(sub_info['activated_at']).strftime('%d.%m.%Y')
                    msg = f"""📋 ИНФОРМАЦИЯ О ПОДПИСКЕ
━━━━━━━━━━━━━━━━━━━━━━━━━━━

✅ Статус: АКТИВНА

📦 Тариф: {plan_name}
📅 Активирована: {activated}
📅 Действует до: {expires_str}
⏳ Осталось: {days_left} дней

━━━━━━━━━━━━━━━━━━━━━━━━━━━"""
                self.send_message(chat_id, msg, self.get_subscription_keyboard())
            else:
                self.send_message(chat_id, "❌ У вас нет активной подписки", self.get_subscription_keyboard())
        
        elif text == "💳 Купить подписку":
            prices = self.subscription_manager.get_prices()
            msg = f"""💳 ПОКУПКА ПОДПИСКИ
━━━━━━━━━━━━━━━━━━━━━━━━━━━

Выберите срок подписки:

📅 1 месяц — ${prices.get('1_month', 10)} USDT
📅 3 месяца — ${prices.get('3_months', 25)} USDT (экономия 17%)
📅 6 месяцев — ${prices.get('6_months', 45)} USDT (экономия 25%)  
📅 1 год — ${prices.get('1_year', 80)} USDT (экономия 33%)

━━━━━━━━━━━━━━━━━━━━━━━━━━━"""
            self.send_message(chat_id, msg, self.get_plan_keyboard())
        
        elif text.startswith("📅 1 месяц"):
            self.waiting_for_input[chat_id] = 'select_network'
            self.subscription_manager.pending_payments[chat_id] = {'plan': '1_month'}
            prices = self.subscription_manager.get_prices()
            msg = f"""💳 ОПЛАТА: 1 МЕСЯЦ
━━━━━━━━━━━━━━━━━━━━━━━━━━━

💰 Сумма: {prices['1_month']} USDT

Выберите сеть для оплаты:

🔷 TRC20 (Tron) — комиссия ~1$
🟡 BEP20 (BSC) — комиссия ~0.3$

━━━━━━━━━━━━━━━━━━━━━━━━━━━"""
            self.send_message(chat_id, msg, self.get_network_keyboard())
        
        elif text.startswith("📅 3 месяца"):
            self.waiting_for_input[chat_id] = 'select_network'
            self.subscription_manager.pending_payments[chat_id] = {'plan': '3_months'}
            prices = self.subscription_manager.get_prices()
            msg = f"""💳 ОПЛАТА: 3 МЕСЯЦА
━━━━━━━━━━━━━━━━━━━━━━━━━━━

💰 Сумма: {prices['3_months']} USDT

Выберите сеть для оплаты:

🔷 TRC20 (Tron) — комиссия ~1$
🟡 BEP20 (BSC) — комиссия ~0.3$

━━━━━━━━━━━━━━━━━━━━━━━━━━━"""
            self.send_message(chat_id, msg, self.get_network_keyboard())
        
        elif text.startswith("📅 6 месяцев"):
            self.waiting_for_input[chat_id] = 'select_network'
            self.subscription_manager.pending_payments[chat_id] = {'plan': '6_months'}
            prices = self.subscription_manager.get_prices()
            msg = f"""💳 ОПЛАТА: 6 МЕСЯЦЕВ
━━━━━━━━━━━━━━━━━━━━━━━━━━━

💰 Сумма: {prices['6_months']} USDT

Выберите сеть для оплаты:

🔷 TRC20 (Tron) — комиссия ~1$
🟡 BEP20 (BSC) — комиссия ~0.3$

━━━━━━━━━━━━━━━━━━━━━━━━━━━"""
            self.send_message(chat_id, msg, self.get_network_keyboard())
        
        elif text.startswith("📅 1 год"):
            self.waiting_for_input[chat_id] = 'select_network'
            self.subscription_manager.pending_payments[chat_id] = {'plan': '1_year'}
            prices = self.subscription_manager.get_prices()
            msg = f"""💳 ОПЛАТА: 1 ГОД
━━━━━━━━━━━━━━━━━━━━━━━━━━━

💰 Сумма: {prices['1_year']} USDT

Выберите сеть для оплаты:

🔷 TRC20 (Tron) — комиссия ~1$
🟡 BEP20 (BSC) — комиссия ~0.3$

━━━━━━━━━━━━━━━━━━━━━━━━━━━"""
            self.send_message(chat_id, msg, self.get_network_keyboard())
        
        elif text == "🔷 TRC20 (Tron)":
            if chat_id in self.subscription_manager.pending_payments:
                pending = self.subscription_manager.pending_payments[chat_id]
                plan = pending['plan']
                prices = self.subscription_manager.get_prices()
                amount = prices[plan]
                wallet = self.subscription_manager.get_wallet('TRC20')
                plan_name = self.subscription_manager.get_plan_name(plan)
                
                self.subscription_manager.set_pending_payment(chat_id, plan, 'TRC20')
                self.waiting_for_input[chat_id] = 'waiting_payment'
                
                msg = f"""━━━━━━━━━━━━━━━━━━━━━━━━━━━
💳 ОПЛАТА ПОДПИСКИ
━━━━━━━━━━━━━━━━━━━━━━━━━━━

📦 Тариф: {plan_name}
💰 Сумма: {amount} USDT
🌐 Сеть: TRC20 (Tron)

━━━━━━━━━━━━━━━━━━━━━━━━━━━

📬 Адрес для оплаты:

`{wallet}`

(нажмите чтобы скопировать)

━━━━━━━━━━━━━━━━━━━━━━━━━━━

⚠️ ВАЖНО:
• Отправляйте ТОЛЬКО USDT
• Только сеть TRC20!
• Сумма РОВНО {amount} USDT
• После оплаты нажмите "Я оплатил"

━━━━━━━━━━━━━━━━━━━━━━━━━━━"""
                self.send_message(chat_id, msg, self.get_payment_keyboard())
        
        elif text == "🟡 BEP20 (BSC)":
            if chat_id in self.subscription_manager.pending_payments:
                pending = self.subscription_manager.pending_payments[chat_id]
                plan = pending['plan']
                prices = self.subscription_manager.get_prices()
                amount = prices[plan]
                wallet = self.subscription_manager.get_wallet('BEP20')
                plan_name = self.subscription_manager.get_plan_name(plan)
                
                self.subscription_manager.set_pending_payment(chat_id, plan, 'BEP20')
                self.waiting_for_input[chat_id] = 'waiting_payment'
                
                msg = f"""━━━━━━━━━━━━━━━━━━━━━━━━━━━
💳 ОПЛАТА ПОДПИСКИ
━━━━━━━━━━━━━━━━━━━━━━━━━━━

📦 Тариф: {plan_name}
💰 Сумма: {amount} USDT
🌐 Сеть: BEP20 (BSC)

━━━━━━━━━━━━━━━━━━━━━━━━━━━

📬 Адрес для оплаты:

`{wallet}`

(нажмите чтобы скопировать)

━━━━━━━━━━━━━━━━━━━━━━━━━━━

⚠️ ВАЖНО:
• Отправляйте ТОЛЬКО USDT
• Только сеть BEP20 (BSC)!
• Сумма РОВНО {amount} USDT
• После оплаты нажмите "Я оплатил"

━━━━━━━━━━━━━━━━━━━━━━━━━━━"""
                self.send_message(chat_id, msg, self.get_payment_keyboard())
        
        elif text == "✅ Я оплатил":
            pending = self.subscription_manager.get_pending_payment(chat_id)
            if pending:
                self.waiting_for_input[chat_id] = 'enter_tx_hash'
                msg = """🔍 ПРОВЕРКА ОПЛАТЫ
━━━━━━━━━━━━━━━━━━━━━━━━━━━

📝 Введите TX Hash транзакции:

Это длинный код из вашего кошелька,
который появился после отправки.

Пример TRC20:
`7f3a8b2c1d4e5f6a7b8c9d0e...`

Пример BEP20:
`0x7f3a8b2c1d4e5f6a7b8c9d0e...`

━━━━━━━━━━━━━━━━━━━━━━━━━━━"""
                self.send_message(chat_id, msg)
            else:
                self.send_message(chat_id, "❌ Нет ожидающего платежа", self.get_subscription_keyboard())
        
        elif text == "❌ Отменить":
            self.subscription_manager.clear_pending_payment(chat_id)
            if chat_id in self.waiting_for_input:
                del self.waiting_for_input[chat_id]
            self.send_message(chat_id, "❌ Оплата отменена", self.get_subscription_keyboard())
        
        elif text == "🔄 Попробовать снова":
            pending = self.subscription_manager.get_pending_payment(chat_id)
            if pending:
                self.waiting_for_input[chat_id] = 'enter_tx_hash'
                msg = """🔍 ПРОВЕРКА ОПЛАТЫ
━━━━━━━━━━━━━━━━━━━━━━━━━━━

📝 Введите TX Hash транзакции:

━━━━━━━━━━━━━━━━━━━━━━━━━━━"""
                self.send_message(chat_id, msg)
            else:
                self.send_message(chat_id, "❌ Нет ожидающего платежа", self.get_subscription_keyboard())
        
        elif text == "💬 Написать админу":
            self.send_message(chat_id, f"💬 Напишите админу: {ADMIN_LINK}", self.get_subscription_keyboard())

        elif text == "🔙 Настройки":
            self.show_settings(chat_id)
        
        # Настройка графиков
        elif text == "📊 Графики":
            self.send_message(chat_id, f"📊 Графики: {'ВКЛ' if s.send_charts else 'ВЫКЛ'}\n\nОтправлять график с каждым сигналом?", self.get_charts_keyboard(s))
        
        elif "📊 Графики ВКЛ" in text:
            s.send_charts = True
            self.send_message(chat_id, self.save_and_confirm(chat_id, "Графики: ВКЛ"), self.get_charts_keyboard(s))
        
        elif "📊 Графики ВЫКЛ" in text:
            s.send_charts = False
            self.send_message(chat_id, self.save_and_confirm(chat_id, "Графики: ВЫКЛ"), self.get_charts_keyboard(s))
        
        # Price Alerts
        elif text == "🎯 Price Alerts":
            if not self.check_subscription(chat_id):
                self.send_no_subscription_message(chat_id)
                return
            alerts_count = len(s.get_user_alerts())
            msg = f"""🎯 PRICE ALERTS
━━━━━━━━━━━━━━━━━━━━━━━━
Уведомления о достижении цены.

📊 Ваши алерты: {alerts_count} из {s.max_alerts_per_user}
💾 Алерты сохраняются автоматически
━━━━━━━━━━━━━━━━━━━━━━━━"""
            self.send_message(chat_id, msg, self.get_price_alerts_keyboard(s))
        
        elif text == "➕ Создать алерт" or text == "➕ Добавить ещё":
            self.alert_creation_state[chat_id] = {'step': 'symbol'}
            msg = """➕ СОЗДАТЬ PRICE ALERT
━━━━━━━━━━━━━━━━━━━━━━━━

📝 Введите символ:

Примеры: BTC_USDT, ETHUSDT
━━━━━━━━━━━━━━━━━━━━━━━━"""
            self.send_message(chat_id, msg, self.get_alert_symbol_keyboard())
        
        elif text == "🔙 Отмена":
            if chat_id in self.alert_creation_state:
                del self.alert_creation_state[chat_id]
            self.send_message(chat_id, "❌ Отменено", self.get_price_alerts_keyboard(s))
        
        elif text in ["BTC_USDT", "ETH_USDT", "SOL_USDT", "PEPE_USDT", "WIF_USDT", "DOGE_USDT", "XRP_USDT", "BNB_USDT", "SHIB_USDT"] or (chat_id in self.alert_creation_state and self.alert_creation_state[chat_id].get('step') == 'symbol' and ('USDT' in text.upper())):
            symbol = text.upper().strip()
            market_type = 'futures' if '_' in symbol else 'spot'
            current_price = s.get_current_price(symbol, market_type)
            if current_price is None:
                alt_market = 'spot' if market_type == 'futures' else 'futures'
                alt_symbol = symbol.replace('_', '') if market_type == 'futures' else symbol.replace('USDT', '_USDT')
                current_price = s.get_current_price(alt_symbol, alt_market)
                if current_price:
                    symbol, market_type = alt_symbol, alt_market
            if current_price is None:
                self.send_message(chat_id, f"❌ {symbol} не найден", self.get_alert_symbol_keyboard())
                return
            self.alert_creation_state[chat_id] = {'step': 'condition', 'symbol': symbol, 'market_type': market_type, 'current_price': current_price}
            market_icon = "🔮" if market_type == 'futures' else "💱"
            msg = f"""➕ СОЗДАТЬ PRICE ALERT
━━━━━━━━━━━━━━━━━━━━━━━━
{market_icon} Монета: {symbol}
💰 Цена: ${s.format_price(current_price)}
━━━━━━━━━━━━━━━━━━━━━━━━

📊 Выберите условие:"""
            self.send_message(chat_id, msg, self.get_alert_condition_keyboard())
        
        elif text == "📈 Цена ВЫШЕ (рост)":
            if chat_id in self.alert_creation_state and self.alert_creation_state[chat_id].get('step') == 'condition':
                state = self.alert_creation_state[chat_id]
                state['step'], state['condition'] = 'price', 'above'
                msg = f"💵 Введите целевую цену:\n\nТекущая: ${s.format_price(state['current_price'])}"
                self.send_message(chat_id, msg, self.get_alert_price_keyboard(s, state['current_price'], 'above'))
        
        elif text == "📉 Цена НИЖЕ (падение)":
            if chat_id in self.alert_creation_state and self.alert_creation_state[chat_id].get('step') == 'condition':
                state = self.alert_creation_state[chat_id]
                state['step'], state['condition'] = 'price', 'below'
                msg = f"💵 Введите целевую цену:\n\nТекущая: ${s.format_price(state['current_price'])}"
                self.send_message(chat_id, msg, self.get_alert_price_keyboard(s, state['current_price'], 'below'))
        
        elif text.startswith("📋 Мои алерты"):
            alerts = s.get_user_alerts()
            if not alerts:
                self.send_message(chat_id, "📋 Нет активных алертов", self.get_price_alerts_keyboard(s))
                return
            msg = "📋 ВАШИ PRICE ALERTS\n━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            for i, alert in enumerate(alerts):
                market_icon = "🔮" if alert['market_type'] == 'futures' else "💱"
                condition_icon = "📈" if alert['condition'] == 'above' else "📉"
                condition_text = "Выше" if alert['condition'] == 'above' else "Ниже"
                current_price = s.get_current_price(alert['symbol'], alert['market_type'])
                msg += f"{i+1}️⃣ {market_icon} {alert['symbol']}\n   {condition_icon} {condition_text} ${s.format_price(alert['target_price'])}"
                if current_price:
                    diff_pct = ((alert['target_price'] - current_price) / current_price) * 100
                    msg += f"\n   💰 Сейчас: ${s.format_price(current_price)} ({diff_pct:+.1f}%)\n\n"
                else:
                    msg += "\n\n"
            msg += "━━━━━━━━━━━━━━━━━━━━━━━━"
            self.send_message(chat_id, msg, self.get_alerts_list_keyboard(alerts))
        
        elif text == "🗑 Очистить все" or text == "🗑 Удалить все":
            count = s.clear_price_alerts()
            self.send_message(chat_id, f"🗑 Удалено: {count}", self.get_price_alerts_keyboard(s))
        
        elif text[0].isdigit() and "️⃣" in text:
            try:
                index = int(text[0]) - 1
                alerts = s.get_user_alerts()
                if 0 <= index < len(alerts):
                    self.selected_alert_index[chat_id] = index
                    alert = alerts[index]
                    market_icon = "🔮" if alert['market_type'] == 'futures' else "💱"
                    condition_icon = "📈" if alert['condition'] == 'above' else "📉"
                    condition_text = "ВЫШЕ" if alert['condition'] == 'above' else "НИЖЕ"
                    current_price = s.get_current_price(alert['symbol'], alert['market_type'])
                    diff_pct = ((alert['target_price'] - current_price) / current_price) * 100 if current_price else 0
                    msg = f"""🎯 АЛЕРТ #{index + 1}
━━━━━━━━━━━━━━━━━━━━━━━━

{market_icon} {alert['symbol']}
{condition_icon} Условие: {condition_text} ${s.format_price(alert['target_price'])}

💰 Текущая: ${s.format_price(current_price) if current_price else 'N/A'}
📊 До цели: {diff_pct:+.1f}%

━━━━━━━━━━━━━━━━━━━━━━━━"""
                    self.send_message(chat_id, msg, self.get_alert_manage_keyboard())
            except:
                pass
        
        elif text == "🗑 Удалить этот алерт":
            if chat_id in self.selected_alert_index:
                index = self.selected_alert_index.pop(chat_id)
                success, removed = s.remove_price_alert(index)
                if success:
                    self.send_message(chat_id, f"✅ Алерт {removed['symbol']} удален", self.get_price_alerts_keyboard(s))
                else:
                    self.send_message(chat_id, "❌ Не найден", self.get_price_alerts_keyboard(s))
        
        elif text == "🔙 К списку":
            alerts = s.get_user_alerts()
            if alerts:
                self.send_message(chat_id, "📋 Ваши алерты:", self.get_alerts_list_keyboard(alerts))
            else:
                self.send_message(chat_id, "📋 Нет алертов", self.get_price_alerts_keyboard(s))
        
        # Аналитика
        elif text == "📈 Аналитика":
            if not self.check_subscription(chat_id):
                self.send_no_subscription_message(chat_id)
                return
            msg = """📈 АНАЛИТИКА
━━━━━━━━━━━━━━━━━━━━━━━━
Статистика сигналов

Выберите период:
━━━━━━━━━━━━━━━━━━━━━━━━"""
            self.send_message(chat_id, msg, self.get_analytics_keyboard())
        
        elif text in ["📊 1 час", "📊 1ч"]:
            msg = s.format_analytics(s.get_analytics(1))
            self.send_message(chat_id, msg, self.get_analytics_result_keyboard())
        
        elif text in ["📊 6 часов", "📊 6ч"]:
            msg = s.format_analytics(s.get_analytics(6))
            self.send_message(chat_id, msg, self.get_analytics_result_keyboard())
        
        elif text in ["📊 24 часа", "📊 24ч"]:
            msg = s.format_analytics(s.get_analytics(24))
            self.send_message(chat_id, msg, self.get_analytics_result_keyboard())
        
        elif text in ["📊 7 дней", "📊 7д"]:
            msg = s.format_analytics(s.get_analytics(168))
            self.send_message(chat_id, msg, self.get_analytics_result_keyboard())
        
        elif text == "🔄 Обновить":
            msg = s.format_analytics(s.get_analytics(24))
            self.send_message(chat_id, msg, self.get_analytics_result_keyboard())
        
        # Настройки с автосохранением
        elif text == "💱 Quote фильтр":
            self.send_message(chat_id, "💱 Фильтр Quote:", self.get_quote_filter_keyboard(s))
        
        elif "🌐 Все пары" in text:
            s.spot_quote_filter = "all"
            s.last_update = 0
            self.send_message(chat_id, self.save_and_confirm(chat_id, "Quote: Все"), self.get_quote_filter_keyboard(s))
        
        elif "💵 Только USDT" in text:
            s.spot_quote_filter = "usdt"
            s.last_update = 0
            self.send_message(chat_id, self.save_and_confirm(chat_id, "Quote: USDT"), self.get_quote_filter_keyboard(s))
        
        elif "🟠 Только BTC" in text:
            s.spot_quote_filter = "btc"
            s.last_update = 0
            self.send_message(chat_id, self.save_and_confirm(chat_id, "Quote: BTC"), self.get_quote_filter_keyboard(s))
        
        elif "🔷 Только ETH" in text:
            s.spot_quote_filter = "eth"
            s.last_update = 0
            self.send_message(chat_id, self.save_and_confirm(chat_id, "Quote: ETH"), self.get_quote_filter_keyboard(s))
        
        elif "💲 Только USDC" in text:
            s.spot_quote_filter = "usdc"
            s.last_update = 0
            self.send_message(chat_id, self.save_and_confirm(chat_id, "Quote: USDC"), self.get_quote_filter_keyboard(s))
        
        elif text == "🎯 Режим сигналов":
            self.send_message(chat_id, "🎯 Режим:", self.get_signal_mode_keyboard(s))
        
        elif "🚀 Только PUMP" in text:
            s.signal_mode = "pump"
            self.send_message(chat_id, self.save_and_confirm(chat_id, "Режим: PUMP"), self.get_signal_mode_keyboard(s))
        
        elif "💥 Только DUMP" in text:
            s.signal_mode = "dump"
            self.send_message(chat_id, self.save_and_confirm(chat_id, "Режим: DUMP"), self.get_signal_mode_keyboard(s))
        
        elif "📊 PUMP + DUMP" in text:
            s.signal_mode = "both"
            self.send_message(chat_id, self.save_and_confirm(chat_id, "Режим: PUMP+DUMP"), self.get_signal_mode_keyboard(s))
        
        elif text == "🕯 Режим свечей":
            self.send_message(chat_id, "🕯 Свеча:", self.get_candle_mode_keyboard(s))
        
        elif "🟡 Текущая |LIVE|" in text:
            s.candle_mode = "current"
            self.send_message(chat_id, self.save_and_confirm(chat_id, "Свеча: LIVE"), self.get_candle_mode_keyboard(s))
        
        elif "✅ Закрытая |CLOSED|" in text:
            s.candle_mode = "closed"
            self.send_message(chat_id, self.save_and_confirm(chat_id, "Свеча: CLOSED"), self.get_candle_mode_keyboard(s))
        
        elif "📊 Обе" in text and "PUMP" not in text:
            s.candle_mode = "both"
            self.send_message(chat_id, self.save_and_confirm(chat_id, "Свеча: Обе"), self.get_candle_mode_keyboard(s))
        
        elif text == "⚡ Скорость":
            self.send_message(chat_id, "⚡ Скорость:", self.get_speed_keyboard(s))
        
        elif "⚡ " in text and "сек" in text:
            try:
                v = int(text.replace("✅ ", "").replace("⬜ ", "").replace("⚡ ", "").replace(" сек", ""))
                s.scan_interval = v
                self.send_message(chat_id, self.save_and_confirm(chat_id, f"Скорость: {v}с"), self.get_speed_keyboard(s))
            except:
                pass
        
        elif text == "⏱ Таймфрейм":
            self.send_message(chat_id, "⏱ Таймфрейм:", self.get_timeframe_keyboard())
        
        elif text.startswith("🕐 "):
            tf = text[2:].strip()
            if s.set_timeframe(tf):
                self.send_message(chat_id, self.save_and_confirm(chat_id, f"ТФ: {tf}"), self.get_timeframe_keyboard())
        
        elif text == "💹 Мин. процент":
            self.send_message(chat_id, f"📊 Текущий: {s.min_pump}%", self.get_percent_keyboard())
        
        elif text.startswith("📊 ") and "%" in text and "час" not in text and "дн" not in text:
            try:
                v = float(text[2:].replace("%", "").strip())
                s.min_pump = s.min_dump = v
                self.send_message(chat_id, self.save_and_confirm(chat_id, f"Мин: {v}%"), self.get_percent_keyboard())
            except:
                pass
        
        elif text == "✏️ Свой %":
            self.waiting_for_input[chat_id] = 'percent'
            self.send_message(chat_id, "✏️ Введите % (напр: 2.5):", self.get_percent_keyboard())
        
        elif text == "🏪 Тип рынка":
            self.send_message(chat_id, "🏪 Рынок:", self.get_market_keyboard(s))
        
        elif "🌐 Все рынки" in text:
            s.market_type_filter = "all"
            s.last_update = 0
            self.send_message(chat_id, self.save_and_confirm(chat_id, "Рынок: Все"), self.get_market_keyboard(s))
        
        elif "🔮 Только Фьючерсы" in text:
            s.market_type_filter = "futures"
            s.last_update = 0
            self.send_message(chat_id, self.save_and_confirm(chat_id, "Рынок: Futures"), self.get_market_keyboard(s))
        
        elif "💱 Только Спот" in text:
            s.market_type_filter = "spot"
            s.last_update = 0
            self.send_message(chat_id, self.save_and_confirm(chat_id, "Рынок: Spot"), self.get_market_keyboard(s))
        
        elif text == "💰 Мин. объём":
            vol = f"${s.format_number(s.min_volume_usdt)}" if s.min_volume_usdt > 0 else "Выкл"
            self.send_message(chat_id, f"💰 Текущий: {vol}", self.get_volume_keyboard())
        
        elif text == "💵 Без фильтра":
            s.min_volume_usdt = 0
            self.send_message(chat_id, self.save_and_confirm(chat_id, "Объём: без фильтра"), self.get_volume_keyboard())
        
        elif text.startswith("💵 $") and "+" in text:
            try:
                t = text[3:].replace("+", "").upper().strip()
                m = 1
                if t.endswith("K"): m, t = 1000, t[:-1]
                elif t.endswith("M"): m, t = 1000000, t[:-1]
                v = float(t) * m
                s.min_volume_usdt = v
                self.send_message(chat_id, self.save_and_confirm(chat_id, f"Объём: ${s.format_number(v)}"), self.get_volume_keyboard())
            except:
                pass
        
        elif text == "✏️ Свой объём":
            self.waiting_for_input[chat_id] = 'volume'
            self.send_message(chat_id, "✏️ Введите объём (5000, 50K, 1M):", self.get_volume_keyboard())
        
        elif text == "🔄 Дубликаты":
            self.send_message(chat_id, f"🔄 Текущий: {'ВКЛ' if s.allow_duplicates else 'ВЫКЛ'}", self.get_duplicates_keyboard())
        
        elif text == "✅ Дубли ВКЛ":
            s.allow_duplicates = True
            self.send_message(chat_id, self.save_and_confirm(chat_id, "Дубли: ВКЛ"), self.get_duplicates_keyboard())
        
        elif text == "❌ Дубли ВЫКЛ":
            s.allow_duplicates = False
            self.send_message(chat_id, self.save_and_confirm(chat_id, "Дубли: ВЫКЛ"), self.get_duplicates_keyboard())
        
        elif text == "⏰ Кулдаун":
            self.send_message(chat_id, f"⏰ Текущий: {s.alert_cooldown}с", self.get_cooldown_keyboard())
        
        elif text.startswith("🔔 ") and "с" in text:
            try:
                v = int(text[2:].replace("с", "").strip())
                s.alert_cooldown = v
                self.send_message(chat_id, self.save_and_confirm(chat_id, f"Кулдаун: {v}с"), self.get_cooldown_keyboard())
            except:
                pass
        
        elif text == "✏️ Свой КД":
            self.waiting_for_input[chat_id] = 'cooldown'
            self.send_message(chat_id, "✏️ Введите секунды (0-3600):", self.get_cooldown_keyboard())
    
    def run(self):
        print("=" * 60)
        print("🚀 MEXC FULL SCREENER v9.0 WITH CHARTS")
        print("🔮 Futures + 💱 Spot | 📊 Charts | 🎯 Price Alerts")
        print("💾 Auto-save + 👥 Multi-user")
        print("=" * 60)
        
        # Проверка matplotlib
        try:
            import matplotlib
            print("✅ Matplotlib загружен успешно")
        except ImportError:
            print("⚠️ Matplotlib не установлен! Графики будут отключены.")
            print("   Установите: pip install matplotlib")
        
        offset = None
        while True:
            try:
                params = {'timeout': 30, 'allowed_updates': ['message']}
                if offset:
                    params['offset'] = offset
                r = requests.get(f"{self.base_url}/getUpdates", params=params, timeout=35)
                updates = r.json()
                if updates.get('ok'):
                    for u in updates.get('result', []):
                        offset = u['update_id'] + 1
                        if 'message' in u:
                            try:
                                self.handle(u['message'])
                            except Exception as e:
                                print(f"❌ Handle error: {e}")
                                import traceback
                                traceback.print_exc()
            except Exception as e:
                print(f"❌ Polling error: {e}")
                time.sleep(5)


# ═══════════════════════════════════════════════════════════════
# ЗАПУСК БОТА + FLASK
# ═══════════════════════════════════════════════════════════════

def start_bot():
    """Запуск Telegram бота в отдельном потоке"""
    bot = TelegramBot()
    bot.run()

# Запускаем бота в фоновом потоке при импорте модуля
bot_thread = threading.Thread(target=start_bot, daemon=True)
bot_thread.start()
print("🤖 Telegram Bot started in background thread")

if __name__ == "__main__":
    # Локальный запуск
    print("🚀 Starting local server...")
    run_flask()
