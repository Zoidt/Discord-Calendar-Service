import discord
from os import getenv
from dotenv import load_dotenv
import json
import asyncio # Not strictly needed for this version, but good for future async operations
import aiohttp # For making asynchronous HTTP requests
import google.generativeai as genai
from datetime import datetime

# Load environment variables from .env file
load_dotenv()

DISCORD_TOKEN = getenv('DISCORD_TOKEN')
GEMINI_API_KEY = getenv('GEMINI_API_KEY')
MAKE_WEBHOOK_URL = getenv('MAKE_WEBHOOK_URL')

# --- CONFIGURATION ---
# !! IMPORTANT: Change this to the name of the channel your bot should listen to !!
TARGET_CHANNEL_NAME = "calendar-agent"
# Consider using a more specific model if needed, like 'gemini-1.5-pro-latest' for complex tasks
GEMINI_MODEL_NAME = 'gemini-2.0-flash' # Good balance of speed and capability

# Configure Gemini client
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel(GEMINI_MODEL_NAME)
    print(f"Gemini model '{GEMINI_MODEL_NAME}' initialized.")
else:
    model = None
    print(
        "GEMINI_API_KEY not found in .env file. Gemini functionality will be disabled."
    )

intents = discord.Intents.default()
intents.message_content = True  # You already have this, which is correct!

client = discord.Client(intents=intents)


@client.event
async def on_ready():
    print(f'Logged in as {client.user}')
    print(
        f"Listening for messages in channel: '{TARGET_CHANNEL_NAME}'"
    )
    if not model:
        print(
            "Warning: Gemini API key not configured. Calendar event parsing will not work."
        )
    if not MAKE_WEBHOOK_URL:
        print(
            "Warning: MAKE_WEBHOOK_URL not configured. Calendar events will not be sent."
        )


