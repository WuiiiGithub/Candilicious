from pymongo import MongoClient
from datetime import datetime
import config

# Connection Setup
client = MongoClient(config.dbURI)
db = client[config.dbName]
selfCollection = db['Self']
configCollection = db['config']

# Data Insertion
selfCollection.insert_many(
    [
        {
            "section": "tos",
            "content": """Welcome to Candilicious Bot! By using this bot, you agree to the following terms:
1. You shall not engage in any activities that disrupt the experience of others.
2. Any misuse, exploitation, or unauthorized modification of the bot is prohibited.
3. The bot developers reserve the right to modify or terminate services at any time.
4. Your interactions with the bot may be logged for moderation and safety purposes.

By continuing to use this bot, you acknowledge that you have read and agreed to these terms.""",
            "updated": datetime.fromisoformat("2025-03-29T22:26:36.486+00:00")
        },
        {
            "section": "privacy",
            "content": """Candilicious Bot respects your privacy. Here’s how we handle your data:
- We do not collect or store any personally identifiable information.
- All user interactions with the bot are only stored temporarily and are deleted after use.
- The bot does not share or sell any data to third parties.
- Certain commands may log minimal metadata for debugging and service improvement.

Your data privacy is our top priority.""",
            "updated": datetime.fromisoformat("2025-03-29T22:26:36.486+00:00")
        },
        {
            "section": "about",
            "content": """Candilicious Bot is designed to enhance your study experience with engaging features:
- Provides study tracking tools to monitor session durations.
- Includes a community leaderboard to encourage productivity.
- Offers automated moderation and inactivity monitoring.
- Supports flexible decision-making with census-based user votes.""",
            "updated": datetime.fromisoformat("2025-03-29T22:26:36.486+00:00")
        },
        {
            "section": "updates",
            "version": "1.2.0",
            "content": """I am rolling out new features for the bot. Its the following:
- Gold Session 
- Silver Session
So... In future... you have two VCs
1. Gold Mine VC -> You get virtual gold coins
2. Silver Mine VC -> You get virtual silver coins

You can see the following images for knowing how it works (tentative)...
Read More on: https://discord.com/channels/1491471841716605062/1497104859541798983/1499117347871522998""",
            "updated": datetime.now()
        }
    ]
)

