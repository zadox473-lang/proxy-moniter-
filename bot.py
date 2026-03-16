"""
Professional Instagram Username Monitor Bot
Enterprise-grade Telegram monitoring system with subscription management
Author: @proxyfxc
Version: 2.0.0
"""

import os
import json
import logging
import asyncio
import datetime
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from pathlib import Path
import sys
import traceback

# Third-party imports
from flask import Flask, jsonify
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
)
from telegram.constants import ParseMode
import aiohttp
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# ==================== CONFIGURATION ====================

class Config:
    """Central configuration management"""
    
    # Bot Configuration
    BOT_TOKEN = os.getenv('BOT_TOKEN', '7728850256:AAE1zUYJ7nEmOIiIN1LzcX8VdLXo8BBk-kk')
    API_KEY = os.getenv('API_KEY', 'PAID_INSTA_SELL187')
    API_BASE_URL = os.getenv('API_BASE_URL', 'https://tg-user-id-to-number-4erk.onrender.com/api')
    
    # Admin Configuration
    OWNER_IDS = [int(id) for id in os.getenv('OWNER_IDS', '7805871651').split(',')]
    
    # Channel Configuration (Force Join)
    REQUIRED_CHANNELS = [
        {'username': '@proxydominates', 'url': 'https://t.me/proxydominates'},
        {'username': '@esxcrows', 'url': 'https://t.me/esxcrows'},
        {'username': '@proxyintfiles', 'url': 'https://t.me/proxyintfiles'},
        {'username': '@nhuDNrfwaaQzM2M1', 'url': 'https://t.me/+nhuDNrfwaaQzM2M1'},
    ]
    
    # User Limits
    DEFAULT_USER_LIMIT = 20  # Free users can monitor up to 20 usernames
    
    # Monitoring Configuration
    CHECK_INTERVAL = 300  # 5 minutes in seconds
    CONFIRMATION_THRESHOLD = 3  # Need 3 consecutive same status to trigger alert
    
    # Flask Keep-alive
    FLASK_HOST = '0.0.0.0'
    FLASK_PORT = int(os.getenv('PORT', 8080))
    
    # Database
    DATA_DIR = 'data'
    USERS_FILE = 'users.json'
    WATCHLIST_FILE = 'watchlist.json'
    BANLIST_FILE = 'banlist.json'
    CONFIRMATIONS_FILE = 'confirmations.json'


# ==================== LOGGING SETUP ====================

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)


# ==================== DATABASE MANAGER ====================

