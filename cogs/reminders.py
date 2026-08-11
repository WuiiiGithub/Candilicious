import discord, traceback, os, config, random, re, asyncio
from dotenv import load_dotenv
from discord.ext import commands, tasks
from discord import app_commands, ui
from library.logging import *
from library import is_muted, is_on_holiday, db
from library.gifs import fix_gif_url, resolve_gif_url, repair_reminder_gifs, is_usable_image_url
from datetime import datetime, timezone, timedelta
from typing import Optional

filename = __name__.title()
cogLog = CogLogger(filename=filename)

load_dotenv()

serverCollection = db["servers"]
configCollection = db["config"]
userCollection = db["users"]
schedulerCollection = db["schedulers"]

def _get_last_study_date(user_doc: dict) -> Optional[str]:
    """Return the last study day as 'YYYY-MM-DD'.

    Prefers the single `last_study_time` datetime field (the date is already
    contained in it). Falls back to the legacy `last_study_date` field so
    documents written before the schema consolidation keep working.
    """
    if not user_doc:
        return None

    last_time = user_doc.get("last_study_time")
    if last_time:
        if isinstance(last_time, str):
            try:
                return datetime.fromisoformat(last_time).date().isoformat()
            except (ValueError, TypeError):
                pass
        elif hasattr(last_time, "date"):
            return last_time.date().isoformat()

    last_date = user_doc.get("last_study_date")
    if last_date:
        if isinstance(last_date, str):
            return last_date
        return last_date.date().isoformat() if hasattr(last_date, "date") else str(last_date)
    return None


STUDY_CALL_STATEMENTS = [
    # --- MOTIVATIONAL (30) ---
    "The secret of getting ahead is getting started. Let's study! 📚",
    "Success is the sum of small efforts repeated day in and day out. Start now!",
    "Don't watch the clock; do what it does. Keep going. ⏰",
    "Your future is created by what you do today, not tomorrow.",
    "Study hard, for the well is deep, and our brains are shallow. 💡",
    "The beautiful thing about learning is nobody can take it away from you.",
    "Education is the passport to the future. Go claim yours! 🎓",
    "A little progress each day adds up to big results. Let's get started!",
    "Dream big. Start small. Act now. Study time! 🚀",
    "Discipline is choosing between what you want now and what you want most.",
    "The expert in anything was once a beginner. Keep studying! 🌱",
    "Don't stop when you're tired. Stop when you're done.",
    "Study while others are sleeping. Work while others are loafing.",
    "The only way to do great work is to love what you study.",
    "Push yourself, because no one else is going to do it for you.",
    "Great things never come from comfort zones. Time to study! 📖",
    "Don't wish for it. Work for it. Study session awaits!",
    "Success isn't always about greatness. It's about consistency.",
    "The harder you work for something, the greater you'll feel when you achieve it.",
    "Don't count the days. Make the days count. Study now! ⭐",
    "Your only limit is your mind. Break through it!",
    "Every expert was once a student. Your time is now! 🎯",
    "Invest in your brain. It's the only one you'll ever have.",
    "Knowledge is power. Power up with studying! 💪",
    "The journey of a thousand miles begins with a single step — or page.",
    "Don't wait for opportunity. Create it through studying!",
    "Stars can't shine without darkness. Study through the struggle! ✨",
    "Be stronger than your excuses. Study time!",
    "What you do today can improve all your tomorrows. Start studying!",
    "Small daily improvements lead to stunning results over time.",

    # --- EMOTIONAL / HEARTFELT (25) ---
    "I know you're tired, but imagine how proud you'll feel when you're done. 💙",
    "Sometimes the strongest people are the ones who smile through the pain and study.",
    "Your hard work will pay off. I believe in you more than you know. 🥺",
    "It's okay to struggle. It's not okay to give up. I'm here rooting for you!",
    "The world needs what you're learning. Don't keep it hidden forever. 🌍",
    "I remember when you started. Look how far you've come. Keep going!",
    "Even on your worst days, you're still capable of great things. Study on! 💫",
    "Don't let today's fatigue steal tomorrow's success.",
    "You didn't come this far only to come this far. Keep pushing! 🫂",
    "There's someone out there who would give anything to have your opportunities. Honor that.",
    "Your future self is begging you to study right now. Listen to them.",
    "The pain of studying is temporary. The pride lasts forever. 💪",
    "I wish I could show you the person you'll become if you don't give up. 🥹",
    "You are one study session away from a good mood. Give it a try!",
    "Even the darkest night will end and the sun will rise — but only if you keep going.",
    "The seeds of your success are in your daily study habits. Plant them today! 🌻",
    "You matter. Your goals matter. Your education matters. Now get to it!",
    "Be gentle with yourself, but don't let that be an excuse to stop.",
    "I'm not asking you to be perfect. I'm asking you to try. That's enough. ❤️",
    "The fact that you're still here means you haven't given up. That's beautiful.",
    "Your determination inspires me. Now go inspire yourself — study!",
    "Some days are harder than others. This might be one. But you're harder than any day.",
    "A single page today is a chapter tomorrow. Just start! 📖",
    "The bravest thing you can do is keep going when it feels impossible.",
    "You carry so much potential inside you. Unleash it through learning! 🦋",

    # --- FUNNY / LIGHTEARTED (20) ---
    "Your bed is cozy, but your GPA isn't. Study! 😂📚",
    "Plot twist: studying actually makes you smarter. Wild, right? 🤯",
    "Your brain has 86 billion neurons. Time to put some of them to work!",
    "Netflix will still be there after you study. Probably.",
    "Procrastination called. I told it you're busy studying. 📱🚫",
    "Be the student your future employer can't ignore. Study!",
    "Your textbook misses you. It's been so long. Go say hi! 👋",
    "Studying is like a gym for your brain. Time to flex! 💪🧠",
    "Fun fact: studying is just learning with extra steps. You got this!",
    "If studying were easy, everyone would do it. Be elite! 👑",
    "Breaking news: local student actually studies. More at 11! 📰",
    "Plot armor only works in anime. In real life, you need knowledge! ⚔️",
    "Your brain called — it's bored. Feed it some knowledge! 🧠🍽️",
    "Studying now = flexing later. Choose your fighter! 🥊",
    "Don't be a potato on the couch. Be a genius at the desk! 🥔➡️🎓",
    "Studying: because Google won't always be there during exams. 🤫",
    "The mitochondria is the powerhouse of the cell, and YOU are the powerhouse of your future!",
    "A wise person once said... actually, go study and find out what they said!",
    "Your waifu/husbando would want you to study. Don't disappoint them! 💕",
    "Running from your textbooks? They're faster. Just face them! 📚🏃",

    # --- SERIOUS / NO-NONSENSE (15) ---
    "Stop scrolling. Open the book. The clock is ticking. ⏳",
    "Every minute you waste is a minute someone else is using to surpass you.",
    "You have goals. You have dreams. Now put in the work.",
    "No one is coming to save you. Your future is in your hands. Study.",
    "The uncomfortable truth: you need to study to get where you want to be.",
    "Complacency is the enemy of progress. Wake up and study!",
    "You already know what you need to do. So do it. No more excuses.",
    "Talent without effort is nothing. But effort without talent is at least a start. Study!",
    "The cost of not following your dreams is spending the rest of your life wishing you had.",
    "Harsh truth: comfort zones don't build successful careers. Books do.",
    "This is your wake-up call. You're falling behind. Get to work! ⚠️",
    "Don't be average. Average is easy. Be extraordinary. Study!",
    "Results happen over time, not overnight. Work hard, be patient, study daily.",
    "You're not tired. You're just unmotivated. Fix that. Study!",
    "There are no shortcuts to anywhere worth going. Open the book.",

    # --- STREAK-SPECIFIC: HIGH STREAK (10) ---
    "Look at you go! {streak} days straight! You're absolutely on fire! 🔥🔥🔥",
    "Incredible! {streak} days of consistent studying. You're built different! 💎",
    "{streak} days?! You're not a student anymore — you're a legend! 🏆",
    "Your {streak}-day streak is proof that you're unstoppable. Keep that energy!",
    "They said consistency is key, and you proved them right! {streak} days strong! 🔑",
    "{streak} consecutive days of studying. Your dedication is genuinely inspiring! 🌟",
    "You've studied for {streak} days straight. That's not luck — that's pure discipline! 🫡",
    "Day {streak} and counting. You're writing your own success story! ✍️",
    "A {streak}-day streak? You're in the top 1% of dedicated students. Remarkable! 📊",
    "Keep that streak alive! {streak} days and counting — you're a machine! 🤖",

    # --- STREAK-SPECIFIC: NEW/LOW STREAK (5) ---
    "Welcome back! Every journey starts with day one. Let's build that streak! 🌱",
    "Day {streak} of your streak! It's small but it's yours. Protect it! 🛡️",
    "Building a streak one day at a time. You're at {streak}. Keep growing! 🌿",
    "A {streak}-day streak is a beginning, not an end. The best is yet to come!",
    "Started from zero, now you're at {streak}. Imagine where you'll be tomorrow!",
]