configCollection.insert_many(
    [
        {
            "gifs": [
                "https://media.tenor.com/bdrxY_1p2ywAAAAM/you-sound-like-minimum-wage-minimum-wage.gif",
                "https://media1.tenor.com/m/Uujd37tXCDMAAAAC/emotional-dammage-jesus.gif",
                "https://media1.tenor.com/m/a7UOrCy2VSsAAAAC/steven-he-timmy.gif",
                "https://media1.tenor.com/m/9PoIZUx13ogAAAAC/steven-he-what-the-hell.gif",
                "https://media1.tenor.com/m/rzUK2-P3fGoAAAAC/i-will-send-you-to-jesus-steven-he.gif",
                "https://media1.tenor.com/m/gB533zDnLj8AAAAC/steven-he-low-iq.gif",
                "https://media.tenor.com/1J364RWIOS0AAAAM/failure-steven-he.gif",
                "https://media.tenor.com/H6Mn8UKr8fMAAAAM/steven-he-taking-glasses-off.gif",
                "https://media.tenor.com/EotvIq9jCWYAAAAM/steven-he-stop-crying.gif",
                "https://media.tenor.com/y3eF3H4NoJ0AAAAM/reupload.gif",
                "https://media.tenor.com/b74aUfxUH48AAAAM/steven-he-timmy.gif",
                "https://media.tenor.com/_8M7GmHA2ncAAAAM/steven-he-nobody.gif",
                "https://media.tenor.com/3ckuBnwYX8YAAAAM/steven-he-timmy.gif",
                "https://media.tenor.com/1y_UVzY1s38AAAAM/steven-he-what.gif",
                "https://media.tenor.com/MJNxLiHKLOQAAAAM/steven-he-listen.gif",
                "https://media.tenor.com/BTHc82DNltcAAAAM/steven-he-masters.gif"
            ],
            "updated": datetime.now()
        },
        {
            "texts": [
                "Timmy started a multi-billion dollar startup during his 5-minute lunch break. You are still on page 1. STUDY!",
                "Failure is not an option. It is a career choice you are currently making. Back to work!",
                "I can smell the lack of productivity from here. It smells like 'Minimum Wage'.",
                "You want to eat? Only those who understand Quantum Physics get rice. Go study!",
                "Your cousin became a doctor at age 12. You are 20 and still 'finding yourself'. Find your textbook!",
                "I will send you to Jesus if you don't finish that practice exam in the next 10 minutes!",
                "If you spend as much time studying as you do breathing, you might actually be a success.",
                "Is that a phone in your hand? Unless you are calling a tutor, put it down before I use it as a coaster!",
                "Studying is the only way forward. Everything else leads to the street corner. GO!",
                "Emotional damage? I'll give you real damage if you don't get an A+!",
                "Why are you blinking? Every blink is a second you aren't memorizing the periodic table!",
                "Stop crying! Tears don't solve for X. Calculus solves for X!",
                "If I see you playing a game, the only game you'll be playing is 'Find a New Place to Live'.",
                "You think you're tired? I used to walk 20 miles uphill both ways on one leg to get to school!",
                "Your IQ is currently lower than the room temperature. Increase it now!",
                "Why you get 98%? Where is the other 2%? Did it evaporate? Go find it!",
                "If you have time to lean, you have time to learn. Get back to the books!",
                "A 'B' is just an 'A' for failures. Do you want to be a failure?",
                "I don't care if the house is on fire, finish the chapter before you leave!",
                "Timmy is a neurosurgeon and a concert pianist. You are a professional couch potato. STUDY!",
                "When I was your age, I was 10 years older than you. Stop being lazy!",
                "Don't talk to me until you have a PhD. Actually, make it two PhDs.",
                "You want a break? The only break you get is a mental breakdown if you fail!",
                "Go back to studying right now! Failure is a disease and you are looking very sick.",
                "I can hear your brain cells dying from inactivity. Open the book!",
                "Sleep is for people who have already succeeded. You have done nothing today.",
                "If you don't study, I will sell your gaming PC and buy a dictionary for your replacement.",
                "Are you enjoying that YouTube video? I hope it teaches you how to survive on the street!",
                "You are a disappointment to 5,000 years of ancestors. Go study and fix it!",
                "History is being made while you are being a 'Failure'. Go read about it!",
                "Why you still here? The textbook doesn't read itself!",
                "I don't need a GPS to find where your potential went—it's in the trash. Get it out!",
                "You want to be a YouTuber? I will YouTube you into a different dimension! STUDY!",
                "Your math skills are so bad, you can't even count how many times you've disappointed me.",
                "The only 'extra credit' you get is the extra chores you'll do when you fail!",
                "If Timmy can perform heart surgery with a toothpick, you can finish your homework!",
                "Is that a smile? Did you get 100%? No? Then wipe it off and read!",
                "You look like you're thinking. Don't think. Memorize!",
                "Education is the only key to success. Right now, you are locked outside.",
                "I am not angry, I am just wondering why I raised a failure.",
                "The neighbors' son just discovered a new element. You haven't even discovered the 'On' switch for your brain.",
                "You think you're smart? Smart people don't need to be told 50 times to study!",
                "I will trade you for a sack of rice if you don't pass this class.",
                "Go study or I will tell everyone you still sleep with a nightlight!",
                "The textbook is 500 pages. You have 5 minutes. Start flipping!",
                "You are the 'Minimum Wage' version of your brother. Level up!",
                "If you fail this test, don't come home. Go live with the pandas at the zoo.",
                "I didn't move to this country so you could watch TikTok. Pick up the pen!",
                "Your brain is like a Ferrari with no gas. Go to the library and fill it up!",
                "Success is 100% studying and 0% of whatever you are doing right now!"
            ],
            "updated": datetime.now()
        }
    ]
)
print("Candilicious data successfully inserted.")