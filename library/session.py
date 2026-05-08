import jwt
from library import (
    datetime, timedelta, UTC,
    os, discord, tasks, sleep,
    userCollection,
    exceptionCollection
)
from .logging import CogLogger

filename = "Session"
log = CogLogger(filename=filename)

class sessionLearners:
    def __init__(self):
        self.learners = {}

    def started(self, id: str):
        self.learners[id] = datetime.now()
        log.log_important(
            event_name="Session Start",
            status_code=50,
            details=f"A new study session has been initiated for User ID: {id}."
        )

    def cancel(self, id: str):
        self.learners.pop(id, None)
        log.log_important(
            event_name="Session Cancel",
            status_code=-25,
            details=f"The active study session for User ID: {id} has been cancelled."
        )

    def ended(self, name: str, user_id: str, server_id: str):
        if userCollection is None:
            log.log_important(
                event_name="Database Error",
                status_code=-100,
                details="Database collection is unavailable; cannot record session data."
            )
            return

        if user_id not in self.learners:
            log.log_important(
                event_name="Session Warning",
                status_code=-25,
                details=f"No active session found for User ID: {user_id}; skipping database update."
            )
            return  

        secs = (datetime.now() - self.learners[user_id]).total_seconds()

        log.log_important(
            event_name="Session End",
            status_code=100,
            details=f"Session concluded for {name} ({user_id}) on Server: {server_id}. Duration: {secs:.2f} seconds added."
        )

        userCollection.update_one(
            {"_id": user_id},
            {
                "$inc": {
                    f"servers.{server_id}.time": secs, 
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
        
    def add(self, data_id: str):
        self.data[data_id] = tasks.create_task(self.waitAndRemove(data_id))

    def isInside(self, data_id):
        isInList = data_id in self.data
        doc = exceptionCollection.find_one({"user_id": data_id})
        print(data_id)
        print(doc)
        isInDB = False if doc == None else True
        return isInList or isInDB
    
    def isNotInside(self, data_id):
        return not self.isInside(data_id)
    
    async def waitAndRemove(self, data_id: int):
        await sleep(300)
        self.data.pop(data_id, None)
   
class tempRecordHandler:
    def __init__(self, data: dict, seconds: int):
        pass
