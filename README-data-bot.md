# Data Bundles Bot

A professional Telegram bot for purchasing mobile data bundles with M-PESA integration.

## Features

- **Easy Data Bundle Purchase**: Users can quickly browse and purchase data bundles
- **Organized Bundle Categories**: Bundles grouped by hourly, daily, weekly, and monthly validity periods
- **Secure Payment Integration**: Direct M-PESA payment integration with PayHero
- **Phone Number Validation**: Ensures correctly formatted Kenyan phone numbers
- **Purchase Confirmation**: Clear purchase summary before payment
- **Admin Broadcast System**: Send announcements to all bot users
- **Usage Statistics**: Track number of users and interactions

## Setup Instructions

### Prerequisites

- Python 3.7 or higher
- A Telegram Bot Token (from BotFather)
- PayHero API credentials
- M-PESA integration via PayHero

### Installation

1. Clone this repository:
   ```bash
   git clone [repository-url]
   cd [repository-directory]
   ```

2. Install the required dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Create a `.env` file from the example:
   ```bash
   cp .env-example .env
   ```

4. Edit the `.env` file with your credentials:
   - BOT_TOKEN: Your Telegram bot token
   - API_USERNAME: Your PayHero API username
   - API_PASSWORD: Your PayHero API password  
   - ADMIN_USER_IDS: Comma-separated list of Telegram user IDs who will have admin access

### Running the Bot

Start the bot using:
```bash
python data_deals_bot.py
```

For production deployment, consider using a process manager like systemd, supervisor, or PM2.

## Usage

### User Commands

- `/start` - Start the bot and see the welcome message
- `/bundles` - View available data packages
- `/help` - Show help information
- `/about` - Show information about the service

### Admin Commands

- `/admin` - Access the admin panel (only available to configured admin users)

### Admin Panel Features

1. **Send Broadcast Message**: Send notifications to all users who have interacted with the bot
2. **View Stats**: See usage statistics and total user count

## Customization

You can customize the available data bundles by editing the `data_packages` dictionary in `data_deals_bot.py`.

## Admin Features

### Broadcast Messages

Admins can send broadcast messages to all users who have used the bot. This is useful for:

- Announcing special offers or promotions
- Informing users about service maintenance
- Communicating important updates

### User Management

The bot automatically keeps track of all users who interact with it. User data is stored in `user_data.json`.

## Troubleshooting

- Check the logs in the `logs` directory for detailed operation information
- Ensure your PayHero API credentials are correct
- Verify that you have set the admin user IDs correctly in the `.env` file

## Security Notes

- Keep your `.env` file secure and never commit it to version control
- Admin users can send messages to all users, so be careful who you grant admin access to

## License

[Your License Information]

## Support

For support, please contact [Your Support Information] 