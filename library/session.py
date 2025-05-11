import jwt
from library import (
    datetime, timedelta, UTC,
    os, discord, tasks, sleep,
    learnerCollection
)
class sessionLearners:
    def __init__(self):
        self.learners = {}

    def started(self, id: str):
        self.learners[id] = datetime.now()
        print(f"📌 Session started for {str(id)} at {self.learners[id]}.")

    def cancel(self, id: str):
        self.learners.pop(id, None)
        print("Session Cancelled!")

    def ended(self, name: str, user_id: str, server_id: str):
        if learnerCollection is None:
            print("❌ Database collection is None! Cannot update session.")
            return

        if user_id not in self.learners:
            print(f"⚠️ No active session found for {user_id}, skipping database update.")
            return  

        hrs = (datetime.now() - self.learners[user_id]).total_seconds()/3600

        if hrs*60*60 > 300:
            print(f"⏳ Skipping update for {user_id}, no meaningful time spent.")
            return

        print(f"📢 Ending session for {str(user_id)} on server {str(server_id)}: +{hrs} hrs.")

        learnerCollection.update_one(
            {"_id": user_id},
            {
                "$inc": {
                    f"servers.{server_id}.time": hrs, 
                },
                "$set": {
                    "name": name
                },
                "$setOnInsert": {"_id": user_id}
            },
            upsert=True
        )

        self.learners.pop(user_id, None)

class TokenManager:
    def __init__(self, secretKey):
        self.secretKey = secretKey

    def genToken(self, data: dict, expireIn: int):
        payload = {
            "data": data,
            "exp": datetime.now(UTC) + timedelta(minutes=expireIn),
            "iat": datetime.now(UTC)
        }
        return jwt.encode(payload, self.secretKey, "HS256")

    def verifyToken(self, token: str):
        try:
            decodedToken = jwt.decode(
                token,
                self.secretKey,
                algorithms=["HS256"]
            )
            return decodedToken
        except jwt.ExpiredSignatureError:
            raise jwt.ExpiredSignatureError("Token has expired")
        except jwt.InvalidTokenError:
            raise jwt.InvalidTokenError("The token provided is invalid.")
        

class tempDataHandler:
    def __init__(self):
        self.data = {}
        
    def add(self, data_id: int):
        self.data[data_id] = tasks.create_task(self.waitAndRemove(data_id))

    def isInside(self, data_id):
        return data_id in self.data
    
    async def waitAndRemove(self, data_id: int):
        await sleep(300)
        self.data.pop(data_id, None)
   
class tempRecordHandler:
    def __init__(self, data: dict, seconds: int):
        pass