@client.event
async def on_message(message):
    if message.author == client.user:
        return  # Ignore messages sent by the bot itself

    # Check if the message is in the designated channel and if Gemini is configured
    if message.channel.name == TARGET_CHANNEL_NAME:
        if not model:
            print(
                "Gemini model not initialized. Skipping message processing."
            )
            # await message.channel.send("Sorry, I can't process calendar events right now (Gemini API not configured).")
            return
        if not MAKE_WEBHOOK_URL:
            print(
                "Make.com webhook URL not configured. Skipping message processing."
            )
            # await message.channel.send("Sorry, I can't process calendar events right now (Webhook URL not configured).")
            return

        message_content = message.content
        print(
            f"Received message in '{TARGET_CHANNEL_NAME}': \"{message_content}\""
        )

        await message.add_reaction('🤔')  # Thinking emoji

        try:
            # 1. Construct the prompt for Gemini
            # The date helps Gemini resolve relative dates like "today" or "tomorrow"
            current_date_str = datetime.now().strftime('%Y-%m-%d')
            prompt = f"""
            You are an intelligent assistant that extracts calendar event details from text.
            The output MUST be a valid JSON object.
            The JSON object must have the following keys:
            - "title": (string) The title or summary of the event.
            - "description": (string) A more detailed description of the event.
            - "start_datetime": (string) The start date and time in ISO 8601 format (YYYY-MM-DDTHH:MM:SS). in EDT timezone.
            - "end_datetime": (string) The end date and time in ISO 8601 format (YYYY-MM-DDTHH:MM:SS). in EDT timezone.
            - "duration": (string, optional) The duration of the event. format (HH:mm)
            - "location": (string, optional) The location of the event.

            Guidelines:
            - If a value for an optional field (description, location) is not present, use null or omit the key.
            - If only a date is provided for the start, assume it's an all-day event for that date. For example, "event on 2025-12-25" means start_datetime: "2025-12-25T00:00:00" and end_datetime: "2025-12-25T23:59:59".
            - If only a start time is provided without a specific date, try to infer the date based on context like "today", "tomorrow". The current date is {current_date_str}.
            - If only a start datetime is provided, assume the event is 1 hour long for the end_datetime.
            - If the text does not seem to describe a calendar event, return an empty JSON object {{}}.

            NOTES: ENSURE ALL TIMEZONES ARE EDT.

            
            Parse the following text:
            "{message_content}"

            JSON Output:
            """

            # 2. Call Gemini API (asynchronously)
            # Use generate_content_async for non-blocking call in async discord.py function
            response = await model.generate_content_async(prompt)
            
            # Clean up the thinking reaction
            try:
                await message.remove_reaction('🤔', client.user)
            except main.NotFound:
                pass # Reaction might have been removed by something else or already gone

            gemini_response_text = response.text
            print(f"Gemini raw response: {gemini_response_text}")

            # 3. Extract JSON from Gemini's response
            # Gemini might wrap its JSON output in markdown (```json ... ```) or add other text.
            json_str = ""
            if "```json" in gemini_response_text:
                json_str = gemini_response_text.split("```json")[1].split("```")[0].strip()
            elif "```" in gemini_response_text: # If only ``` ```
                json_str = gemini_response_text.split("```")[1].split("```")[0].strip()
            else:
                # Try to find JSON-like structure (heuristic)
                if gemini_response_text.strip().startswith("{") and gemini_response_text.strip().endswith("}"):
                    json_str = gemini_response_text.strip()
                else: # Could not reliably find JSON
                    raise json.JSONDecodeError("No clear JSON block found in Gemini response.", gemini_response_text, 0)


            if not json_str: # If after attempting to extract, json_str is empty
                 raise json.JSONDecodeError("Extracted JSON string is empty.", gemini_response_text, 0)

            event_details = json.loads(json_str)
            print(f"Parsed event details: {event_details}")

            # If Gemini returns an empty object, it means it didn't find an event
            if not event_details:
                print("Gemini parsed no event details. Not sending to webhook.")
                await message.add_reaction('🤷') # Shrug for no event found
                # await message.channel.send("I didn't find any event details in that message.")
                return

            # 4. Make the webhook request to Make.com using aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.post(MAKE_WEBHOOK_URL, json=event_details) as webhook_response:
                    if webhook_response.status >= 200 and webhook_response.status < 300:
                        print(f"Webhook request successful: {webhook_response.status}")
                        await message.add_reaction('✅')  # Success
                    else:
                        error_text = await webhook_response.text()
                        print(f"Webhook request failed: {webhook_response.status} - {error_text}")
                        await message.add_reaction('⚠️')  # Webhook error
                        await message.channel.send(f"Error sending to calendar: {webhook_response.status} - {error_text[:1500]}")

        except json.JSONDecodeError as e:
            print(f"Error decoding JSON from Gemini: {e}")
            if 'gemini_response_text' in locals():
                 print(f"Gemini raw response was: {gemini_response_text}")
                 await message.channel.send(f"Sorry, I couldn't understand the event details. Gemini's response: ```\n{gemini_response_text[:1500]}\n```")
            else:
                 await message.channel.send("Sorry, I couldn't understand the event details (no response from Gemini).")
            await message.add_reaction('❌') # Error parsing
        except genai.types.generation_types.BlockedPromptException as e:
            print(f"Gemini API call failed due to blocked prompt: {e}")
            try:
                await message.remove_reaction('🤔', client.user)
            except main.NotFound:
                pass
            await message.add_reaction('🚫') # Blocked by safety
            await message.channel.send("Sorry, your request was blocked by content safety filters.")
        except Exception as e:
            print(f"An unexpected error occurred: {e}")
            import traceback
            traceback.print_exc() # Log the full error
            try:
                await message.remove_reaction('🤔', client.user)
            except main.NotFound:
                pass
            await message.add_reaction('❌') # General error
            await message.channel.send(f"An unexpected error occurred: {str(e)[:1000]}")


def main():
    if not DISCORD_TOKEN:
        print("DISCORD_TOKEN not found in .env file. Bot cannot start.")
        return
    client.run(DISCORD_TOKEN)

if __name__ == '__main__':
    main()