class DatabaseManager:
    """Persistent JSON storage manager with thread-safe operations"""
    
    def __init__(self):
        self.data_dir = Path(Config.DATA_DIR)
        self.data_dir.mkdir(exist_ok=True)
        
        self.users_file = self.data_dir / Config.USERS_FILE
        self.watchlist_file = self.data_dir / Config.WATCHLIST_FILE
        self.banlist_file = self.data_dir / Config.BANLIST_FILE
        self.confirmations_file = self.data_dir / Config.CONFIRMATIONS_FILE
        
        # Initialize data structures
        self.users = self._load_json(self.users_file, {})
        self.watchlist = self._load_json(self.watchlist_file, {})
        self.banlist = self._load_json(self.banlist_file, {})
        self.confirmations = self._load_json(self.confirmations_file, {})
        
        logger.info("Database initialized successfully")
    
    def _load_json(self, file_path: Path, default: Any) -> Any:
        """Load JSON data from file with error handling"""
        try:
            if file_path.exists():
                with open(file_path, 'r') as f:
                    return json.load(f)
            return default
        except Exception as e:
            logger.error(f"Error loading {file_path}: {e}")
            return default
    
    def _save_json(self, file_path: Path, data: Any) -> bool:
        """Save JSON data to file with error handling"""
        try:
            with open(file_path, 'w') as f:
                json.dump(data, f, indent=2)
            return True
        except Exception as e:
            logger.error(f"Error saving {file_path}: {e}")
            return False
    
    def save_all(self):
        """Save all data to disk"""
        self._save_json(self.users_file, self.users)
        self._save_json(self.watchlist_file, self.watchlist)
        self._save_json(self.banlist_file, self.banlist)
        self._save_json(self.confirmations_file, self.confirmations)
        logger.debug("All data saved to disk")
    
    # User Management
    def get_user(self, user_id: int) -> Dict:
        """Get user data by ID"""
        return self.users.get(str(user_id), {})
    
    def create_user(self, user_id: int, username: str = "", first_name: str = "") -> Dict:
        """Create a new user"""
        str_id = str(user_id)
        if str_id not in self.users:
            self.users[str_id] = {
                'user_id': user_id,
                'username': username,
                'first_name': first_name,
                'role': 'user',
                'subscription_expiry': None,
                'joined_date': datetime.now().isoformat(),
                'approved_by': None,
                'approved_days': 0,
                'notification_preferences': {
                    'ban_alerts': True,
                    'unban_alerts': True
                }
            }
            self.save_all()
        return self.users[str_id]
    
    def update_user(self, user_id: int, **kwargs) -> bool:
        """Update user data"""
        str_id = str(user_id)
        if str_id in self.users:
            self.users[str_id].update(kwargs)
            self.save_all()
            return True
        return False
    
    def get_all_users(self) -> Dict:
        """Get all users"""
        return self.users
    
    # Watchlist Management
    def get_watchlist(self, user_id: int) -> List[str]:
        """Get user's watchlist"""
        return self.watchlist.get(str(user_id), [])
    
    def add_to_watchlist(self, user_id: int, username: str) -> bool:
        """Add username to watchlist"""
        str_id = str(user_id)
        if str_id not in self.watchlist:
            self.watchlist[str_id] = []
        
        username = username.lower().strip().lstrip('@')
        if username not in self.watchlist[str_id]:
            self.watchlist[str_id].append(username)
            
            # Initialize confirmation counter
            if username not in self.confirmations:
                self.confirmations[username] = {
                    'status': None,
                    'count': 0,
                    'last_check': None,
                    'details': {}
                }
            else:
                # Reset confirmation if moving from banlist to watchlist
                if self.confirmations[username].get('current_list') == 'ban':
                    self.confirmations[username]['count'] = 0
                    self.confirmations[username]['status'] = None
            
            self.confirmations[username]['current_list'] = 'watch'
            self.save_all()
            return True
        return False
    
    def remove_from_watchlist(self, user_id: int, username: str) -> bool:
        """Remove username from watchlist"""
        str_id = str(user_id)
        if str_id in self.watchlist:
            username = username.lower().strip().lstrip('@')
            if username in self.watchlist[str_id]:
                self.watchlist[str_id].remove(username)
                self.save_all()
                return True
        return False
    
    # Banlist Management
    def get_banlist(self, user_id: int) -> List[str]:
        """Get user's banlist"""
        return self.banlist.get(str(user_id), [])
    
    def add_to_banlist(self, user_id: int, username: str) -> bool:
        """Add username to banlist"""
        str_id = str(user_id)
        if str_id not in self.banlist:
            self.banlist[str_id] = []
        
        username = username.lower().strip().lstrip('@')
        if username not in self.banlist[str_id]:
            self.banlist[str_id].append(username)
            
            # Initialize or update confirmation
            if username not in self.confirmations:
                self.confirmations[username] = {
                    'status': None,
                    'count': 0,
                    'last_check': None,
                    'details': {}
                }
            else:
                # Reset confirmation if moving from watchlist to banlist
                if self.confirmations[username].get('current_list') == 'watch':
                    self.confirmations[username]['count'] = 0
                    self.confirmations[username]['status'] = None
            
            self.confirmations[username]['current_list'] = 'ban'
            self.save_all()
            return True
        return False
    
    def remove_from_banlist(self, user_id: int, username: str) -> bool:
        """Remove username from banlist"""
        str_id = str(user_id)
        if str_id in self.banlist:
            username = username.lower().strip().lstrip('@')
            if username in self.banlist[str_id]:
                self.banlist[str_id].remove(username)
                self.save_all()
                return True
        return False
    
    # Confirmation Management
    def update_confirmation(self, username: str, status: str, details: Dict = None) -> Tuple[bool, int]:
        """
        Update confirmation counter for a username
        Returns: (should_trigger_alert, current_count)
        """
        username = username.lower().strip().lstrip('@')
        
        if username not in self.confirmations:
            self.confirmations[username] = {
                'status': None,
                'count': 0,
                'last_check': None,
                'details': {}
            }
        
        conf = self.confirmations[username]
        old_status = conf['status']
        current_list = conf.get('current_list', 'watch')
        
        # Update last check time
        conf['last_check'] = datetime.now().isoformat()
        
        # If status changed or became unknown, reset counter
        if status == 'UNKNOWN' or (old_status and old_status != status):
            conf['count'] = 0
            conf['status'] = status if status != 'UNKNOWN' else None
            conf['details'] = details or {}
            self.save_all()
            return False, 0
        
        # Same status detected, increment counter
        if old_status == status:
            conf['count'] += 1
            conf['details'] = details or {}
            self.save_all()
            
            # Check if threshold reached
            if conf['count'] >= Config.CONFIRMATION_THRESHOLD:
                # Reset counter after triggering alert
                conf['count'] = 0
                self.save_all()
                return True, Config.CONFIRMATION_THRESHOLD
            return False, conf['count']
        
        # First detection
        conf['status'] = status
        conf['count'] = 1
        conf['details'] = details or {}
        self.save_all()
        return False, 1
    
    def reset_confirmation(self, username: str):
        """Reset confirmation counter for a username"""
        username = username.lower().strip().lstrip('@')
        if username in self.confirmations:
            self.confirmations[username]['count'] = 0
            self.confirmations[username]['status'] = None
            self.save_all()


# ==================== API CLIENT ====================

