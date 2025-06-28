import base64
import datetime
import json
import logging
import os
import re
import uuid
from logging.handlers import RotatingFileHandler

import nest_asyncio
import requests
from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (ApplicationBuilder, CallbackQueryHandler,
                          CommandHandler, ContextTypes, ConversationHandler,
                          MessageHandler, filters)

# Setup application constants and environment
APP_NAME = "Bingwa Data Deals Bot"
APP_VERSION = "1.0.0"
SUPPORT_CONTACT = "@bingwamta"  # Telegram username for support

# Configure logging with more detailed format and file rotation
log_dir = "logs"
if not os.path.exists(log_dir):
    os.makedirs(log_dir)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s',
    handlers=[
        RotatingFileHandler(
            f"{log_dir}/data_bot.log", 
            maxBytes=10485760,  # 10MB
            backupCount=5
        ),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

# Allow nested event loops (useful for environments like Jupyter)
nest_asyncio.apply()

# Load environment variables from .env file
load_dotenv()

# Environment variables
API_USERNAME = os.getenv('API_USERNAME')
API_PASSWORD = os.getenv('API_PASSWORD')
BOT_TOKEN = os.getenv('BOT_TOKEN')
ADMIN_USER_IDS = os.getenv('ADMIN_USER_IDS', '').split(',')

# Validate environment configuration
if not all([API_USERNAME, API_PASSWORD, BOT_TOKEN]):
    logger.error("API_USERNAME, API_PASSWORD, and BOT_TOKEN must be set in the environment.")
    raise EnvironmentError("Required environment variables not set. Please check your .env file.")

# Create Basic Auth token
credentials = f"{API_USERNAME}:{API_PASSWORD}"
encoded_credentials = base64.b64encode(credentials.encode()).decode()
basic_auth_token = f"Basic {encoded_credentials}"

# Define Conversation States
CHOOSING_PACKAGE, GETTING_PHONE, CONFIRMING_PURCHASE = range(3)

# Admin conversation states
ADMIN_COMMAND, ADMIN_BROADCAST_MESSAGE = range(100, 102)

# File to store user data
USER_DATA_FILE = "user_data.json"

# ===== Data Models =====

class DataPackage:
    """Model class for data package offers"""
    def __init__(self, display_name, price, size, validity="", description=""):
        self.display_name = display_name
        self.price = price
        self.size = size
        self.validity = validity
        self.description = description
        
    def get_full_display(self):
        """Returns a formatted display string for the package"""
        return self.display_name
    
    def get_details_display(self):
        """Returns detailed information about the package"""
        return f"{self.display_name}\n" + \
               (f"Data: {self.size}\n" if self.size else "") + \
               (f"Validity: {self.validity}\n" if self.validity else "") + \
               (f"Description: {self.description}" if self.description else "")

# ===== Package Definitions =====

# Define data packages with callback_data matching dictionary keys based on the provided data
data_packages = {
    # Bingwa Data Deals
    'data_1': DataPackage('1.25GB till midnight @ Ksh 55', 55, "1.25GB", "Until midnight", "Same day data bundle"),
    'data_2': DataPackage('250MB for 24hrs @ Ksh 18', 18, "250MB", "24 Hours", "Daily data bundle"),
    'data_3': DataPackage('1GB for 1hr @ Ksh 19', 19, "1GB", "1 Hour", "Hourly data bundle"),
    'data_4': DataPackage('Internet access for 3hrs @ Ksh 49', 49, "Unlimited", "3 Hours", "Hourly access bundle"),
    'data_5': DataPackage('1GB for 24hrs @ Ksh 95', 95, "1GB", "24 Hours", "Daily data bundle"),
    'data_6': DataPackage('350MB for 7 days @ Ksh 47', 47, "350MB", "7 Days", "Weekly data bundle"),
    'data_7': DataPackage('2GB for 24hrs @ Ksh 100', 100, "2GB", "24 Hours", "Daily data bundle"),
    'data_8': DataPackage('1.2GB for 30days @ Ksh 250', 250, "1.2GB", "30 Days", "Monthly data bundle"),
    
    # Normal Data Deals
    'data_9': DataPackage('1GB for 1hr @ Ksh 20', 20, "1GB", "1 Hour", "Hourly data bundle"),
    'data_10': DataPackage('1.5GB for 3hrs @ Ksh 50', 50, "1.5GB", "3 Hours", "Hourly data bundle"),
    'data_11': DataPackage('2GB for 24hrs @ Ksh 100', 100, "2GB", "24 Hours", "Daily data bundle")
}

# ===== Helper Functions =====

def is_valid_phone_number(phone):
    """Validate Kenyan phone number format"""
    # Check if the number is a valid Kenyan format
    # Accepts formats: 07XXXXXXXX, 01XXXXXXXX, +254XXXXXXXXX, 254XXXXXXXXX
    
    # Remove any spaces or special characters
    phone = re.sub(r'[\s\-\(\)]', '', phone)
    
    # Define patterns for Kenyan phone numbers
    patterns = [
        r'^(?:\+254|254)?(7\d{8})$',  # Mobile numbers starting with 7
        r'^(?:\+254|254)?(1\d{8})$',   # Mobile numbers starting with 1
        r'^0(7\d{8})$',               # Mobile numbers with leading 0
        r'^0(1\d{8})$'                # Mobile numbers with leading 0
    ]
    
    for pattern in patterns:
        match = re.match(pattern, phone)
        if match:
            # Format to standard 254XXXXXXXXX format
            return f"254{match.group(1)}"
    
    return None

def format_timestamp():
    """Return a formatted timestamp for transaction references"""
    return datetime.datetime.now().strftime("%Y%m%d%H%M%S")

def generate_reference():
    """Generate a unique reference for transactions"""
    return f"BINGWA-{format_timestamp()}-{str(uuid.uuid4())[:8]}"

def is_admin(user_id):
    """Check if a user is an admin"""
    return str(user_id) in ADMIN_USER_IDS

def load_user_data():
    """Load user data from file"""
    if os.path.exists(USER_DATA_FILE):
        try:
            with open(USER_DATA_FILE, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading user data: {e}")
            return {"users": []}
    return {"users": []}

def save_user_data(data):
    """Save user data to file"""
    try:
        with open(USER_DATA_FILE, 'w') as f:
            json.dump(data, f, indent=2)
        return True
    except Exception as e:
        logger.error(f"Error saving user data: {e}")
        return False

def register_user(user):
    """Register a user in the database"""
    data = load_user_data()
    user_id = str(user.id)
    
    # Check if user already exists
    for existing_user in data["users"]:
        if existing_user["id"] == user_id:
            # Update user data
            existing_user["username"] = user.username
            existing_user["first_name"] = user.first_name
            existing_user["last_name"] = user.last_name
            existing_user["last_active"] = datetime.datetime.now().isoformat()
            save_user_data(data)
            return
    
    # Add new user
    data["users"].append({
        "id": user_id,
        "username": user.username,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "joined": datetime.datetime.now().isoformat(),
        "last_active": datetime.datetime.now().isoformat()
    })
    
    save_user_data(data)

# ===== Bot Command Handlers =====

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Send a welcome message and show data bundles menu."""
    user = update.effective_user
    user_first_name = user.first_name
    
    # Register user
    register_user(user)
    
    # Clear any existing conversation data
    context.user_data.clear()
    
    logger.info(f"User {user.id} ({user_first_name}) started the bot")
    
    welcome_message = (
        f"Welcome to {APP_NAME}, {user_first_name}!\n\n"
        f"I can help you purchase mobile data bundles quickly and easily.\n\n"
        f"Need help? Contact our support at {SUPPORT_CONTACT} or call 0707071631"
    )
    
    await update.message.reply_text(welcome_message)
    
    # Show data bundles menu directly
    return await show_bundles(update, context)

async def contact_support(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Provide support contact information."""
    user = update.effective_user
    
    # Register user
    register_user(user)
    
    logger.info(f"User {user.id} requested support contact information")
    
    support_message = (
        "📞 *Customer Support*\n\n"
        f"If you need assistance, please contact us through:\n\n"
        f"• Telegram: {SUPPORT_CONTACT}\n"
        f"• Phone: 0707071631\n\n"
        "We're here to help you with any questions or issues!"
    )
    
    await update.message.reply_text(support_message, parse_mode='Markdown')
    return ConversationHandler.END

async def show_bundles(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Display the main categories of bundles."""
    user = update.effective_user
    
    # Register user
    register_user(user)
    
    logger.info(f"User {user.id} accessed the bundles menu")
    
    keyboard = [
        [InlineKeyboardButton("🚀 Bingwa Data Deals", callback_data='bingwa_deals')],
        [InlineKeyboardButton("📱 Normal Data Deals", callback_data='normal_deals')],
        [InlineKeyboardButton("📞 Customer Support", callback_data='support')],
        [InlineKeyboardButton("❌ Cancel", callback_data='cancel_purchase')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    message = await update.message.reply_text(
        "Welcome to Bingwa Data Deals! Please select a category:",
        reply_markup=reply_markup
    )
    
    # Store the message for future deletion
    context.user_data['last_message'] = message
    
    return CHOOSING_PACKAGE

async def show_bingwa_deals(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Show Bingwa data deals packages."""
    query = update.callback_query
    await query.answer()
    
    user = update.effective_user
    logger.info(f"User {user.id} selected Bingwa Data Deals")
    
    # Filter packages
    bingwa_packages = {k: v for k, v in data_packages.items() if int(k.split('_')[1]) <= 8}
    
    # Create keyboard for packages
    keyboard = []
    for key, package in bingwa_packages.items():
        keyboard.append([InlineKeyboardButton(package.get_full_display(), callback_data=key)])
    
    keyboard.append([InlineKeyboardButton("⬅️ Back to Categories", callback_data='back_to_categories')])
    keyboard.append([InlineKeyboardButton("📞 Customer Support", callback_data='support')])
    keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data='cancel_purchase')])

    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Delete previous message if exists
    try:
        await query.message.delete()
    except Exception as e:
        logger.warning(f"Could not delete previous message: {e}")
    
    # Send new message
    new_message = await query.message.reply_text(
        "🚀 *Bingwa Data Deals*\n\n"
        "Our special selection of premium data bundles. Please select a package:",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )
    
    # Store new message for future deletion
    context.user_data['last_message'] = new_message
    
    return CHOOSING_PACKAGE