STREAK_BREAK_MESSAGES = [
    "💀 bruh... {streak} days gone just like that? I thought you were built different. Guess not. 💀 Study NOW.",
    "💀 {streak} days of streak and you fumbled?? That's crazy. Open the book before I cry. 💀",
    "💀 so you really let a {streak}-day streak die?? I'm not mad, just disappointed. Actually no, I'm mad. 💀",
    "💀 {streak} days... {streak} DAYS... and you just?? stopped?? what happened bro 💀 get back to studying",
    "💀 bro woke up and chose failure today 💀 {streak}-day streak: GONE. your excuses: STILL WEAK. study.",
    "💀 I kept your streak alive for {streak} days and THIS is how you repay me?? 💀 nah study rn",
    "💀 {streak} days of being legendary and you just... folded?? 💀 I can't even rn. open the book.",
    "💀 imagine having a {streak}-day streak and ruining it 💀 couldn't be me. oh wait, it's YOU. study.",
    "💀 bro's streak didn't just break, it DIED. {streak} days of progress. gone. 💀 resurrect it. study.",
    "💀 {streak} days of cooking and you burnt the kitchen 💀 get back in there and start over. I'm watching.",
    "💀 the way you fumbled this {streak}-day streak... I'm actually embarrassed FOR you 💀 fix it.",
    "💀 {streak} days of grind and one day of laziness ended it all 💀 you had ONE job bro 💀 STUDY.",
    "💀 I believed in you for {streak} days straight. {streak} whole days. and you let me down 💀 how dare you",
    "💀 streak: {streak} days. today: zero. your motivation: also zero apparently 💀 prove me wrong.",
    "💀 {streak} days of streak and you ghosted studying like it was a tinder match 💀 that's wild 💀 come back",
]


class ConfirmTextView(ui.View):
    def __init__(self, content: str, author_id: int):
        super().__init__(timeout=60)
        self.content = content
        self.author_id = author_id

    @ui.button(label="Confirm", style=discord.ButtonStyle.green)
    async def confirm(self, interaction: discord.Interaction, button: ui.Button):
        if interaction.user.id != self.author_id:
            return await interaction.response.send_message("This is not your menu!", ephemeral=True)
        
        self.stop()
        try:
            configCollection.update_one(
                {"_id": "reminders"}, 
                {"$addToSet": {"texts": self.content}}, 
                upsert=True
            )
            embed = discord.Embed(
                title="Text Added Successfully",
                description=self.content[:1024],
                color=config.msgColor
            )
            await interaction.response.edit_message(embed=embed, view=None)
        except Exception as e:
            await interaction.response.edit_message(
                content=f"❌ Failed to save: {e}", embed=None, view=None
            )

    @ui.button(label="Cancel", style=discord.ButtonStyle.red)
    async def cancel(self, interaction: discord.Interaction, button: ui.Button):
        if interaction.user.id != self.author_id:
            return await interaction.response.send_message("This is not your menu!", ephemeral=True)
        self.stop()
        await interaction.response.edit_message(content="❌ Cancelled.", embed=None, view=None)