class InstagramAPIClient:
    """Async API client for Instagram username checking"""
    
    def __init__(self, api_key: str, base_url: str):
        self.api_key = api_key
        self.base_url = base_url
        self.session = None
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session"""
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session
    
    async def check_username(self, username: str) -> Tuple[str, Dict]:
        """
        Check username status
        Returns: (status, details)
        Status: 'BANNED', 'ACTIVE', or 'UNKNOWN'
        """
        try:
            session = await self._get_session()
            url = f"{self.base_url}/insta={username}"
            
            async with session.get(
                url,
                params={'api_key': self.api_key},
                timeout=30
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    
                    # Parse response based on API structure
                    # Assuming API returns something like {"status": "active", "data": {...}}
                    if data.get('error'):
                        return 'UNKNOWN', {}
                    
                    # Check if account is banned (customize based on actual API response)
                    if data.get('is_banned', False) or data.get('status') == 'banned':
                        return 'BANNED', data.get('data', {})
                    else:
                        return 'ACTIVE', data.get('data', {})
                else:
                    logger.warning(f"API returned status {response.status} for {username}")
                    return 'UNKNOWN', {}
                    
        except asyncio.TimeoutError:
            logger.error(f"Timeout checking username {username}")
            return 'UNKNOWN', {}
        except Exception as e:
            logger.error(f"Error checking username {username}: {e}")
            return 'UNKNOWN', {}
    
    async def close(self):
        """Close the session"""
        if self.session and not self.session.closed:
            await self.session.close()


# ==================== MONITORING ENGINE ====================

class MonitoringEngine:
    """Background monitoring engine with confirmation system"""
    
    def __init__(self, db: DatabaseManager, api_client: InstagramAPIClient, bot_app: Application):
        self.db = db
        self.api_client = api_client
        self.bot_app = bot_app
        self.is_running = False
        self.task = None
    
    async def start(self):
        """Start the monitoring engine"""
        if not self.is_running:
            self.is_running = True
            self.task = asyncio.create_task(self._monitoring_loop())
            logger.info("Monitoring engine started")
    
    async def stop(self):
        """Stop the monitoring engine"""
        self.is_running = False
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        logger.info("Monitoring engine stopped")
    
    async def _monitoring_loop(self):
        """Main monitoring loop"""
        while self.is_running:
            try:
                start_time = datetime.now()
                logger.info("Starting monitoring cycle")
                
                # Collect all usernames to check
                usernames_to_check = {}
                
                # Add watchlist items
                for user_id_str, usernames in self.db.watchlist.items():
                    for username in usernames:
                        if username not in usernames_to_check:
                            usernames_to_check[username] = {
                                'user_ids': [],
                                'list_type': 'watch'
                            }
                        usernames_to_check[username]['user_ids'].append(int(user_id_str))
                
                # Add banlist items
                for user_id_str, usernames in self.db.banlist.items():
                    for username in usernames:
                        if username not in usernames_to_check:
                            usernames_to_check[username] = {
                                'user_ids': [],
                                'list_type': 'ban'
                            }
                        usernames_to_check[username]['user_ids'].append(int(user_id_str))
                
                # Check each username
                for username, info in usernames_to_check.items():
                    try:
                        await self._check_single_username(username, info['user_ids'], info['list_type'])
                        # Small delay between checks to avoid rate limiting
                        await asyncio.sleep(1)
                    except Exception as e:
                        logger.error(f"Error checking username {username}: {e}")
                        continue
                
                # Calculate time taken for next cycle
                elapsed = (datetime.now() - start_time).total_seconds()
                sleep_time = max(Config.CHECK_INTERVAL - elapsed, 60)  # Minimum 60 seconds
                
                logger.info(f"Monitoring cycle completed in {elapsed:.2f}s. Next check in {sleep_time:.2f}s")
                await asyncio.sleep(sleep_time)
                
            except asyncio.CancelledError:
                logger.info("Monitoring loop cancelled")
                break
            except Exception as e:
                logger.error(f"Error in monitoring loop: {e}")
                await asyncio.sleep(60)  # Wait a minute before retrying
    
    async def _check_single_username(self, username: str, user_ids: List[int], list_type: str):
        """Check a single username and process results"""
        
        # Check status via API
        status, details = await self.api_client.check_username(username)
        
        # Update confirmation counter
        should_alert, count = self.db.update_confirmation(username, status, details)
        
        # If confirmation threshold reached, process alert
        if should_alert:
            await self._process_alert(username, user_ids, status, list_type, details)
    
    async def _process_alert(self, username: str, user_ids: List[int], status: str, list_type: str, details: Dict):
        """Process and send alerts for confirmed status changes"""
        
        # Get current list type from database
        current_list = self.db.confirmations.get(username, {}).get('current_list', 'watch')
        
        for user_id in user_ids:
            try:
                # Check if user wants notifications
                user_data = self.db.get_user(user_id)
                
                # Determine if this is a ban or unban alert
                if status == 'BANNED' and current_list == 'watch':
                    # Move from watchlist to banlist
                    self.db.remove_from_watchlist(user_id, username)
                    self.db.add_to_banlist(user_id, username)
                    
                    # Send ban alert
                    if user_data.get('notification_preferences', {}).get('ban_alerts', True):
                        await self._send_ban_alert(user_id, username, details)
                        
                elif status == 'ACTIVE' and current_list == 'ban':
                    # Move from banlist to watchlist
                    self.db.remove_from_banlist(user_id, username)
                    self.db.add_to_watchlist(user_id, username)
                    
                    # Send unban alert
                    if user_data.get('notification_preferences', {}).get('unban_alerts', True):
                        await self._send_unban_alert(user_id, username, details)
                        
            except Exception as e:
                logger.error(f"Error processing alert for user {user_id}: {e}")
                continue
    
    async def _send_ban_alert(self, user_id: int, username: str, details: Dict):
        """Send ban alert to user"""
        try:
            message = self._format_ban_alert(username, details)
            await self.bot_app.bot.send_message(
                chat_id=user_id,
                text=message,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=False
            )
        except Exception as e:
            logger.error(f"Failed to send ban alert to {user_id}: {e}")
    
    async def _send_unban_alert(self, user_id: int, username: str, details: Dict):
        """Send unban alert to user"""
        try:
            message = self._format_unban_alert(username, details)
            await self.bot_app.bot.send_message(
                chat_id=user_id,
                text=message,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=False
            )
        except Exception as e:
            logger.error(f"Failed to send unban alert to {user_id}: {e}")
    
    def _format_ban_alert(self, username: str, details: Dict) -> str:
        """Format ban alert message"""
        name = details.get('full_name', username)
        followers = details.get('follower_count', 'N/A')
        following = details.get('following_count', 'N/A')
        posts = details.get('media_count', 'N/A')
        is_private = details.get('is_private', False)
        
        time_info = details.get('detected_time', datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        
        return f"""