async def show_normal_deals(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Show normal data deals packages."""
    query = update.callback_query
    await query.answer()
    
    user = update.effective_user
    logger.info(f"User {user.id} selected Normal Data Deals")
    
    # Filter packages
    normal_packages = {k: v for k, v in data_packages.items() if int(k.split('_')[1]) > 8}
    
    # Create keyboard for packages
    keyboard = []
    for key, package in normal_packages.items():
        keyboard.append([InlineKeyboardButton(package.get_full_display(), callback_data=key)])
    
    keyboard.append([InlineKeyboardButton("⬅️ Back to Categories", callback_data='back_to_categories')])
    keyboard.append([InlineKeyboardButton("📞 Customer Support", callback_data='support')])
    keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data='cancel_purchase')])

    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Delete previous message if exists
    try:
        await query.message.delete()
    except Exception as e:
        logger.warning(f"Could not delete previous message: {e}")
    
    # Send new message
    new_message = await query.message.reply_text(
        "📱 *Normal Data Deals*\n\n"
        "Standard data bundles available for purchase. Please select a package:",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )
    
    # Store new message for future deletion
    context.user_data['last_message'] = new_message
    
    return CHOOSING_PACKAGE

async def back_to_categories(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Go back to showing categories."""
    query = update.callback_query
    await query.answer()
    
    keyboard = [
        [InlineKeyboardButton("🚀 Bingwa Data Deals", callback_data='bingwa_deals')],
        [InlineKeyboardButton("📱 Normal Data Deals", callback_data='normal_deals')],
        [InlineKeyboardButton("📞 Customer Support", callback_data='support')],
        [InlineKeyboardButton("❌ Cancel", callback_data='cancel_purchase')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Delete previous message if exists
    try:
        await query.message.delete()
    except Exception as e:
        logger.warning(f"Could not delete previous message: {e}")
    
    # Send new message
    new_message = await query.message.reply_text(
        "Please select a category:",
        reply_markup=reply_markup
    )
    
    # Store new message for future deletion
    context.user_data['last_message'] = new_message
    
    return CHOOSING_PACKAGE

async def choose_package(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle the selection of a specific package."""
    query = update.callback_query
    await query.answer()
    
    user = update.effective_user
    choice = query.data
    
    # Handle navigation options
    if choice == 'back_to_categories':
        return await back_to_categories(update, context)
    elif choice == 'bingwa_deals':
        return await show_bingwa_deals(update, context)
    elif choice == 'normal_deals':
        return await show_normal_deals(update, context)
    elif choice == 'support':
        return await handle_support_button(update, context)
    elif choice == 'cancel_purchase':
        return await cancel_purchase(update, context)
    
    # Handle package selection
    selected_package = data_packages.get(choice)
    
    if not selected_package:
        logger.error(f"Invalid package selection: {choice}")
        await query.message.reply_text("Invalid package selection. Please try again.")
        return CHOOSING_PACKAGE
    
    logger.info(f"User {user.id} selected package: {choice}")
    context.user_data['package'] = selected_package
    context.user_data['package_key'] = choice
    
    # Delete previous message if exists
    try:
        await query.message.delete()
    except Exception as e:
        logger.warning(f"Could not delete previous message: {e}")
    
    # Send new message asking for phone number
    new_message = await query.message.reply_text(
        f"You selected: {selected_package.get_details_display()}\n\n"
        "Please enter the phone number to purchase this package for:"
        "\n\nAccepted formats: 07XXXXXXXX, +254XXXXXXXX, 254XXXXXXXX"
    )
    
    # Store new message for future deletion
    context.user_data['last_message'] = new_message
    
    return GETTING_PHONE

async def get_phone_number(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle the phone number input and validate."""
    user = update.effective_user
    phone_number = update.message.text.strip()
    
    # Try to delete previous message if exists
    last_message = context.user_data.get('last_message')
    if last_message:
        try:
            await last_message.delete()
        except Exception as e:
            logger.warning(f"Could not delete previous message: {e}")
    
    logger.info(f"User {user.id} entered phone number: {phone_number}")
    
    # Validate phone number
    formatted_phone = is_valid_phone_number(phone_number)
    if not formatted_phone:
        await update.message.reply_text(
            "❌ Invalid phone number format. Please enter a valid Kenyan phone number.\n\n"
            "Accepted formats: 07XXXXXXXX, +011XXXXXXXX, 254XXXXXXXX"
        )
        return GETTING_PHONE
    
    selected_package = context.user_data.get('package')
    
    if selected_package is None:
        logger.error(f"No package selected for user {user.id}")
        await update.message.reply_text("No package selected. Please try again.")
        return ConversationHandler.END
    
    # Store the validated phone number
    context.user_data['phone_number'] = formatted_phone
    
    # Show confirmation keyboard
    keyboard = [
        [InlineKeyboardButton("✅ Confirm Purchase", callback_data='confirm_purchase')],
        [InlineKeyboardButton("🔄 Change Phone Number", callback_data='change_phone')],
        [InlineKeyboardButton("❌ Cancel", callback_data='cancel_purchase')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"📋 *Purchase Summary*\n\n"
        f"Data Bundle: {selected_package.get_full_display()}\n"
        f"Size: {selected_package.size}\n"
        f"Validity: {selected_package.validity}\n"
        f"Phone Number: {formatted_phone}\n"
        f"Price: KSh {selected_package.price}\n\n"
        f"Please confirm your purchase:",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )
    
    return CONFIRMING_PURCHASE

async def handle_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle the user's confirmation of purchase."""
    query = update.callback_query
    await query.answer()
    
    user = update.effective_user
    choice = query.data
    phone_number = context.user_data.get('phone_number')
    selected_package = context.user_data.get('package')
    
    # Delete previous message if exists
    try:
        await query.message.delete()
    except Exception as e:
        logger.warning(f"Could not delete previous message: {e}")
    
    if choice == 'change_phone':
        # Ask for phone number again
        new_message = await query.message.reply_text(
            "Please enter a different phone number:"
            "\n\nAccepted formats: 07XXXXXXXX, +254XXXXXXXX, 254XXXXXXXX"
        )
        # Store new message for future deletion
        context.user_data['last_message'] = new_message
        return GETTING_PHONE
    
    # Generate a transaction reference
    reference = generate_reference()
    context.user_data['reference'] = reference
    
    logger.info(f"User {user.id} confirmed purchase for {phone_number} with reference {reference}")
    
    # Prepare transaction details
    await query.message.reply_text(
        f"✅ Purchase confirmed!\n\n"
        f"• Package: {selected_package.display_name}\n"
        f"• Phone: {phone_number}\n"
        f"• Price: KSh {selected_package.price}\n"
        f"• Reference: {reference}\n\n"
        "Processing payment...\n\n"
        "Please complete the payment on your phone when prompted."
    )
    
    # Initiate payment process
    await initiate_stk_push(
        phone_number, 
        selected_package.price, 
        reference,
        update
    )
    
    # End the conversation here
    return ConversationHandler.END

async def initiate_stk_push(phone_number: str, amount: int, reference: str, update: Update):
    """Initiate STK Push payment via PayHero API."""
    stk_push_url = "https://backend.payhero.co.ke/api/v2/payments"
    
    payload = {
        "amount": amount,
        "phone_number": phone_number,
        "channel_id": 2486,
        "provider": "m-pesa",
        "external_reference": reference,
        "callback_url": "emmkash"
    }

    headers = {"Authorization": basic_auth_token}
    
    logger.info(f"Initiating STK Push: amount={amount}, phone={phone_number}, ref={reference}")

    try:
        response = requests.post(stk_push_url, json=payload, headers=headers)

        logger.info(f"STK Push Response Status Code: {response.status_code}")
        logger.debug(f"STK Push Response Content: {response.text}")

        if response.status_code in [200, 201]:
            response_json = response.json()
            logger.info(f"STK Push Response: {response_json}")

            if response_json.get('success'):
                status = response_json.get('status')
                logger.info(f"STK Push Status: {status}")

                if status == 'SUCCESS':
                    # Get user's first name
                    user = update.effective_user
                    first_name = user.first_name or "Valued Customer"
                    
                    await update.callback_query.message.reply_text(
                        f"✅ *Payment Successful*\n\n"
                        f"Thank you {first_name} for your purchase! Your data bundle has been activated.\n\n"
                        f"Reference: `{reference}`",
                        parse_mode='Markdown'
                    )
                else:
                    await update.callback_query.message.reply_text(
                        "🔄 *Payment Processing*\n\n"
                        "Please check your phone and complete the payment.\n\n"
                        f"Reference: `{reference}`\n\n"
                        "If you need assistance, please contact our support.",
                        parse_mode='Markdown'
                    )
            else:
                await update.callback_query.message.reply_text(
                    "❌ *Payment Failed*\n\n"
                    "Sorry, we couldn't process your payment. Please try again later.\n\n"
                    "If the issue persists, please contact our support."
                )
        else:
            await update.callback_query.message.reply_text(
                "❌ *Error Processing Payment*\n\n"
                "An error occurred while processing your payment. Please try again later.\n\n"
                "If the issue persists, please contact our support."
            )

    except Exception as e:
        logger.error(f"Error initiating STK push: {e}")
        await update.callback_query.message.reply_text(
            "❌ *System Error*\n\n"
            "A system error occurred while processing your payment.\n\n"
            "Please try again later or contact our support for assistance."
        )
    
    return False

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a message when the command /help is issued."""
    user = update.effective_user
    register_user(user)
    
    help_text = (
        "*Welcome to Data Bundles Bot*\n\n"
        "This bot helps you purchase data bundles quickly and easily.\n\n"
        "*Available Commands:*\n"
        "/start - Start the bot\n"
        "/bundles - View available data bundles\n"
        "/help - Show this help message\n"
        "/restart - Reset the bot if you get stuck\n"
        "/about - Information about this service\n\n"
        "To purchase a data bundle, follow these steps:\n"
        "1. Choose a data bundle from the menu\n"
        "2. Enter the phone number\n"
        "3. Confirm your purchase\n"
        "4. Complete the payment via M-PESA\n\n"
        "*Note:* Conversations will automatically reset after 3 minutes of inactivity. You can also use /restart at any time to start over.\n\n"
        "If you need assistance, please contact our support."
    )
    
    await update.message.reply_text(help_text, parse_mode='Markdown')

async def about_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send information about the service."""
    user = update.effective_user
    register_user(user)
    
    about_text = (
        f"*{APP_NAME} v{APP_VERSION}*\n\n"
        "A convenient way to purchase mobile data bundles directly through Telegram.\n\n"
        "Powered by Bingwamta Technologies\n"
        "© 2023 All Rights Reserved\n\n"
        "For support, please contact us at support@emmkashtechnologies.xyz"
    )
    
    await update.message.reply_text(about_text, parse_mode='Markdown')

async def cancel_purchase(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle the cancellation of a purchase."""
    query = update.callback_query
    await query.answer()
    
    user = update.effective_user
    logger.info(f"User {user.id} cancelled the purchase")
    
    await query.message.reply_text(
        f"You have cancelled your purchase. If you need assistance, please contact our support at {SUPPORT_CONTACT} or call 0707071631.\n\n"
        "You can start a new purchase anytime by sending /bundles."
    )
    return ConversationHandler.END

async def handle_support_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle the support button in the bundles menu."""
    query = update.callback_query
    await query.answer()
    
    await query.message.reply_text(
        "📞 *Customer Support*\n\n"
        f"If you need assistance, please contact us through:\n\n"
        f"• Telegram: {SUPPORT_CONTACT}\n"
        f"• Phone: 0707071631\n\n"
        "We're here to help you with any questions or issues!",
        parse_mode='Markdown'
    )
    
    # Return to the bundle selection
    return CHOOSING_PACKAGE

# ===== Admin Command Handlers =====

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle the /admin command"""
    user = update.effective_user
    
    if not is_admin(user.id):
        logger.warning(f"Non-admin user {user.id} tried to access admin panel")
        await update.message.reply_text("You don't have permission to access this command.")
        return ConversationHandler.END
    
    logger.info(f"Admin {user.id} accessed admin panel")
    
    keyboard = [
        [InlineKeyboardButton("📢 Send Broadcast Message", callback_data='admin_broadcast')],
        [InlineKeyboardButton("📊 View Stats", callback_data='admin_stats')],
        [InlineKeyboardButton("❌ Exit Admin Panel", callback_data='admin_exit')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "🔐 *Admin Panel*\n\n"
        "Please select an option:",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )
    
    return ADMIN_COMMAND

async def admin_handle_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle admin panel choices"""
    query = update.callback_query
    await query.answer()
    
    user = update.effective_user
    choice = query.data
    
    if choice == 'admin_exit':
        await query.message.reply_text("Admin panel closed.")
        return ConversationHandler.END
    
    elif choice == 'admin_broadcast':
        await query.message.reply_text(
            "📢 *Send Broadcast Message*\n\n"
            "Please enter the message you want to send to all users.\n"
            "This will be sent to everyone who has used the bot.\n\n"
            "Type /cancel to cancel."
        )
        return ADMIN_BROADCAST_MESSAGE
    
    elif choice == 'admin_stats':
        # Get user statistics
        data = load_user_data()
        user_count = len(data["users"])
        
        stats_text = (
            "📊 *Bot Statistics*\n\n"
            f"Total Users: {user_count}\n"
        )
        
        await query.message.reply_text(stats_text, parse_mode='Markdown')
        return ADMIN_COMMAND
    
    return ADMIN_COMMAND

async def admin_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle broadcast message input"""
    user = update.effective_user
    message_text = update.message.text
    
    if message_text.lower() == '/cancel':
        await update.message.reply_text("Broadcast cancelled.")
        return ConversationHandler.END
    
    logger.info(f"Admin {user.id} is sending broadcast message")
    
    # Get all users
    data = load_user_data()
    users = data["users"]
    
    if not users:
        await update.message.reply_text("No users found in the database.")
        return ConversationHandler.END
    
    # Prepare broadcast message
    broadcast_text = (
        "📢 *Broadcast Message*\n\n"
        f"{message_text}"
    )
    
    # Send broadcast to all users
    sent_count = 0
    failed_count = 0
    
    # Show sending progress
    status_message = await update.message.reply_text(
        "🔄 Sending broadcast message...\n\n"
        "Please wait, this may take some time depending on the number of users."
    )
    
    for user_data in users:
        try:
            user_id = int(user_data["id"])
            await context.bot.send_message(
                chat_id=user_id,
                text=broadcast_text,
                parse_mode='Markdown'
            )
            sent_count += 1
            
            # Update progress every 10 users
            if sent_count % 10 == 0:
                await status_message.edit_text(
                    f"🔄 Sending broadcast message...\n\n"
                    f"Progress: {sent_count}/{len(users)} messages sent."
                )
                
        except Exception as e:
            logger.error(f"Failed to send broadcast to user {user_id}: {e}")
            failed_count += 1
    
    # Send summary
    await status_message.edit_text(
        "✅ *Broadcast Complete*\n\n"
        f"Messages sent: {sent_count}\n"
        f"Failed: {failed_count}"
    )
    
    await update.message.reply_text(
        "Broadcast completed. What would you like to do next?",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📢 Send Another Broadcast", callback_data='admin_broadcast')],
            [InlineKeyboardButton("❌ Exit Admin Panel", callback_data='admin_exit')]
        ])
    )
    
    return ADMIN_COMMAND

async def admin_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel the admin conversation."""
    await update.message.reply_text("Admin operation cancelled.")
    return ConversationHandler.END

async def timeout_end(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle conversation timeout."""
    # Note: In this version of python-telegram-bot, there's no direct callback for timeouts
    # However, we can use this function to handle the ConversationHandler.TIMEOUT state
    # which will be a message handler for the TIMEOUT state (not used directly in this implementation)
    
    logger.info(f"Conversation timed out")
    
    # Clear user data
    context.user_data.clear()
    
    # Send a message to the user about the timeout (can't be used directly with the current setup)
    # This function is kept for reference and future compatibility
    
    return ConversationHandler.END

async def restart_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Restart the bot and clear any ongoing conversation."""
    user = update.effective_user
    
    # Clear user data
    context.user_data.clear()
    
    logger.info(f"User {user.id} restarted the bot manually")
    
    await update.message.reply_text(
        "🔄 Bot has been restarted. Your previous session has been cleared.\n\n"
        "You can now start a new purchase."
    )
    
    # Show bundles menu directly
    return await show_bundles(update, context)

# ===== Main Function =====

def main() -> None:
    """Start the Telegram bot."""
    application = ApplicationBuilder().token(BOT_TOKEN).build()

    # Define regular handlers
    start_handler = CommandHandler('start', start)
    restart_handler = CommandHandler('restart', restart_command)
    bundles_handler = CommandHandler('bundles', show_bundles)
    help_handler = CommandHandler('help', help_command)
    about_handler = CommandHandler('about', about_command)
    support_handler = CommandHandler('support', contact_support)

    # Callback query handlers for the conversation
    choose_package_handler = CallbackQueryHandler(
        choose_package, 
        pattern=r'^(data_\d+|section_header|support|bingwa_deals|normal_deals|back_to_categories)$'
    )
    confirm_handler = CallbackQueryHandler(
        handle_confirmation,
        pattern='^(confirm_purchase|change_phone)$'
    )
    cancel_handler = CallbackQueryHandler(cancel_purchase, pattern='^cancel_purchase$')
    
    # Phone number handler - captures text input
    phone_handler = MessageHandler(filters.TEXT & ~filters.COMMAND, get_phone_number)

    # Define main ConversationHandler with conversation timeout
    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler('start', start), 
            CommandHandler('bundles', show_bundles),
            CommandHandler('restart', restart_command)
        ],
        states={
            CHOOSING_PACKAGE: [choose_package_handler, cancel_handler],
            GETTING_PHONE: [phone_handler, cancel_handler],
            CONFIRMING_PURCHASE: [confirm_handler, cancel_handler],
        },
        fallbacks=[cancel_handler, CommandHandler('restart', restart_command)],
        conversation_timeout=180,  # Timeout after 3 minutes (180 seconds)
        name="main_conversation",
        persistent=False,
        per_message=False,
        per_chat=True
    )
    
    # Define admin ConversationHandler
    admin_handler = ConversationHandler(
        entry_points=[CommandHandler('admin', admin_command)],
        states={
            ADMIN_COMMAND: [
                CallbackQueryHandler(admin_handle_choice, pattern='^admin_')
            ],
            ADMIN_BROADCAST_MESSAGE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_broadcast),
                CommandHandler('cancel', admin_cancel)
            ],
        },
        fallbacks=[CommandHandler('cancel', admin_cancel), CommandHandler('restart', restart_command)]
    )

    # Add handlers to the application
    application.add_handler(conv_handler)
    application.add_handler(admin_handler)
    application.add_handler(help_handler)
    application.add_handler(about_handler)
    application.add_handler(support_handler)
    application.add_handler(restart_handler)  # Add restart command outside conversation handlers too

    logger.info(f"Starting {APP_NAME} v{APP_VERSION}...")
    application.run_polling()

if __name__ == '__main__':
    main() 