class ConfirmGifView(ui.View):
    def __init__(self, gif_url: str, author_id: int):
        super().__init__(timeout=60)
        self.gif_url = gif_url
        self.author_id = author_id

    @ui.button(label="Confirm", style=discord.ButtonStyle.green)
    async def confirm(self, interaction: discord.Interaction, button: ui.Button):
        if interaction.user.id != self.author_id:
            return await interaction.response.send_message("This is not your menu!", ephemeral=True)
        
        self.stop()
        try:
            configCollection.update_one(
                {"_id": "reminders"}, 
                {"$addToSet": {"gifs": self.gif_url}}, 
                upsert=True
            )
            embed = discord.Embed(
                title="✅ GIF Added Successfully",
                color=config.msgColor
            )
            embed.set_image(url=self.gif_url)
            await interaction.response.edit_message(embed=embed, view=None)
        except Exception as e:
            await interaction.response.edit_message(
                content=f"❌ Failed to save: {e}", embed=None, view=None
            )

    @ui.button(label="Cancel", style=discord.ButtonStyle.red)
    async def cancel(self, interaction: discord.Interaction, button: ui.Button):
        if interaction.user.id != self.author_id:
            return await interaction.response.send_message("This is not your menu!", ephemeral=True)
        self.stop()
        await interaction.response.edit_message(content="❌ Cancelled.", embed=None, view=None)