🔴 <b>BANNED ACCOUNT DETECTED</b> 🔴

━━━━━━━━━━━━━━━━━━━━━
📸 <b>Profile:</b> @{username}

👤 <b>Name:</b> {name}
👥 <b>Followers:</b> {followers:,}
👤 <b>Following:</b> {following:,}
📸 <b>Posts:</b> {posts:,}
🔐 <b>Private:</b> {'Yes' if is_private else 'No'}

⚠️ <b>Status:</b> <code>BANNED</code>
⏰ <b>Detected:</b> {time_info}

━━━━━━━━━━━━━━━━━━━━━
<i>Account has been automatically moved to Ban List</i>

Powered by @proxyfxc
"""
    
    def _format_unban_alert(self, username: str, details: Dict) -> str:
        """Format unban alert message"""
        name = details.get('full_name', username)
        followers = details.get('follower_count', 'N/A')
        following = details.get('following_count', 'N/A')
        posts = details.get('media_count', 'N/A')
        is_private = details.get('is_private', False)
        
        time_info = details.get('detected_time', datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        
        return f"""
🟢 <b>ACCOUNT UNBANNED</b> 🟢

━━━━━━━━━━━━━━━━━━━━━
📸 <b>Profile:</b> @{username}

👤 <b>Name:</b> {name}
👥 <b>Followers:</b> {followers:,}
👤 <b>Following:</b> {following:,}
📸 <b>Posts:</b> {posts:,}
🔐 <b>Private:</b> {'Yes' if is_private else 'No'}

✅ <b>Status:</b> <code>ACTIVE / UNBANNED</code>
⏰ <b>Detected:</b> {time_info}

━━━━━━━━━━━━━━━━━━━━━
<i>Account has been automatically moved to Watch List</i>

