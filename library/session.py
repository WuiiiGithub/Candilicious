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
   
