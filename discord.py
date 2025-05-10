import discord
from os import getenv
from dotenv import load_dotenv

ENV = getenv('DISCORD_TOKEN')

intents = discord.Intents.default()
intents.message_content = True  # Make sure to enable message content intent

client = discord.Client(intents=intents)

@client.event
async def on_ready():
    print(f'Logged in as {client.user}')

@client.event
async def on_message(message):
    if message.author == client.user:
        return  # Ignore messages sent by the bot itself

    if message.channel.name == 'general' and message.content.lower() == 'hello':
        await message.add_reaction('👍')

def main():
    client.run('YOUR_BOT_TOKEN')

if __name__ == '__main__':
    main()