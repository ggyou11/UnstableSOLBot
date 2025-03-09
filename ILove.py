import websocket
import json
import os
import requests
from dotenv import load_dotenv
from rugcheck import rugcheck  # Import the rugcheck function

# Load environment variables
load_dotenv()

api_helius_key = os.getenv("api_helius_key")
RAYDIUM_PROGRAM_ID = os.getenv("RAYDIUM_PROGRAM_ID")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_SOGE_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("IDG_CHAT")

# New endpoint for parsing transactions
HELIUS_HTTPS_URI_TX = f"https://api.helius.xyz/v0/transactions/?api-key={api_helius_key}"
wss_url = f"wss://mainnet.helius-rpc.com/?api-key={api_helius_key}"

def send_telegram_message(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message
    }
    response = requests.post(url, json=payload)
    return response.ok

def fetch_transaction_details(signature):
    # Using the new Helius HTTPS endpoint and payload format
    payload = {
        "transactions": [signature]
    }
    try:
        response = requests.post(HELIUS_HTTPS_URI_TX, json=payload)
        data = response.json()
        if isinstance(data, list) and data:
            print("parsed transaction: ", data)
            return data[0]
        else:
            return None
    except Exception as e:
        print(f"Error fetching transaction: {e}")
        return None

def extract_token_address(transaction_data):
    """
    Extract the new token's mint address by iterating over tokenTransfers.
    This function ignores the wrapped SOL mint (So11111111111111111111111111111111111111112)
    and selects transfers that have a non-empty 'fromTokenAccount' (typically indicating
    the actual token transfer rather than pool liquidity token minting).
    """
    try:
        # For debugging: print the transaction data structure
        print("Transaction data:", json.dumps(transaction_data, indent=2))
        token_transfers = transaction_data.get("tokenTransfers", [])
        for token in token_transfers:
            mint = token.get("mint")
            # Exclude wrapped SOL and tokens without a proper fromTokenAccount
            if mint and mint != "So11111111111111111111111111111111111111112" and token.get("fromTokenAccount"):
                return mint
        return None
    except KeyError:
        return None

def connect_websocket():
    ws = websocket.create_connection(wss_url)
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "logsSubscribe",
        "params": [
            {
                "mentions": [RAYDIUM_PROGRAM_ID]
            }
        ]
    }
    ws.send(json.dumps(request))
    print("WebSocket connection established and request sent.")
    return ws

def perform_rugcheck(token_mint):
    rc = rugcheck(token_mint)  # Perform rug check

    # Retrieve RugCheck result details
    response_message = f"RugCheck Results for {token_mint}:\n"
    response_message += f"Token Risk Score: {rc.score}\n"

    # Calculate the total amount across all top holders
    total_amount = sum(holder['amount'] for holder in rc.topHolders)

    # Sort top holders by amount in descending order and limit to top 10
    top_holders = sorted(rc.topHolders, key=lambda x: x['amount'], reverse=True)[:10]

    # Calculate percentage for each top holder and sum them
    total_percentage = 0
    top_holder_percentages = []

    for holder in top_holders:
        # Calculate percentage for each holder
        percentage = (holder['amount'] / total_amount) * 100
        top_holder_percentages.append(f"{percentage:.2f}%")
        total_percentage += percentage

    # Format the response message
    response_message += f"Top 10 Holders (Percentage of Total Supply):\n"
    response_message += "\n".join(top_holder_percentages)

    # Show the sum of percentages for the top 10 holders
    response_message += f"\n\nTotal of Top 10 Holders' Percentages: {total_percentage:.2f}%"

    # Add liquidity and creator info
    response_message += f"\nLiquidity: {rc.totalMarketLiquidity}\n"
    response_message += f"Creator: {rc.creator if rc.creator else 'Unknown'}\n"

    # Add disclaimer message
    response_message += "\n\n⚠️ This is not financial advice. Please conduct your own research (DOYR) before making any investment decisions."

    return response_message

# Establish initial WebSocket connection
ws = connect_websocket()

# Auto notification on bot start
if send_telegram_message("Bot started and monitoring liquidity pool creations."):
    print("Startup notification sent to Telegram.")
else:
    print("Failed to send startup notification to Telegram.")

while True:
    try:
        message = ws.recv()
        data = json.loads(message)
        if "method" in data and data["method"] == "logsNotification":
            logs = data["params"]["result"]["value"]["logs"]
            signature = data["params"]["result"]["value"]["signature"]
            # Change the log search condition as needed
            if any("Program log: initialize2: InitializeInstruction2" in log for log in logs):
                print(f"New liquidity pool detected. Signature: {signature}")
                # Pause WebSocket connection to process transaction
                ws.close()
                print("WebSocket stopped to handle transaction")
                print("WebSocket paused for transaction processing")

                # Fetch transaction details using the new endpoint
                tx_details = fetch_transaction_details(signature)
                if not tx_details:
                    print("Failed to fetch transaction details.")
                else:
                    token_mint = extract_token_address(tx_details)
                    if token_mint:
                        print(f"Token mint address: {token_mint}")
                        # Perform rug check and format the report
                        rugcheck_report = perform_rugcheck(token_mint)
                        telegram_msg = f"New token detected on Solana:\n{rugcheck_report}"
                        if send_telegram_message(telegram_msg):
                            print("Telegram notification sent.")
                        else:
                            print("Failed to send Telegram notification.")
                    else:
                        print("Token mint not found in transaction.")

                # Resume the WebSocket connection
                ws = connect_websocket()
    except websocket.WebSocketException as e:
        print(f"WebSocket error: {e}")
        break
    except KeyboardInterrupt:
        print("Shutdown requested...")
        ws.close()
        print("WebSocket connection closed.")
        break
    except Exception as e:
        print(f"Unexpected error: {e}")