Powered by @proxyfxc
"""


# ==================== FLASK KEEP-ALIVE ====================

app = Flask(__name__)
monitoring_engine = None

@app.route('/')
def home():
    """Health check endpoint"""
    return jsonify({
        'status': 'alive',
        'timestamp': datetime.now().isoformat(),
        'service': 'Instagram Monitor Bot'
    })

@app.route('/health')
def health():
    """Detailed health check"""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'monitoring_active': monitoring_engine.is_running if monitoring_engine else False,
        'users_count': len(db.users) if 'db' in globals() else 0,
        'watchlist_count': sum(len(items) for items in db.watchlist.values()) if 'db' in globals() else 0,
        'banlist_count': sum(len(items) for items in db.banlist.values()) if 'db' in globals() else 0
    })

def run_flask():
    """Run Flask in a separate thread"""
    app.run(host=Config.FLASK_HOST, port=Config.FLASK_PORT)


# ==================== TELEGRAM BOT HANDLERS ====================

class BotHandlers:
    """All Telegram bot command and callback handlers"""
    
    def __init__(self, db: DatabaseManager, api_client: InstagramAPIClient):
        self.db = db
        self.api_client = api_client
    
    # ===== UTILITY FUNCTIONS =====
    
    def is_owner(self, user_id: int) -> bool:
        """Check if user is owner"""
        return user_id in Config.OWNER_IDS
    
    def is_admin(self, user_id: int) -> bool:
        """Check if user is admin or owner"""
        if self.is_owner(user_id):
            return True
        user_data = self.db.get_user(user_id)
        return user_data.get('role') == 'admin'
    
    def has_active_subscription(self, user_id: int) -> bool:
        """Check if user has active subscription"""
        if self.is_admin(user_id):  # Admins have unlimited access
            return True
        
        user_data = self.db.get_user(user_id)
        expiry = user_data.get('subscription_expiry')
        
        if not expiry:
            return False
        
        try:
            expiry_date = datetime.fromisoformat(expiry)
            return expiry_date > datetime.now()
        except:
            return False
    
    def get_user_limit(self, user_id: int) -> int:
        """Get user's monitoring limit"""
        if self.is_admin(user_id):
            return float('inf')  # Unlimited
        return Config.DEFAULT_USER_LIMIT
    
    def get_user_stats(self, user_id: int) -> Tuple[int, int]:
        """Get user's watchlist and banlist counts"""
        watch_count = len(self.db.get_watchlist(user_id))
        ban_count = len(self.db.get_banlist(user_id))
        return watch_count, ban_count
    
    async def check_force_join(self, user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
        """Check if user has joined required channels"""
        try:
            for channel in Config.REQUIRED_CHANNELS:
                try:
                    member = await context.bot.get_chat_member(
                        chat_id=channel['username'],
                        user_id=user_id
                    )
                    if member.status in ['left', 'kicked']:
                        return False
                except Exception as e:
                    logger.warning(f"Could not verify channel {channel['username']}: {e}")
                    # If we can't verify, assume they need to join
                    return False
            return True
        except Exception as e:
            logger.error(f"Error checking force join for user {user_id}: {e}")
            return False
    
    async def send_force_join_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Send force join message with buttons"""
        keyboard = []
        for channel in Config.REQUIRED_CHANNELS:
            keyboard.append([InlineKeyboardButton(
                text=f"📢 Join {channel['username']}",
                url=channel['url']
            )])
        
        keyboard.append([InlineKeyboardButton(
            text="✅ I've Joined",
            callback_data="verify_join"
        )])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        message = """
<b>🔒 CHANNEL SUBSCRIPTION REQUIRED</b>

To use this bot, you must join all of our channels first:

━━━━━━━━━━━━━━━━━━━━━
• Get latest updates
• Important announcements
• Premium features info
━━━━━━━━━━━━━━━━━━━━━

<i>Click the buttons below to join, then click "I've Joined" to verify.</i>
"""
        
        await update.message.reply_text(
            message,
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup,
            disable_web_page_preview=True
        )
    
    # ===== COMMAND HANDLERS =====
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command"""
        user = update.effective_user
        
        # Create or get user
        self.db.create_user(
            user_id=user.id,
            username=user.username or "",
            first_name=user.first_name or ""
        )
        
        # Check force join
        if not await self.check_force_join(user.id, context):
            await self.send_force_join_message(update, context)
            return
        
        # Send welcome message
        welcome_msg = f"""
<b>🚀 INSTAGRAM MONITOR PRO</b>

Welcome <b>{user.first_name}</b>!

━━━━━━━━━━━━━━━━━━━━━
📊 <b>Your Status:</b>
• Role: <code>{self.db.get_user(user.id).get('role', 'user').upper()}</code>
• Subscription: <code>{'Active' if self.has_active_subscription(user.id) else 'Inactive'}</code>
• Watch List: <code>{len(self.db.get_watchlist(user.id))}/{self.get_user_limit(user.id)}</code>
• Ban List: <code>{len(self.db.get_banlist(user.id))}</code>
━━━━━━━━━━━━━━━━━━━━━

<b>📌 Available Commands:</b>
/watch - Manage your watch list
/ban - Manage your ban list
/status - View monitoring status
/help - Get help & info

<i>Powered by @proxyfxc</i>
"""
        
        # Create main menu keyboard
        keyboard = [
            [InlineKeyboardButton("📋 Watch List", callback_data="menu_watch"),
             InlineKeyboardButton("🚫 Ban List", callback_data="menu_ban")],
            [InlineKeyboardButton("📊 Status", callback_data="menu_status"),
             InlineKeyboardButton("ℹ️ Help", callback_data="menu_help")]
        ]
        
        if self.is_admin(user.id):
            keyboard.append([InlineKeyboardButton("⚙️ Admin Panel", callback_data="menu_admin")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            welcome_msg,
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup,
            disable_web_page_preview=True
        )
        
        # Notify owner about new user
        if not self.is_admin(user.id):
            for owner_id in Config.OWNER_IDS:
                try:
                    await context.bot.send_message(
                        chat_id=owner_id,
                        text=f"👤 <b>New User Alert</b>\n\nUser: {user.first_name}\nID: <code>{user.id}</code>\nUsername: @{user.username or 'N/A'}",
                        parse_mode=ParseMode.HTML
                    )
                except:
                    pass
    
    async def watch_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /watch command"""
        user = update.effective_user
        
        # Check force join
        if not await self.check_force_join(user.id, context):
            await self.send_force_join_message(update, context)
            return
        
        watchlist = self.db.get_watchlist(user.id)
        watch_count = len(watchlist)
        limit = self.get_user_limit(user.id)
        
        message = f"""
<b>📋 WATCH LIST MANAGEMENT</b>

━━━━━━━━━━━━━━━━━━━━━
📊 <b>Statistics:</b>
• Current: <code>{watch_count}/{limit if limit != float('inf') else '∞'}</code>
• Active Subscription: <code>{'Yes' if self.has_active_subscription(user.id) else 'No'}</code>
━━━━━━━━━━━━━━━━━━━━━

<b>📝 Your Watch List:</b>
"""
        
        if watchlist:
            for i, username in enumerate(watchlist[:10], 1):
                message += f"{i}. @{username}\n"
            if len(watchlist) > 10:
                message += f"...and {len(watchlist) - 10} more\n"
        else:
            message += "<i>No usernames in watch list</i>\n"
        
        message += "\n<b>🔧 Commands:</b>\n/addwatch [username] - Add to watch list\n/removewatch [username] - Remove from watch list"
        
        await update.message.reply_text(
            message,
            parse_mode=ParseMode.HTML
        )
    
    async def ban_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /ban command"""
        user = update.effective_user
        
        # Check force join
        if not await self.check_force_join(user.id, context):
            await self.send_force_join_message(update, context)
            return
        
        banlist = self.db.get_banlist(user.id)
        
        message = f"""
<b>🚫 BAN LIST MANAGEMENT</b>

━━━━━━━━━━━━━━━━━━━━━
📊 <b>Statistics:</b>
• Banned Accounts: <code>{len(banlist)}</code>
━━━━━━━━━━━━━━━━━━━━━

<b>📝 Your Ban List:</b>
"""
        
        if banlist:
            for i, username in enumerate(banlist[:10], 1):
                message += f"{i}. @{username}\n"
            if len(banlist) > 10:
                message += f"...and {len(banlist) - 10} more\n"
        else:
            message += "<i>No usernames in ban list</i>\n"
        
        message += "\n<b>🔧 Commands:</b>\n/addban [username] - Add to ban list\n/removeban [username] - Remove from ban list"
        
        await update.message.reply_text(
            message,
            parse_mode=ParseMode.HTML
        )
    
    async def status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /status command"""
        user = update.effective_user
        
        # Check force join
        if not await self.check_force_join(user.id, context):
            await self.send_force_join_message(update, context)
            return
        
        watch_count, ban_count = self.get_user_stats(user.id)
        user_data = self.db.get_user(user.id)
        expiry = user_data.get('subscription_expiry')
        
        if expiry:
            try:
                expiry_date = datetime.fromisoformat(expiry)
                days_left = (expiry_date - datetime.now()).days
                expiry_str = f"{expiry_date.strftime('%Y-%m-%d')} ({days_left} days left)"
            except:
                expiry_str = "Invalid"
        else:
            expiry_str = "No active subscription"
        
        message = f"""
<b>📊 ACCOUNT STATUS</b>

━━━━━━━━━━━━━━━━━━━━━
👤 <b>User:</b> {user.first_name}
🆔 <b>ID:</b> <code>{user.id}</code>
👑 <b>Role:</b> <code>{user_data.get('role', 'user').upper()}</code>
📅 <b>Joined:</b> {user_data.get('joined_date', 'Unknown')[:10]}
💳 <b>Subscription:</b> <code>{'Active' if self.has_active_subscription(user.id) else 'Inactive'}</code>
⏰ <b>Expires:</b> {expiry_str}

━━━━━━━━━━━━━━━━━━━━━
📋 <b>Watch List:</b> {watch_count} / {self.get_user_limit(user.id) if self.get_user_limit(user.id) != float('inf') else '∞'}
🚫 <b>Ban List:</b> {ban_count}
━━━━━━━━━━━━━━━━━━━━━

<i>Powered by @proxyfxc</i>
"""
        
        await update.message.reply_text(
            message,
            parse_mode=ParseMode.HTML
        )
    
    async def addwatch_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /addwatch command"""
        user = update.effective_user
        
        # Check force join
        if not await self.check_force_join(user.id, context):
            await self.send_force_join_message(update, context)
            return
        
        # Check subscription
        if not self.has_active_subscription(user.id) and not self.is_admin(user.id):
            await update.message.reply_text(
                "❌ <b>Subscription Required</b>\n\nYou need an active subscription to add usernames.\n\nContact an admin to purchase access.",
                parse_mode=ParseMode.HTML
            )
            return
        
        # Check limit
        current_count = len(self.db.get_watchlist(user.id))
        limit = self.get_user_limit(user.id)
        
        if current_count >= limit and limit != float('inf'):
            await update.message.reply_text(
                f"❌ <b>Limit Reached</b>\n\nYou've reached your maximum limit of {limit} usernames.\n\nUpgrade your subscription to add more.",
                parse_mode=ParseMode.HTML
            )
            return
        
        # Get username from command
        args = context.args
        if not args:
            await update.message.reply_text(
                "❌ <b>Usage:</b> /addwatch [username]\n\nExample: /addwatch cristiano",
                parse_mode=ParseMode.HTML
            )
            return
        
        username = args[0].lower().strip().lstrip('@')
        
        # Check if already in watchlist
        watchlist = self.db.get_watchlist(user.id)
        if username in watchlist:
            await update.message.reply_text(
                f"⚠️ @{username} is already in your watch list.",
                parse_mode=ParseMode.HTML
            )
            return
        
        # Add to watchlist
        self.db.add_to_watchlist(user.id, username)
        
        await update.message.reply_text(
            f"✅ <b>Username Added</b>\n\n@{username} has been added to your watch list.\n\n<i>You will be notified when status changes.</i>",
            parse_mode=ParseMode.HTML
        )
    
    async def removewatch_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /removewatch command"""
        user = update.effective_user
        
        # Check force join
        if not await self.check_force_join(user.id, context):
            await self.send_force_join_message(update, context)
            return
        
        args = context.args
        if not args:
            await update.message.reply_text(
                "❌ <b>Usage:</b> /removewatch [username]\n\nExample: /removewatch cristiano",
                parse_mode=ParseMode.HTML
            )
            return
        
        username = args[0].lower().strip().lstrip('@')
        
        if self.db.remove_from_watchlist(user.id, username):
            await update.message.reply_text(
                f"✅ @{username} has been removed from your watch list.",
                parse_mode=ParseMode.HTML
            )
        else:
            await update.message.reply_text(
                f"❌ @{username} not found in your watch list.",
                parse_mode=ParseMode.HTML
            )
    
    async def addban_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /addban command"""
        user = update.effective_user
        
        # Check force join
        if not await self.check_force_join(user.id, context):
            await self.send_force_join_message(update, context)
            return
        
        # Check subscription
        if not self.has_active_subscription(user.id) and not self.is_admin(user.id):
            await update.message.reply_text(
                "❌ <b>Subscription Required</b>\n\nYou need an active subscription to add usernames.",
                parse_mode=ParseMode.HTML
            )
            return
        
        args = context.args
        if not args:
            await update.message.reply_text(
                "❌ <b>Usage:</b> /addban [username]\n\nExample: /addban cristiano",
                parse_mode=ParseMode.HTML
            )
            return
        
        username = args[0].lower().strip().lstrip('@')
        
        # Check if already in banlist
        banlist = self.db.get_banlist(user.id)
        if username in banlist:
            await update.message.reply_text(
                f"⚠️ @{username} is already in your ban list.",
                parse_mode=ParseMode.HTML
            )
            return
        
        # Add to banlist
        self.db.add_to_banlist(user.id, username)
        
        await update.message.reply_text(
            f"✅ <b>Username Added to Ban List</b>\n\n@{username} has been added to your ban list.\n\n<i>You will be notified when it becomes active again.</i>",
            parse_mode=ParseMode.HTML
        )
    
    async def removeban_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /removeban command"""
        user = update.effective_user
        
        # Check force join
        if not await self.check_force_join(user.id, context):
            await self.send_force_join_message(update, context)
            return
        
        args = context.args
        if not args:
            await update.message.reply_text(
                "❌ <b>Usage:</b> /removeban [username]\n\nExample: /removeban cristiano",
                parse_mode=ParseMode.HTML
            )
            return
        
        username = args[0].lower().strip().lstrip('@')
        
        if self.db.remove_from_banlist(user.id, username):
            await update.message.reply_text(
                f"✅ @{username} has been removed from your ban list.",
                parse_mode=ParseMode.HTML
            )
        else:
            await update.message.reply_text(
                f"❌ @{username} not found in your ban list.",
                parse_mode=ParseMode.HTML
            )
    
    # ===== ADMIN COMMANDS =====
    
    async def approve_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /approve command (Admin only)"""
        user = update.effective_user
        
        if not self.is_admin(user.id):
            await update.message.reply_text("❌ You don't have permission to use this command.")
            return
        
        args = context.args
        if len(args) < 2:
            await update.message.reply_text(
                "❌ <b>Usage:</b> /approve [user_id] [days]\n\nExample: /approve 123456789 30",
                parse_mode=ParseMode.HTML
            )
            return
        
        try:
            target_id = int(args[0])
            days = int(args[1])
        except ValueError:
            await update.message.reply_text("❌ Invalid user ID or days. Please provide numbers.")
            return
        
        # Calculate expiry
        expiry_date = datetime.now() + timedelta(days=days)
        
        # Update user
        if self.db.update_user(
            target_id,
            role='user',
            subscription_expiry=expiry_date.isoformat(),
            approved_by=user.id,
            approved_days=days
        ):
            await update.message.reply_text(
                f"✅ <b>User Approved</b>\n\nUser ID: <code>{target_id}</code>\nDays: {days}\nExpires: {expiry_date.strftime('%Y-%m-%d')}\n\n<i>User has been granted monitoring access.</i>",
                parse_mode=ParseMode.HTML
            )
            
            # Notify user
            try:
                await context.bot.send_message(
                    chat_id=target_id,
                    text=f"""
✅ <b>SUBSCRIPTION APPROVED</b>

━━━━━━━━━━━━━━━━━━━━━
Your subscription has been approved!
📅 <b>Duration:</b> {days} days
⏰ <b>Expires:</b> {expiry_date.strftime('%Y-%m-%d')}

You can now add up to {Config.DEFAULT_USER_LIMIT} usernames to monitor.
━━━━━━━━━━━━━━━━━━━━━

<i>Powered by @proxyfxc</i>
""",
                    parse_mode=ParseMode.HTML
                )
            except:
                pass
        else:
            await update.message.reply_text("❌ User not found.")
    
    async def addadmin_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /addadmin command (Owner only)"""
        user = update.effective_user
        
        if not self.is_owner(user.id):
            await update.message.reply_text("❌ Only the owner can use this command.")
            return
        
        args = context.args
        if not args:
            await update.message.reply_text(
                "❌ <b>Usage:</b> /addadmin [user_id]\n\nExample: /addadmin 123456789",
                parse_mode=ParseMode.HTML
            )
            return
        
        try:
            target_id = int(args[0])
        except ValueError:
            await update.message.reply_text("❌ Invalid user ID.")
            return
        
        if self.db.update_user(target_id, role='admin'):
            await update.message.reply_text(
                f"✅ <b>Admin Added</b>\n\nUser ID: <code>{target_id}</code>\n\n<i>This user now has admin privileges.</i>",
                parse_mode=ParseMode.HTML
            )
            
            # Notify new admin
            try:
                await context.bot.send_message(
                    chat_id=target_id,
                    text=f"""
👑 <b>ADMIN PRIVILEGES GRANTED</b>

━━━━━━━━━━━━━━━━━━━━━
You've been promoted to Admin!
Now you can:
• Approve user subscriptions
• Send broadcasts
• Unlimited monitoring
━━━━━━━━━━━━━━━━━━━━━

<i>Powered by @proxyfxc</i>
""",
                    parse_mode=ParseMode.HTML
                )
            except:
                pass
        else:
            await update.message.reply_text("❌ User not found.")
    
    async def broadcast_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /broadcast command (Admin only)"""
        user = update.effective_user
        
        if not self.is_admin(user.id):
            await update.message.reply_text("❌ You don't have permission to use this command.")
            return
        
        # Check if there's a message to broadcast
        if not context.args and not update.message.reply_to_message:
            await update.message.reply_text(
                "❌ <b>Usage:</b> /broadcast [message]\n\nOr reply to a message with /broadcast",
                parse_mode=ParseMode.HTML
            )
            return
        
        # Get broadcast message
        if update.message.reply_to_message:
            message = update.message.reply_to_message.text or update.message.reply_to_message.caption
        else:
            message = ' '.join(context.args)
        
        if not message:
            await update.message.reply_text("❌ No message to broadcast.")
            return
        
        # Send initial status
        status_msg = await update.message.reply_text(
            "📤 <b>Broadcasting message...</b>\n\nThis may take a few moments.",
            parse_mode=ParseMode.HTML
        )
        
        # Get all users
        users = self.db.get_all_users()
        total = len(users)
        success = 0
        failed = 0
        
        # Send broadcast
        for user_id_str in users:
            try:
                await context.bot.send_message(
                    chat_id=int(user_id_str),
                    text=f"""
📢 <b>BROADCAST MESSAGE</b>

━━━━━━━━━━━━━━━━━━━━━
{message}
━━━━━━━━━━━━━━━━━━━━━

<i>Powered by @proxyfxc</i>
""",
                    parse_mode=ParseMode.HTML
                )
                success += 1
            except Exception as e:
                failed += 1
                logger.warning(f"Broadcast failed for user {user_id_str}: {e}")
            
            # Small delay to avoid flooding
            await asyncio.sleep(0.05)
        
        # Update status
        await status_msg.edit_text(
            f"✅ <b>Broadcast Complete</b>\n\n📊 <b>Statistics:</b>\n• Total Users: {total}\n• Success: {success}\n• Failed: {failed}",
            parse_mode=ParseMode.HTML
        )
    
    # ===== CALLBACK HANDLERS =====
    
    async def button_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle button callbacks"""
        query = update.callback_query
        await query.answer()
        
        user = update.effective_user
        data = query.data
        
        # Check force join for menu actions
        if not data.startswith('verify_join'):
            if not await self.check_force_join(user.id, context):
                await query.edit_message_text(
                    "❌ You need to join our channels first.\nUse /start to verify.",
                    parse_mode=ParseMode.HTML
                )
                return
        
        if data == "verify_join":
            # Verify channel join
            if await self.check_force_join(user.id, context):
                await query.edit_message_text(
                    "✅ <b>Verification Successful!</b>\n\nYou can now use the bot.\n\nSend /start to begin.",
                    parse_mode=ParseMode.HTML
                )
            else:
                await query.edit_message_text(
                    "❌ <b>Verification Failed</b>\n\nPlease join all channels and try again.",
                    parse_mode=ParseMode.HTML
                )
        
        elif data == "menu_watch":
            await self.watch_command(update, context)
        
        elif data == "menu_ban":
            await self.ban_command(update, context)
        
        elif data == "menu_status":
            await self.status_command(update, context)
        
        elif data == "menu_help":
            help_text = """
<b>📚 HELP & SUPPORT</b>

━━━━━━━━━━━━━━━━━━━━━
<b>📌 Basic Commands:</b>
/watch - Manage your watch list
/ban - Manage your ban list
/status - View your account status
/help - Show this help message

<b>🔧 Watch List Commands:</b>
/addwatch [username] - Add to watch list
/removewatch [username] - Remove from watch list

<b>🚫 Ban List Commands:</b>
/addban [username] - Add to ban list
/removeban [username] - Remove from ban list

<b>⚙️ Admin Commands:</b>
/approve [user_id] [days] - Approve user
/broadcast [message] - Send broadcast
/addadmin [user_id] - Add admin (Owner only)

━━━━━━━━━━━━━━━━━━━━━
<b>📊 How It Works:</b>
• Bot checks usernames every 5 minutes
• 3 confirmations needed for alerts
• Auto moves between lists
• Real-time notifications

<i>Powered by @proxyfxc</i>
"""
            await query.edit_message_text(
                help_text,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True
            )
        
        elif data == "menu_admin" and self.is_admin(user.id):
            admin_text = f"""
<b>⚙️ ADMIN PANEL</b>

━━━━━━━━━━━━━━━━━━━━━
<b>📊 System Status:</b>
• Total Users: {len(self.db.get_all_users())}
• Watchlist Items: {sum(len(items) for items in self.db.watchlist.values())}
• Banlist Items: {sum(len(items) for items in self.db.banlist.values())}
━━━━━━━━━━━━━━━━━━━━━

<b>📌 Admin Commands:</b>
/approve [user_id] [days] - Approve user
/broadcast [message] - Send broadcast
/addadmin [user_id] - Add admin (Owner only)

<i>Powered by @proxyfxc</i>
"""
            await query.edit_message_text(
                admin_text,
                parse_mode=ParseMode.HTML
            )


# ==================== MAIN APPLICATION ====================

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle errors gracefully"""
    logger.error(f"Exception while handling an update: {context.error}")
    
    try:
        if update and update.effective_chat:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="⚠️ <b>An error occurred</b>\n\nOur team has been notified. Please try again later.",
                parse_mode=ParseMode.HTML
            )
    except:
        pass

def main():
    """Main entry point"""
    global db, monitoring_engine
    
    # Initialize database
    db = DatabaseManager()
    
    # Initialize API client
    api_client = InstagramAPIClient(Config.API_KEY, Config.API_BASE_URL)
    
    # Create application
    application = (
        Application.builder()
        .token(Config.BOT_TOKEN)
        .concurrent_updates(True)
        .build()
    )
    
    # Initialize handlers
    handlers = BotHandlers(db, api_client)
    
    # Add command handlers
    application.add_handler(CommandHandler("start", handlers.start_command))
    application.add_handler(CommandHandler("watch", handlers.watch_command))
    application.add_handler(CommandHandler("ban", handlers.ban_command))
    application.add_handler(CommandHandler("status", handlers.status_command))
    application.add_handler(CommandHandler("addwatch", handlers.addwatch_command))
    application.add_handler(CommandHandler("removewatch", handlers.removewatch_command))
    application.add_handler(CommandHandler("addban", handlers.addban_command))
    application.add_handler(CommandHandler("removeban", handlers.removeban_command))
    application.add_handler(CommandHandler("approve", handlers.approve_command))
    application.add_handler(CommandHandler("addadmin", handlers.addadmin_command))
    application.add_handler(CommandHandler("broadcast", handlers.broadcast_command))
    
    # Add callback query handler
    application.add_handler(CallbackQueryHandler(handlers.button_callback))
    
    # Add error handler
    application.add_error_handler(error_handler)
    
    # Initialize and start monitoring engine
    monitoring_engine = MonitoringEngine(db, api_client, application)
    
    # Start monitoring in background
    asyncio.create_task(monitoring_engine.start())
    
    # Start Flask in a separate thread
    import threading
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    
    # Start bot
    logger.info("Starting bot...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
