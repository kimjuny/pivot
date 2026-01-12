# Environment Setup

## Quick Start

1. Copy the example environment file:
   ```bash
   cp server/.env.example server/.env
   ```

2. Edit `server/.env` and add your Doubao API key:
   ```
   DOUBAO_SEED_API_KEY=your_actual_api_key_here
   ```

3. Start the application:
   ```bash
   ./start.sh --dev
   ```

## Getting API Key

To use this application, you need a Doubao API key. Visit the Doubao platform to obtain your API key.

## Environment Variables

- `DATABASE_URL`: Database connection URL (default: SQLite for development, PostgreSQL for production)
- `DOUBAO_SEED_API_KEY`: Your Doubao API key for the LLM

## Troubleshooting

If you see an error like "DOUBAO_SEED_API_KEY environment variable not set", make sure:
1. You have created a `.env` file in the `server/` directory
2. You have added your API key to the `.env` file
3. The API key is not empty or set to "your_api_key_here"