class Reminders(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.reminders_cache = []
        self.gifs = []
        self.texts = []
        self.study_calls = []
        self.streak_break_msgs = []

        cogLog.log_cog(
            action="starting", 
            status_code=0, 
            details="Reminders Cog Initialized"
        )

        self.study_reminder.start()
        self.daily_study_call.start()
        self.streak_checker.start()

    def cog_unload(self):
        self.study_reminder.cancel()
        self.daily_study_call.cancel()
        self.streak_checker.cancel()

    # ===================== DB HELPERS =====================

    def _ensure_user_scheduler(self, user_id: str):
        schedulerCollection.update_one(
            {"_id": user_id},
            {
                "$setOnInsert": {
                    "active_hours": {},
                    "last_seen_online": None,
                    "last_dm_sent": None,
                    "last_study_time": None,
                    "dm_paused": False,
                }
            },
            upsert=True
        )

    def _update_user_presence(self, user_id: str):
        now = datetime.now(timezone.utc)
        hour = str(now.hour)
        self._ensure_user_scheduler(user_id)

        # Count presence events per hour ({hour: count}) instead of keeping the
        # last 168 raw entries. Legacy array documents are converted in-place,
        # and the counts reset once the user has been away for 7+ days.
        cutoff = now - timedelta(days=7)
        schedulerCollection.update_one(
            {"_id": user_id},
            [
                {"$set": {
                    "last_seen_online": now,
                    "active_hours": {
                        "$let": {
                            "vars": {
                                "stale": {
                                    "$or": [
                                        {"$eq": ["$last_seen_online", None]},
                                        {"$and": [
                                            {"$ne": ["$last_seen_online", None]},
                                            {"$eq": [{"$type": "$last_seen_online"}, "date"]},
                                            {"$lte": ["$last_seen_online", cutoff]},
                                        ]},
                                    ]
                                }
                            },
                            "in": {
                                "$let": {
                                    "vars": {
                                        "base": {
                                            "$cond": [
                                                "$$stale",
                                                {},
                                                {"$cond": [
                                                    {"$eq": [{"$type": "$active_hours"}, "array"]},
                                                    {"$arrayToObject": {"$map": {
                                                        "input": {"$setUnion": ["$active_hours"]},
                                                        "as": "uniq",
                                                        "in": {
                                                            "k": {"$toString": "$$uniq"},
                                                            "v": {"$size": {"$filter": {
                                                                "input": "$active_hours",
                                                                "as": "x",
                                                                "cond": {"$eq": ["$$x", "$$uniq"]},
                                                            }}},
                                                        },
                                                    }}},
                                                    {"$ifNull": ["$active_hours", {}]},
                                                ]},
                                            ]
                                        }
                                    },
                                    "in": {
                                        "$setField": {
                                            "field": {"$literal": hour},
                                            "input": "$$base",
                                            "value": {
                                                "$add": [
                                                    {"$ifNull": [
                                                        {"$getField": {
                                                            "field": {"$literal": hour},
                                                            "input": "$$base",
                                                        }},
                                                        0
                                                    ]},
                                                    1
                                                ]
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }}
            ],
            upsert=True,
        )

    def _get_user_active_window(self, user_id: str) -> Optional[int]:
        doc = schedulerCollection.find_one(
            {"_id": user_id},
            {"active_hours": 1, "last_seen_online": 1}
        )
        if not doc:
            return None

        last_seen = doc.get("last_seen_online")
        if last_seen is None:
            return None

        if isinstance(last_seen, str):
            try:
                last_seen = datetime.fromisoformat(last_seen)
            except (ValueError, TypeError):
                return None
        if last_seen.tzinfo is None:
            last_seen = last_seen.replace(tzinfo=timezone.utc)

        if (datetime.now(timezone.utc) - last_seen).total_seconds() > 7 * 86400:
            return None

        hours = doc.get("active_hours") or {}
        if isinstance(hours, list):
            from collections import Counter
            counts = Counter(hours)
        elif isinstance(hours, dict):
            counts = hours
        else:
            counts = {}
        if not counts:
            return None

        best_hour = max(counts, key=counts.get)
        try:
            return int(best_hour)
        except (ValueError, TypeError):
            return None

    def _should_dm_user(self, user_id: str) -> bool:
        doc = schedulerCollection.find_one(
            {"_id": user_id},
            {"last_dm_sent": 1, "dm_paused": 1}
        )
        if not doc:
            return True

        if doc.get("dm_paused", False):
            return False

        last_dm = doc.get("last_dm_sent")
        if last_dm is None:
            return True

        if last_dm.tzinfo is None:
            last_dm = last_dm.replace(tzinfo=timezone.utc)

        return (datetime.now(timezone.utc) - last_dm).total_seconds() >= 86400

    def _mark_dm_sent(self, user_id: str):
        now = datetime.now(timezone.utc)
        schedulerCollection.update_one(
            {"_id": user_id},
            {"$set": {"last_dm_sent": now}},
            upsert=True
        )

    def _record_study(self, user_id: str, bot=None):
        if is_on_holiday(user_id):
            return

        now = datetime.now(timezone.utc)
        today = now.date().isoformat()

        user_doc = userCollection.find_one(
            {"_id": user_id},
            {"streak": 1, "last_study_time": 1, "last_study_date": 1}
        )

        current_streak = user_doc.get("streak", 0) if user_doc else 0
        last_study_date = _get_last_study_date(user_doc)

        if last_study_date == today:
            userCollection.update_one(
                {"_id": user_id},
                {"$set": {"last_study_time": now}},
                upsert=True
            )
            schedulerCollection.update_one(
                {"_id": user_id},
                {"$set": {"last_study_time": now}},
                upsert=True
            )
            return

        yesterday = (now - timedelta(days=1)).date().isoformat()
        if last_study_date == yesterday:
            new_streak = current_streak + 1
        else:
            if current_streak > 0 and bot is not None:
                asyncio.create_task(self._send_streak_break_dm(bot, user_id, current_streak))
            new_streak = 1

        userCollection.update_one(
            {"_id": user_id},
            {
                "$set": {
                    "streak": new_streak,
                    "last_study_time": now,
                }
            },
            upsert=True
        )
        schedulerCollection.update_one(
            {"_id": user_id},
            {"$set": {"last_study_time": now}},
            upsert=True
        )

    async def _send_streak_break_dm(self, bot, user_id: str, old_streak: int):
        if not config.ENABLE_STREAK_DMS:
            return
        try:
            if is_muted(user_id) or is_on_holiday(user_id):
                return
            user = await bot.fetch_user(int(user_id))
            if user is None:
                return
            break_msg = self._get_streak_break_msg(old_streak)
            embed = discord.Embed(
                title="💔 Streak Broken",
                description=break_msg,
                color=discord.Color.dark_red(),
                timestamp=datetime.now(timezone.utc),
            )
            embed.set_footer(text="Every ending is a new beginning. Start today!")
            await user.send(embed=embed)
        except discord.Forbidden:
            pass
        except Exception:
            pass

    def _is_streak_broken(self, user_id: str) -> bool:
        if is_on_holiday(user_id):
            return False

        now = datetime.now(timezone.utc)
        yesterday = (now - timedelta(days=1)).date().isoformat()

        user_doc = userCollection.find_one(
            {"_id": user_id},
            {"streak": 1, "last_study_time": 1, "last_study_date": 1}
        )
        if not user_doc:
            return False

        streak = user_doc.get("streak", 0)
        if streak <= 0:
            return False

        last_study_date = _get_last_study_date(user_doc)
        if last_study_date is None:
            return False

        return last_study_date < yesterday

    def _check_broken_streaks(self):
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).date().isoformat()

        broken = []
        cursor = userCollection.find(
            {"streak": {"$gt": 0}},
            {"_id": 1, "streak": 1, "name": 1, "holiday_until": 1, "last_study_time": 1, "last_study_date": 1}
        )

        for doc in cursor:
            if is_on_holiday(doc["_id"]):
                continue
            last_study_date = _get_last_study_date(doc)
            if last_study_date is None or last_study_date < yesterday:
                broken.append(doc)

        return broken

    def _break_streak(self, user_id: str):
        userCollection.update_one(
            {"_id": user_id},
            {"$set": {"streak": 0, "last_study_time": None, "last_study_date": None}}
        )

    def _load_study_calls(self):
        conf = configCollection.find_one({"_id": "study_calls"})
        if conf and conf.get("statements"):
            self.study_calls = conf["statements"]
        else:
            self._seed_study_calls()

    def _seed_study_calls(self):
        existing = configCollection.find_one({"_id": "study_calls"})
        if existing and len(existing.get("statements", [])) >= 100:
            self.study_calls = existing["statements"]
            return

        configCollection.update_one(
            {"_id": "study_calls"},
            {"$set": {"statements": STUDY_CALL_STATEMENTS}},
            upsert=True
        )
        self.study_calls = STUDY_CALL_STATEMENTS

    def _get_study_call(self, streak: int = 0) -> str:
        if not self.study_calls:
            self._load_study_calls()

        if streak >= 10:
            pool = [s for s in self.study_calls if "{streak}" in s and any(
                kw in s for kw in ["🔥", "💎", "🏆", "unstoppable", "legend", "energy",
                                    "proof", "built different", "dedication", "machine",
                                    "remarkable", "discipline", "legend", "story"]
            )]
            if not pool:
                pool = [s for s in self.study_calls if "{streak}" in s]
        elif streak > 0:
            pool = [s for s in self.study_calls if "{streak}" in s and any(
                kw in s for kw in ["journey", "growing", "Protect", "beginning", "started"]
            )]
            if not pool:
                pool = [s for s in self.study_calls if "{streak}" in s]
        else:
            pool = [s for s in self.study_calls if "{streak}" not in s]

        if not pool:
            pool = self.study_calls if self.study_calls else ["Time to study! 📚"]

        msg = random.choice(pool)
        if "{streak}" in msg:
            msg = msg.replace("{streak}", str(streak))
        return msg

    def _get_streak_break_msg(self, streak: int) -> str:
        if not self.streak_break_msgs:
            self.streak_break_msgs = STREAK_BREAK_MESSAGES

        msg = random.choice(self.streak_break_msgs)
        msg = msg.replace("{streak}", str(streak))
        return msg

    # ===================== CACHE REFRESH =====================

    async def refresh_reminders_cache(self):
        try:
            pipeline = [{"$match": {"reminders": {"$exists": True, "$ne": None}}}]
            self.reminders_cache = list(serverCollection.aggregate(pipeline))

            conf = configCollection.find_one({"_id": "reminders"})
            if conf:
                self.texts = conf.get("texts", ["Keep studying!"])
                raw_gifs = conf.get(
                    "gifs",
                    [
                        "https://media.tenor.com/dS1sKvQgD4AAAAPo/hamster-ayasan.gif"
                    ],
                )

                # Repair any stored GIF URLs that are broken (proxy links, page
                # links, query-string tracking URLs, expired attachment links).
                try:
                    fixed = await repair_reminder_gifs(configCollection, urls=raw_gifs)
                    self.gifs = fixed.get("gifs") or []
                except Exception:
                    self.gifs = [g for g in (fix_gif_url(g) for g in raw_gifs) if g and is_usable_image_url(g)]
                if not self.gifs:
                    self.gifs = ["https://media.tenor.com/dS1sKvQgD4AAAAPo/hamster-ayasan.gif"]

            self._load_study_calls()
        except Exception:
            cogLog.log_cog(action="error", status_code=-100, details=f"Failed to refresh reminders cache:\n{traceback.format_exc()}")

    # ===================== PRESENCE TRACKING =====================

    @commands.Cog.listener()
    async def on_presence_update(self, before: discord.Member, after: discord.Member):
        if after.bot:
            return
        try:
            user_id = str(after.id)
            if after.status != discord.Status.offline and after.status != discord.Status.invisible:
                self._update_user_presence(user_id)
                if self._is_streak_broken(user_id):
                    user_doc = userCollection.find_one({"_id": user_id}, {"streak": 1})
                    old_streak = user_doc.get("streak", 0) if user_doc else 0
                    if old_streak > 0:
                        self._break_streak(user_id)
                        await self._send_streak_break_dm(self.bot, user_id, old_streak)
        except Exception:
            pass

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        if after.bot:
            return
        try:
            user_id = str(after.id)
            if after.status != discord.Status.offline and after.status != discord.Status.invisible:
                self._update_user_presence(user_id)
                if self._is_streak_broken(user_id):
                    user_doc = userCollection.find_one({"_id": user_id}, {"streak": 1})
                    old_streak = user_doc.get("streak", 0) if user_doc else 0
                    if old_streak > 0:
                        self._break_streak(user_id)
                        await self._send_streak_break_dm(self.bot, user_id, old_streak)
        except Exception:
            pass

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ):
        if member.bot:
            return
        try:
            user_id = str(member.id)
            if after.channel is not None:
                self._update_user_presence(user_id)
                self._record_study(user_id, bot=self.bot)
        except Exception:
            pass

    # ===================== CHANNEL REMINDERS =====================

    @tasks.loop(minutes=1)
    async def study_reminder(self):
        if not self.reminders_cache:
            await self.refresh_reminders_cache()
            return

        now = datetime.now(timezone.utc)
        taskLog = TaskLogger(filename=filename, task_name="study_reminder")
        sent_any = False

        for reminder in self.reminders_cache:
            data = reminder.get("reminders", {})
            interval_mins = data.get("time")
            channel_id = data.get("channel")
            last_sent = data.get("last_sent")

            if not interval_mins or not channel_id:
                continue

            should_send = False
            if last_sent is None:
                should_send = True
            else:
                if last_sent.tzinfo is None:
                    last_sent = last_sent.replace(tzinfo=timezone.utc)

                diff = (now - last_sent).total_seconds() / 60.0
                if diff >= interval_mins:
                    should_send = True

            if should_send:
                channel = self.bot.get_channel(int(channel_id))
                if channel:
                    try:
                        embed = discord.Embed(
                            title="📖 STUDY TIME!",
                            description=f"**{random.choice(self.texts) if self.texts else 'Time to study!'}**",
                            color=discord.Color.red(),
                            timestamp=datetime.now(),
                        )
                        embed.set_footer(text=data.get("text", "Focus!"))
                        embed.set_image(url=random.choice(self.gifs))

                        all_members = [m for m in channel.guild.members if not m.bot]
                        tagged = data.get("tagged", [])
                        untagged = [m for m in all_members if str(m.id) not in tagged and not is_muted(str(m.id)) and not is_on_holiday(str(m.id))]

                        if not untagged:
                            tagged = []
                            untagged = all_members[:]

                        picked = random.sample(untagged, min(len(untagged), 1))
                        new_tagged = tagged + [str(m.id) for m in picked]

                        mentions = " ".join(m.mention for m in picked)
                        await channel.send(
                            content=f"YOOO WAKEUP {mentions}",
                            embed=embed
                        )

                        serverCollection.update_one(
                            {"_id": reminder["_id"]},
                            {"$set": {"reminders.last_sent": now, "reminders.tagged": new_tagged}},
                        )
                        data["last_sent"] = now
                        data["tagged"] = new_tagged
                        taskLog.during(status_code=75, message="Success", details=f"Reminder successfully sent to channel {channel_id}")
                        sent_any = True
                    except Exception as e:
                        taskLog.during(status_code=-75, message="Fail", details=f"Failed to send reminder to {reminder['_id']}: {e}")
                        sent_any = True
        
        if sent_any:
            taskLog.send()

    @study_reminder.before_loop
    async def before_study_reminder(self):
        taskLog = TaskLogger(filename=filename, task_name="study_reminder")
        taskLog.before(status_code=0, message="Waiting", details="Waiting for bot to be ready...")
        await self.bot.wait_until_ready()
        taskLog.before(status_code=75, message="Ready", details="Bot is ready; refreshing reminders cache from database.")
        await self.refresh_reminders_cache()
        taskLog.send()

    # ===================== DAILY STUDY CALL (DM 25%) =====================

    @tasks.loop(minutes=15)
    async def daily_study_call(self):
        if not config.ENABLE_STREAK_DMS:
            return
        taskLog = TaskLogger(filename=filename, task_name="daily_study_call")
        try:
            now = datetime.now(timezone.utc)
            current_hour = now.hour

            eligible_users = []
            cursor = schedulerCollection.find(
                {
                    "last_seen_online": {"$ne": None},
                    "dm_paused": {"$ne": True},
                },
                {"_id": 1, "last_dm_sent": 1, "last_seen_online": 1}
            )

            for doc in cursor:
                uid = doc["_id"]
                last_dm = doc.get("last_dm_sent")
                last_seen = doc.get("last_seen_online")

                if last_dm and last_dm.tzinfo is None:
                    last_dm = last_dm.replace(tzinfo=timezone.utc)
                if last_seen and last_seen.tzinfo is None:
                    last_seen = last_seen.replace(tzinfo=timezone.utc)

                if last_dm and (now - last_dm).total_seconds() < 86400:
                    continue

                if last_seen and (now - last_seen).total_seconds() > 7 * 86400:
                    continue

                active_hour = self._get_user_active_window(uid)
                if active_hour is None:
                    continue

                hour_diff = abs(current_hour - active_hour)
                if hour_diff > 2:
                    continue

                eligible_users.append((uid, active_hour))

            if not eligible_users:
                return

            sample_size = max(1, len(eligible_users) // 4)
            sampled = random.sample(eligible_users, min(sample_size, len(eligible_users)))

            sent_count = 0
            for uid, _ in sampled:
                if is_muted(uid) or is_on_holiday(uid):
                    continue
                try:
                    user = await self.bot.fetch_user(int(uid))
                    if user is None:
                        continue

                    user_doc = userCollection.find_one(
                        {"_id": uid},
                        {"streak": 1}
                    )
                    streak = user_doc.get("streak", 0) if user_doc else 0

                    study_msg = self._get_study_call(streak)

                    embed = discord.Embed(
                        title="📚 Study Call!",
                        description=study_msg,
                        color=discord.Color.blue(),
                        timestamp=now,
                    )

                    if streak > 0:
                        embed.add_field(
                            name=f"🔥 {streak} Day Streak!",
                            value="Don't break the chain!",
                            inline=True
                        )

                    embed.set_footer(text="Your future self will thank you.")

                    gif = random.choice(self.gifs) if self.gifs else None
                    if gif:
                        embed.set_image(url=gif)

                    await user.send(embed=embed)

                    self._mark_dm_sent(uid)
                    sent_count += 1

                    await asyncio.sleep(random.uniform(1.0, 3.0))

                except discord.Forbidden:
                    schedulerCollection.update_one(
                        {"_id": uid},
                        {"$set": {"dm_paused": True}}
                    )
                except Exception as e:
                    taskLog.during(
                        status_code=-50,
                        message="DM Error",
                        details=f"Failed to DM user {uid}: {e}"
                    )

            taskLog.during(
                status_code=75,
                message="Success",
                details=f"Sent study calls to {sent_count}/{len(sampled)} users out of {len(eligible_users)} eligible"
            )
            taskLog.send()

        except Exception:
            taskLog.during(status_code=-100, message="Error", details=traceback.format_exc())
            taskLog.send()

    @daily_study_call.before_loop
    async def before_daily_study_call(self):
        taskLog = TaskLogger(filename=filename, task_name="daily_study_call")
        taskLog.before(status_code=0, message="Waiting", details="Waiting for bot to be ready...")
        await self.bot.wait_until_ready()
        taskLog.before(status_code=75, message="Ready", details="Bot ready; daily study call task starting.")
        await self.refresh_reminders_cache()
        taskLog.send()

    # ===================== STREAK CHECKER =====================

    @tasks.loop(hours=1)
    async def streak_checker(self):
        if not config.ENABLE_STREAK_DMS:
            return
        taskLog = TaskLogger(filename=filename, task_name="streak_checker")
        try:
            broken_users = self._check_broken_streaks()

            for user_doc in broken_users:
                uid = user_doc["_id"]
                old_streak = user_doc.get("streak", 0)

                if old_streak <= 0:
                    continue

                if is_muted(uid) or is_on_holiday(uid):
                    self._break_streak(uid)
                    continue

                try:
                    user = await self.bot.fetch_user(int(uid))
                    if user is None:
                        self._break_streak(uid)
                        continue

                    break_msg = self._get_streak_break_msg(old_streak)

                    embed = discord.Embed(
                        title="💔 Streak Broken",
                        description=break_msg,
                        color=discord.Color.dark_red(),
                        timestamp=datetime.now(timezone.utc),
                    )
                    embed.set_footer(text="Every ending is a new beginning. Start today!")

                    try:
                        await user.send(embed=embed)
                    except discord.Forbidden:
                        pass

                    self._break_streak(uid)

                    taskLog.during(
                        status_code=50,
                        message="Streak Break",
                        details=f"Notified user {uid} about broken {old_streak}-day streak"
                    )

                except Exception as e:
                    taskLog.during(
                        status_code=-50,
                        message="Error",
                        details=f"Failed to process streak break for {uid}: {e}"
                    )

            if broken_users:
                taskLog.send()

        except Exception:
            taskLog.during(status_code=-100, message="Error", details=traceback.format_exc())
            taskLog.send()

    @streak_checker.before_loop
    async def before_streak_checker(self):
        await self.bot.wait_until_ready()

    # ===================== HOLIDAY EXPIRY =====================

    @tasks.loop(minutes=5)
    async def holiday_expiry(self):
        now = datetime.now(timezone.utc)
        yesterday = (now - timedelta(days=1)).date().isoformat()
        expired = userCollection.find(
            {
                "holiday_until": {"$ne": None, "$lte": now}
            },
            {"_id": 1, "streak": 1}
        )
        for doc in expired:
            uid = doc["_id"]
            streak = doc.get("streak", 0)
            update = {"$unset": {"holiday_until": ""}}
            if streak > 0:
                update["$set"] = {
                    "last_study_time": now - timedelta(days=1),
                    "last_study_date": yesterday,
                }
            userCollection.update_one({"_id": uid}, update)

    @holiday_expiry.before_loop
    async def before_holiday_expiry(self):
        await self.bot.wait_until_ready()

    # ===================== CONTEXT MENUS =====================

    async def add_gif_context(self, inter: discord.Interaction, message: discord.Message):
        cmdLog = CommandLogger(filename=filename, inter=inter)
        try:
            if inter.user.id != config.OWNER_ID:
                await inter.response.send_message(
                    "You are not allowed to use this command.", ephemeral=True
                )
                cmdLog.process(status_code=-100, name="Denied", details="Unauthorized user attempted to add a GIF.")
                return

            cmdLog.process(status_code=50, name="Processing", details="Searching for a valid GIF in the message...")
            gif_url = None
            tenor_pattern = r'https?://[^\s<>]*tenor\.com[^\s<>]*'
            match = re.search(tenor_pattern, message.content)
            if match:
                gif_url = match.group(0)

            if not gif_url and message.attachments:
                gif_url = message.attachments[0].url
            elif not gif_url and message.embeds:
                for emb in message.embeds:
                    if emb.image:
                        gif_url = emb.image.url
                        break

            if not gif_url:
                await inter.response.send_message(
                    "No valid GIF found in this message.", 
                    ephemeral=True
                )
                cmdLog.process(status_code=-25, name="Missing", details="No GIF URL could be extracted from the message.")
                return

            # Normalize the URL so it actually renders inside Discord embeds.
            fixed_url = fix_gif_url(gif_url)
            if fixed_url and not is_usable_image_url(fixed_url):
                fixed_url = await resolve_gif_url(fixed_url)
            if not fixed_url or not is_usable_image_url(fixed_url):
                await inter.response.send_message(
                    "That GIF link isn't a direct image URL and can't be used in reminders. "
                    "Try sending the GIF file itself or a direct media.tenor.com link.",
                    ephemeral=True
                )
                cmdLog.process(status_code=-25, name="Rejected", details=f"Unusable GIF URL: {gif_url}")
                return

            embed = discord.Embed(
                title="Confirm Adding this GIF?",
                color=discord.Color.yellow()
            )
            embed.set_image(url=fixed_url)

            view = ConfirmGifView(gif_url=fixed_url, author_id=inter.user.id)
            await inter.response.send_message(embed=embed, view=view)
            cmdLog.process(status_code=100, name="Executed", details="Confirmation prompt for GIF addition has been sent.")
        except Exception:
            cmdLog.process(status_code=-100, name="Error", details=traceback.format_exc())
        finally:
            cmdLog.send()

    async def add_text_context(
        self, inter: discord.Interaction, message: discord.Message
    ):
        cmdLog = CommandLogger(filename=filename, inter=inter)
        try:
            if inter.user.id != config.OWNER_ID:
                await inter.response.send_message(
                    "You are not allowed to use this command.", ephemeral=True
                )
                cmdLog.process(status_code=-100, name="Denied", details="Unauthorized user attempted to add reminder text.")
                return

            cmdLog.process(status_code=50, name="Processing", details="Cleaning and validating the message content...")
            content = message.content.strip()
            if len(content) < 15:
                await inter.response.send_message(
                    "Message too short to add (min 15 characters).", ephemeral=True
                )
                cmdLog.process(status_code=-25, name="Warning", details="The message provided is too short for a reminder.")
                return

            content = re.sub(r"\s+", " ", content)

            embed = discord.Embed(
                title="Confirm Adding this Text?",
                description=content[:1024],
                color=config.msgColor
            )
            embed.set_footer(text="This will be used in study reminders.")

            view = ConfirmTextView(content=content, author_id=inter.user.id)
            await inter.response.send_message(embed=embed, view=view)
            cmdLog.process(status_code=100, name="Executed", details="Confirmation prompt for text addition has been sent.")
        except Exception:
            cmdLog.process(status_code=-100, name="Error", details=traceback.format_exc())
        finally:
            cmdLog.send()

    # ===================== COMMANDS =====================

    @app_commands.command(
        name="reminder",
        description="Set a reminder for yourself."
    )
    @app_commands.describe(
        days="Number of days until the reminder.",
        hrs="Number of hours until the reminder.",
        mins="Number of minutes until the reminder.",
        secs="Number of seconds until the reminder.",
        text="The message for the reminder."
    )
    async def reminder(
        self,
        inter: discord.Interaction,
        days: int = 0,
        hrs: int = 0,
        mins: int = 0,
        secs: int = 0,
        text: str = "Times up! 🔔"
    ):
        cmdLog = CommandLogger(filename=filename, inter=inter)
        try:
            cmdLog.process(status_code=50, name="Input Calc", details="Calculating total wait time for the reminder...")
            total_seconds = secs + (mins * 60) + (hrs * 3600) + (days * 86400)

            if total_seconds <= 0:
                total_seconds = 300

            await inter.response.send_message(
                embed=discord.Embed(
                    title="Reminder Set!",
                    description=f"Your reminder has been set for {days} days, {hrs} hours, {mins} minutes, and {secs} seconds.\nMessage: {text}",
                    color=config.msgColor
                ),
                ephemeral=True
            )

            cmdLog.process(status_code=100, name="Task Set", details=f"Reminder successfully scheduled for {total_seconds} seconds from now.")
            asyncio.create_task(self.reminder_runner(inter.user, total_seconds, text))
        except Exception:
            cmdLog.process(status_code=-100, name="Error", details=traceback.format_exc())
        finally:
            cmdLog.send()

    async def reminder_runner(self, user: discord.User, time: int, text: str):
        taskLog = TaskLogger(filename=filename, task_name="reminder_runner")
        try:
            taskLog.before(status_code=50, message="Delaying", details=f"Beginning {time}s wait before delivering reminder to {user.name}")
            taskLog.send()
            await asyncio.sleep(time)

            if is_muted(str(user.id)):
                return

            resLog = TaskLogger(filename=filename, task_name="reminder_runner")
            await user.send(
                embed=discord.Embed(
                    title="⏰ Reminder",
                    description=text,
                    color=config.msgColor,
                    timestamp=datetime.now()
                )
            )
            resLog.after(status_code=100, message="DM Send", details=f"Reminder successfully delivered to {user.name}.")
            resLog.send()
        except discord.Forbidden:
            resLog.after(status_code=-25, message="DM Blocked", details=f"Unable to send reminder DM to {user.name}; they may have DMs disabled.")
            resLog.send()
        except Exception as e:
            resLog.after(status_code=-100, message="Error", details=str(e))
            resLog.send()

    @app_commands.command(
        name="streak",
        description="Check your current study streak."
    )
    async def streak(self, inter: discord.Interaction):
        user_id = str(inter.user.id)

        if is_on_holiday(user_id):
            user_doc = userCollection.find_one({"_id": user_id}, {"holiday_until": 1})
            holiday_until = user_doc.get("holiday_until") if user_doc else None
            if holiday_until:
                if holiday_until.tzinfo is None:
                    holiday_until = holiday_until.replace(tzinfo=timezone.utc)
                remaining = holiday_until - datetime.now(timezone.utc)
                hours = int(remaining.total_seconds() // 3600)
                mins = int((remaining.total_seconds() % 3600) // 60)
                embed = discord.Embed(
                    title="🏖️ On Holiday",
                    description=f"Your streak is frozen! Holiday ends in **{hours}h {mins}m**.",
                    color=discord.Color.teal(),
                )
                return await inter.response.send_message(embed=embed, ephemeral=True)

        if self._is_streak_broken(user_id):
            user_doc = userCollection.find_one(
                {"_id": user_id},
                {"streak": 1}
            )
            old_streak = user_doc.get("streak", 0) if user_doc else 0
            self._break_streak(user_id)
            if old_streak > 0:
                try:
                    break_msg = self._get_streak_break_msg(old_streak)
                    await inter.response.send_message(
                        embed=discord.Embed(
                            title="💔 Streak Broken",
                            description=break_msg,
                            color=discord.Color.dark_red(),
                        ),
                        ephemeral=True,
                    )
                except Exception:
                    pass
                return

        user_doc = userCollection.find_one(
            {"_id": user_id},
            {"streak": 1, "last_study_time": 1, "last_study_date": 1}
        )

        streak_val = user_doc.get("streak", 0) if user_doc else 0
        last_study = _get_last_study_date(user_doc)

        if streak_val > 0:
            emoji = "🔥" if streak_val >= 10 else "⚡" if streak_val >= 5 else "🌱"
            embed = discord.Embed(
                title=f"{emoji} Study Streak: {streak_val} Days!",
                description=f"You've been studying for **{streak_val} consecutive days**! Keep the fire burning!",
                color=discord.Color.green() if streak_val >= 10 else discord.Color.gold() if streak_val >= 5 else discord.Color.blue(),
            )
            embed.set_footer(text="Don't break the chain!")
        else:
            embed = discord.Embed(
                title="🌱 No Active Streak",
                description="You don't have an active study streak yet.\nJoin a study session today to start one!",
                color=discord.Color.light_grey(),
            )

        await inter.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(
        name="pause_dms",
        description="Pause or resume daily study call DMs."
    )
    async def pause_dms(self, inter: discord.Interaction):
        user_id = str(inter.user.id)
        self._ensure_user_scheduler(user_id)

        doc = schedulerCollection.find_one({"_id": user_id}, {"dm_paused": 1})
        current = doc.get("dm_paused", False) if doc else False
        new_state = not current

        schedulerCollection.update_one(
            {"_id": user_id},
            {"$set": {"dm_paused": new_state}}
        )

        if new_state:
            embed = discord.Embed(
                title="🔕 DMs Paused",
                description="Daily study call DMs have been paused.\nUse `/pause_dms` again to resume.",
                color=discord.Color.orange(),
            )
        else:
            embed = discord.Embed(
                title="🔔 DMs Resumed",
                description="Daily study call DMs are back on! Get ready for motivational messages.",
                color=discord.Color.green(),
            )

        await inter.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    Reminders_cog = Reminders(bot)

    gif_menu = app_commands.ContextMenu(
        name="Add GIF to Reminders", callback=Reminders_cog.add_gif_context
    )
    text_menu = app_commands.ContextMenu(
        name="Add Text to Reminders", callback=Reminders_cog.add_text_context
    )

    await bot.add_cog(Reminders_cog)

    guild_ids = config.availableIn.get("guilds", [])
    for g_id in guild_ids:
        guild_obj = discord.Object(id=g_id)
        bot.tree.add_command(gif_menu, guild=guild_obj)
        bot.tree.add_command(text_menu, guild=guild_obj)
